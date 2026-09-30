from typing import Any

from ..normalizers.common import normalized_list
from ..normalizers.sold_product import normalize_sold_product


class SoldProductResource:
    def __init__(self, client):
        self.client = client

    async def list(self, params: dict[str, Any] | None = None):
        payload = await self.client.request(
            "GET",
            "/products_solds",
            params=params,
        )
        return normalized_list(
            payload,
            "ProductsSolds",
            "products_sold",
            normalize_sold_product,
            "sold_products",
        )
