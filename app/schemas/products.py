from typing import Any
from pydantic import BaseModel


class ProductStockUpdate(BaseModel):
    stock: int | float


class ProductPayload(BaseModel):
    data: dict[str, Any]
