import re
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def normalize_zipcode(value: str) -> str:
    zipcode = re.sub(r"\D", "", value)
    if len(zipcode) != 8:
        raise ValueError("must contain exactly 8 digits")
    return zipcode


class ShippingQuoteProduct(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    product_id: int = Field(gt=0)
    variant_id: int | None = Field(default=None, gt=0)
    price: Decimal = Field(ge=0)
    quantity: int = Field(gt=0)


class ShippingQuoteRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )

    zipcode: str
    products: list[ShippingQuoteProduct] = Field(min_length=1)

    @field_validator("zipcode")
    @classmethod
    def validate_zipcode(cls, value: str) -> str:
        return normalize_zipcode(value)
