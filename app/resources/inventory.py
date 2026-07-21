from ..exceptions import TrayValidationError
from ..normalizers.common import normalized_list
from ..normalizers.inventory import normalize_inventory


class InventoryResource:
    def __init__(self, client): self.client = client

    async def distribution_centers(self, params=None):
        return normalized_list(await self.client.request("GET", "/multicd/distribution-centers", params=params), "DistributionCenters", "distribution_center", normalize_inventory, "distribution_centers")

    async def distribution_center(self, resource_id):
        payload = await self.client.request("GET", f"/multicd/distribution-centers/{resource_id}")
        return {"success": True, "distribution_center": normalize_inventory(payload.get("DistributionCenter", payload) if isinstance(payload, dict) else {})}

    async def detailed_product_stock(self, product_id):
        payload = await self.client.request("GET", f"/multicd/stock/detailed/product/{product_id}")
        return normalized_list(payload, "Stock", "inventory", normalize_inventory, "inventory")

    async def update_stock(self, center_id, payload):
        identifiers = [key for key in ("product_id", "variation_id", "reference") if payload.get(key) is not None]
        if len(identifiers) != 1 or payload.get("stock") is None:
            raise TrayValidationError("exactly_one_stock_identifier_required")
        return await self.client.request("PUT", f"/multicd/distribution-centers/{center_id}/stock", json=payload)
