from .common import Resource
from ..normalizers.customer import normalize_address, normalize_customer
from ..normalizers.common import normalized_list


class CustomerResource(Resource):
    path, plural, singular, normalizer = "/customers", "Customers", "customer", staticmethod(normalize_customer)

    async def addresses(self, params=None):
        return normalized_list(await self.client.request("GET", "/customers/addresses", params=params), "Addresses", "address", normalize_address, "addresses")

    async def address(self, resource_id):
        payload = await self.client.request("GET", f"/customers/addresses/{resource_id}")
        return {"success": True, "address": normalize_address(payload.get("Address", payload) if isinstance(payload, dict) else {})}
