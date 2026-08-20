import asyncio
from typing import Any

from .common import Resource
from ..normalizers.product import normalize_product
from ..product_search import paginate_products, product_matches_tokens


class ProductResource(Resource):
    path, plural, singular, normalizer = "/products", "Products", "product", staticmethod(normalize_product)

    # Tray list pages used as candidate pool for local AND/ILIKE filtering.
    _SEARCH_TRAY_LIMIT = 50
    _SEARCH_MAX_PAGES = 40
    _SEARCH_NAME_PAGES = 3
    _SEARCH_BRAND_PAGES = 12
    _SEARCH_FETCH_CONCURRENCY = 4

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
        lock = asyncio.Lock()
        sem = asyncio.Semaphore(self._SEARCH_FETCH_CONCURRENCY)

        async def absorb(params: dict[str, Any]) -> list[dict[str, Any]]:
            async with sem:
                result = await self.list(params)
            page_items = result.get("products") or []
            async with lock:
                for product in page_items:
                    if not isinstance(product, dict):
                        continue
                    product_id = str(product.get("id") or "")
                    if not product_id or product_id in seen:
                        continue
                    seen.add(product_id)
                    candidates.append(product)
            return page_items

        async def absorb_many(param_list: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
            if not param_list:
                return []
            rows = await asyncio.gather(
                *[absorb(params) for params in param_list],
                return_exceptions=True,
            )
            out: list[list[dict[str, Any]]] = []
            for row in rows:
                if isinstance(row, Exception):
                    out.append([])
                    continue
                out.append(row if isinstance(row, list) else [])
            return out

        if brand:
            probes: list[str] = []
            if tokens:
                joined = " ".join(tokens[:3]).strip()
                if joined:
                    probes.append(joined)
                for token in tokens:
                    if token and token not in probes:
                        probes.append(token)
            if probes:
                first_pages = await absorb_many(
                    [
                        {
                            "brand": brand,
                            "name": name,
                            "limit": self._SEARCH_TRAY_LIMIT,
                            "page": 1,
                        }
                        for name in probes
                    ]
                )
                extra_params: list[dict[str, Any]] = []
                for name, page_items in zip(probes, first_pages):
                    if len(page_items) >= self._SEARCH_TRAY_LIMIT:
                        extra_params.extend(
                            {
                                "brand": brand,
                                "name": name,
                                "limit": self._SEARCH_TRAY_LIMIT,
                                "page": tray_page,
                            }
                            for tray_page in range(2, self._SEARCH_NAME_PAGES + 1)
                        )
                if extra_params:
                    await absorb_many(extra_params)
                if any(product_matches_tokens(product, tokens) for product in candidates):
                    return candidates
                seen.clear()
                candidates.clear()
            await absorb_many(
                [
                    {
                        "brand": brand,
                        "limit": self._SEARCH_TRAY_LIMIT,
                        "page": tray_page,
                    }
                    for tray_page in range(1, self._SEARCH_BRAND_PAGES + 1)
                ]
            )
            return candidates

        probes: list[str] = []
        joined = " ".join(tokens)
        if joined:
            probes.append(joined)
        for token in tokens:
            if token not in probes:
                probes.append(token)
        first_pages = await absorb_many(
            [
                {
                    "name": name,
                    "limit": self._SEARCH_TRAY_LIMIT,
                    "page": 1,
                }
                for name in probes
            ]
        )
        extra_params = []
        max_name_pages = min(3, self._SEARCH_MAX_PAGES)
        for name, page_items in zip(probes, first_pages):
            if len(page_items) >= self._SEARCH_TRAY_LIMIT:
                extra_params.extend(
                    {
                        "name": name,
                        "limit": self._SEARCH_TRAY_LIMIT,
                        "page": tray_page,
                    }
                    for tray_page in range(2, max_name_pages + 1)
                )
        if extra_params:
            await absorb_many(extra_params)
        return candidates
