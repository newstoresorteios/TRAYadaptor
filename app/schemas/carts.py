from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CartCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

    product_id: str = Field(min_length=1)
    variant_id: str | None = None
    quantity: int = Field(ge=1)
    price: Decimal = Field(ge=0)
    session_id: str | None = None
