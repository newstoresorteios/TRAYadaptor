from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..identifiers import normalize_optional_variant_id


class CartCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

    product_id: str = Field(min_length=1)
    variant_id: str | None = Field(default=None, min_length=1)
    quantity: int = Field(ge=1)
    price: Decimal = Field(ge=0)
    session_id: str = Field(min_length=1, max_length=32)

    @field_validator("product_id")
    @classmethod
    def validate_product_id(cls, value: str) -> str:
        if not value.isascii() or not value.isdecimal() or int(value) < 1:
            raise ValueError("must be a positive numeric identifier")
        return value

    @field_validator("variant_id")
    @classmethod
    def validate_variant_id(cls, value: str | None) -> str | None:
        if value is None or value == "0":
            return None
        if not value.isascii() or not value.isdecimal() or int(value) < 1:
            raise ValueError("must be null, zero, or a positive numeric identifier")
        return value

    @field_validator("session_id")
    @classmethod
    def reject_null_session(cls, value: str) -> str:
        if value.lower() in {"none", "null"}:
            raise ValueError("must be a valid session identifier")
        return value


class CartItemQuantityUpdateRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    product_id: int = Field(gt=0)
    variant_id: int | None = Field(default=None, gt=0)
    quantity: int = Field(ge=1)

    @field_validator("variant_id", mode="before")
    @classmethod
    def normalize_variant_id(cls, value):
        return normalize_optional_variant_id(value)
