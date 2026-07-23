from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CartCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

    product_id: str = Field(min_length=1)
    variant_id: str | None = Field(default=None, min_length=1)
    quantity: int = Field(ge=1)
    price: Decimal = Field(ge=0)
    session_id: str | None = Field(default=None, min_length=1)

    @field_validator("product_id", "variant_id")
    @classmethod
    def validate_numeric_identifier(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.isascii() or not value.isdecimal() or int(value) < 1:
            raise ValueError("must be a positive numeric identifier")
        return value

    @field_validator("session_id")
    @classmethod
    def reject_null_session(cls, value: str | None) -> str | None:
        if value is not None and value.lower() in {"none", "null"}:
            raise ValueError("must be null or a valid identifier")
        return value
