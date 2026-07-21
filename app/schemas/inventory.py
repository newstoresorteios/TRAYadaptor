from typing import Any
from pydantic import BaseModel


class DistributionStockUpdate(BaseModel):
    product_id: str | None = None
    variation_id: str | None = None
    reference: str | None = None
    stock: int | float
