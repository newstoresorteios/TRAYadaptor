from typing import Any
from pydantic import BaseModel


class CouponPayload(BaseModel):
    data: dict[str, Any]
