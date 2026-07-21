from datetime import datetime, timedelta, timezone
from typing import Any

from ..exceptions import TrayValidationError
from ..normalizers.common import normalized_list


class Resource:
    path = ""
    plural = ""
    singular = ""
    normalizer = staticmethod(lambda value: value)

    def __init__(self, client):
        self.client = client

    async def list(self, params: dict[str, Any] | None = None):
        return normalized_list(await self.client.request("GET", self.path, params=params), self.plural, self.singular, self.normalizer, self.singular + "s")

    async def get(self, resource_id):
        payload = await self.client.request("GET", f"{self.path}/{resource_id}")
        return {"success": True, self.singular: self.normalizer(_unwrap(payload, self.singular))}

    async def create(self, payload):
        return await self.client.request("POST", self.path, json=payload)

    async def update(self, resource_id, payload):
        return await self.client.request("PUT", f"{self.path}/{resource_id}", json=payload)

    async def delete(self, resource_id, payload=None):
        return await self.client.request("DELETE", f"{self.path}/{resource_id}", json=payload)


def _unwrap(payload, singular):
    if isinstance(payload, dict):
        value = payload.get(singular, payload.get(singular.capitalize(), payload.get(singular.capitalize() + "s", payload)))
        if isinstance(value, list):
            value = value[0] if value else {}
        if isinstance(value, dict) and singular.capitalize() in value:
            value = value[singular.capitalize()]
        return value if isinstance(value, dict) else payload
    return {}


def coupon_dates(payload: dict[str, Any], days: int) -> dict[str, Any]:
    result = dict(payload)
    if not result.get("ends_at"):
        start = result.get("starts_at")
        try:
            base = datetime.fromisoformat(start.replace("Z", "+00:00")) if start else datetime.now(timezone.utc)
        except (AttributeError, ValueError):
            base = datetime.now(timezone.utc)
        result["ends_at"] = (base + timedelta(days=days)).isoformat()
    return result


def validate_coupon_relationship(payload: dict[str, Any]):
    groups = ("products", "product_ids", "brands", "brand_ids", "categories", "category_ids")
    active = [group for group in groups if payload.get(group)]
    types = {"products" if "product" in group else "brands" if "brand" in group else "categories" for group in active}
    if len(types) > 1:
        raise TrayValidationError("coupon_relationship_conflict")
