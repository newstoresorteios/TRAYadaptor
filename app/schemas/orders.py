import re
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from .shippings import normalize_zipcode


class OrderShipping(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )

    shipping_id: int = Field(gt=0)
    quotation_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    value: Decimal = Field(ge=0)
    min_period: int | None = Field(default=None, ge=0)
    max_period: int | None = Field(default=None, ge=0)

    @field_validator("quotation_id", mode="before")
    @classmethod
    def stringify_quotation_id(cls, value: Any) -> str:
        return str(value)


class OrderPayment(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    method_id: str = Field(min_length=1)
    name: str = Field(min_length=1)

    @field_validator("method_id", mode="before")
    @classmethod
    def stringify_method_id(cls, value: Any) -> str:
        return str(value)


class OrderCustomer(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    type: Literal["0"]
    name: str = Field(min_length=1)
    cpf: str
    email: str = Field(min_length=3)
    phone: str
    rg: str | None = None
    gender: str | None = None

    @field_validator("cpf")
    @classmethod
    def validate_cpf(cls, value: str) -> str:
        cpf = re.sub(r"\D", "", value)
        if len(cpf) != 11:
            raise ValueError("must contain exactly 11 digits")
        return cpf

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        phone = re.sub(r"\D", "", value)
        if not 10 <= len(phone) <= 11:
            raise ValueError("must contain 10 or 11 digits")
        return phone

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        local, separator, domain = value.partition("@")
        if not separator or not local or "." not in domain:
            raise ValueError("must be a structurally valid email")
        return value

    @field_validator("rg", "gender", mode="before")
    @classmethod
    def omit_blank_optional_values(cls, value: Any) -> Any:
        return None if value is None or str(value).strip() == "" else value


class OrderAddress(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    address: str = Field(min_length=1)
    zip_code: str
    number: str = Field(min_length=1)
    complement: str | None = None
    neighborhood: str = Field(min_length=1)
    city: str = Field(min_length=1)
    state: str
    country: str
    type: Literal["1"]

    @field_validator("zip_code")
    @classmethod
    def validate_zip_code(cls, value: str) -> str:
        return normalize_zipcode(value)

    @field_validator("state")
    @classmethod
    def validate_state(cls, value: str) -> str:
        state = value.upper()
        if len(state) != 2 or not state.isascii() or not state.isalpha():
            raise ValueError("must contain a 2-letter Brazilian state code")
        return state

    @field_validator("country")
    @classmethod
    def normalize_country(cls, value: str) -> str:
        if value.upper() not in {"BRA", "BR"}:
            raise ValueError("must identify Brazil")
        return "BRA"

    @field_validator("complement", mode="before")
    @classmethod
    def omit_blank_complement(cls, value: Any) -> Any:
        return None if value is None or str(value).strip() == "" else value


class OrderProduct(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    product_id: int = Field(gt=0)
    variant_id: int | None = Field(default=None, gt=0)
    price: Decimal = Field(ge=0)
    original_price: Decimal = Field(ge=0)
    quantity: int = Field(gt=0)


class OrderCreateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )

    session_id: str = Field(min_length=1, max_length=32)
    shipping: OrderShipping
    payment: OrderPayment
    customer: OrderCustomer
    address: OrderAddress
    products: list[OrderProduct] = Field(min_length=1)

    @field_validator("session_id")
    @classmethod
    def reject_null_session(cls, value: str) -> str:
        if value.lower() in {"none", "null"}:
            raise ValueError("must be a valid session identifier")
        return value


class OrderShippingUpdateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )

    status_id: int | None = Field(default=None, gt=0)
    shipment: str | None = Field(default=None, min_length=1)
    shipment_value: Decimal | None = Field(default=None, ge=0)
    sending_code: str | None = Field(default=None, min_length=1)
    sending_date: date | None = None
    tracking_url: str | None = Field(default=None, min_length=1)

    @field_validator("tracking_url")
    @classmethod
    def validate_tracking_url(cls, value: str | None) -> str | None:
        if value is not None and not value.lower().startswith(("http://", "https://")):
            raise ValueError("must be an HTTP or HTTPS URL")
        return value

    @model_validator(mode="after")
    def require_at_least_one_field(self):
        if not self.model_fields_set:
            raise ValueError("at least one shipping field is required")
        return self
