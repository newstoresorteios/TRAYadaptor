from typing import Any
from pydantic import BaseModel


class CustomerPayload(BaseModel):
    data: dict[str, Any]
