from .common import Resource
from ..normalizers.product import normalize_product


class ProductResource(Resource):
    path, plural, singular, normalizer = "/products", "Products", "product", staticmethod(normalize_product)

    async def get_product_stock(self, product_id):
        result = await self.get(product_id)
        return {"success": True, "product_id": str(product_id), "stock": result["product"].get("stock")}

    async def update_product_stock(self, product_id, stock):
        return await self.update(product_id, {"Product": {"stock": stock}})
