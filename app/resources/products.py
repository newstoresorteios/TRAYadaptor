from typing import Any

from .common import Resource
from ..normalizers.product import normalize_product
from ..product_search import paginate_products, product_matches_tokens


class ProductResource(Resource):
    path, plural, singular, normalizer = "/products", "Products", "product", staticmethod(normalize_product)

    # Tray list pages used as candidate pool for local AND/ILIKE filtering.
    _SEARCH_TRAY_LIMIT = 50
    _SEARCH_MAX_PAGES = 40

    async def get_product_stock(self, product_id):
        result = await self.get(product_id)
        return {"success": True, "product_id": str(product_id), "stock": result["product"].get("stock")}

    async def update_product_stock(self, product_id, stock):
        return await self.update(product_id, {"Product": {"stock": stock}})

    async def search_by_tokens(
        self,
        tokens: list[str],
        *,
        brand: str | None = None,
        limit: int = 20,
        page: int = 1,
    ) -> dict[str, Any]:
        candidates = await self._collect_search_candidates(tokens, brand=brand)
        matched = [
            product
            for product in candidates
            if product_matches_tokens(product, tokens)
        ]
        return paginate_products(matched, limit=limit, page=page)

    async def _collect_search_candidates(
        self,
        tokens: list[str],
        *,
        brand: str | None,
    ) -> list[dict[str, Any]]:
        seen: set[str] = set()
        candidates: list[dict[str, Any]] = []

        async def absorb(params: dict[str, Any]) -> list[dict[str, Any]]:
            result = await self.list(params)
            page_items = result.get("products") or []
            for product in page_items:
                if not isinstance(product, dict):
                    continue
                product_id = str(product.get("id") or "")
                if not product_id or product_id in seen:
                    continue
                seen.add(product_id)
                candidates.append(product)
            return page_items

        if brand:
            for tray_page in range(1, self._SEARCH_MAX_PAGES + 1):
                page_items = await absorb({
                    "brand": brand,
                    "limit": self._SEARCH_TRAY_LIMIT,
                    "page": tray_page,
                })
                if len(page_items) < self._SEARCH_TRAY_LIMIT:
                    break
            return candidates

        # Without brand, seed from name probes (Tray name filter is imperfect).
        probes: list[str] = []
        joined = " ".join(tokens)
        if joined:
            probes.append(joined)
        for token in tokens:
            if token not in probes:
                probes.append(token)
        for name in probes:
            for tray_page in range(1, min(3, self._SEARCH_MAX_PAGES) + 1):
                page_items = await absorb({
                    "name": name,
                    "limit": self._SEARCH_TRAY_LIMIT,
                    "page": tray_page,
                })
                if len(page_items) < self._SEARCH_TRAY_LIMIT:
                    break
        return candidates
