from __future__ import annotations

import asyncio
from typing import Any

from .common import Resource
from ..exceptions import TrayAPIError, TrayAuthenticationError, TrayConnectionError
from ..normalizers.common import normalized_list
from ..normalizers.product import normalize_product
from ..normalizers.property import normalize_property
from ..product_search import paginate_products, product_matches_tokens, product_token_score


class ProductResource(Resource):
    path, plural, singular, normalizer = "/products", "Products", "product", staticmethod(normalize_product)

    # Tray list pages used as candidate pool for local AND/ILIKE filtering.
    _SEARCH_TRAY_LIMIT = 50
    _SEARCH_MAX_PAGES = 40
    _SEARCH_NAME_PAGES = 2
    _SEARCH_BRAND_PAGES = 4
    _SEARCH_FETCH_CONCURRENCY = 2

    @staticmethod
    def _parse_current_price_range(value: Any) -> tuple[float | None, float | None] | None:
        if value in (None, ""):
            return None
        parts = [part.strip() for part in str(value).split(",", 1)]
        if len(parts) != 2:
            return None
        try:
            lower = float(parts[0]) if parts[0] else None
            upper = float(parts[1]) if parts[1] else None
        except ValueError:
            return None
        return lower, upper

    @staticmethod
    def _effective_price(product: dict[str, Any]) -> float | None:
        for key in ("current_price", "promotional_price", "price"):
            value = product.get(key)
            if value in (None, "", 0, 0.0, "0", "0.00"):
                continue
            try:
                return float(str(value).replace(",", "."))
            except (TypeError, ValueError):
                continue
        return None

    async def list(self, params: dict[str, Any] | None = None):
        """Use Tray's documented `price_range` and always enforce it locally.

        `current_price_range` appears in Tray response metadata but is rejected
        as a request parameter by some stores. It remains part of our internal
        API for compatibility and is translated before calling Tray.
        """
        original = dict(params or {})
        raw_range = original.pop("current_price_range", None)
        parsed_range = self._parse_current_price_range(raw_range)
        if raw_range not in (None, "") and parsed_range is None:
            from ..exceptions import TrayValidationError

            raise TrayValidationError("current_price_range must be min,max")
        translated = parsed_range is not None and "price_range" not in original
        if translated:
            original["price_range"] = raw_range
        try:
            result = await super().list(original)
        except TrayAPIError:
            if not translated:
                raise
            # Store/API versions vary in accepted price_range syntax. A local
            # filter is safer than surfacing 500 or silently dropping the cap.
            original.pop("price_range", None)
            result = await super().list(original)
            result["price_filter_source"] = "local_fallback"
        if parsed_range is None:
            return result
        lower, upper = parsed_range
        products = []
        for product in result.get("products") or []:
            price = self._effective_price(product)
            if price is None:
                continue
            if lower is not None and price < lower:
                continue
            if upper is not None and price > upper:
                continue
            products.append(product)
        result["products"] = products
        result.setdefault("price_filter_source", "tray_and_local")
        return result

    async def list_properties(self, params: dict[str, Any] | None = None):
        payload = await self.client.request(
            "GET", "/products/properties", params=params
        )
        return normalized_list(
            payload, "Properties", "property", normalize_property, "properties"
        )

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
        match_mode: str = "all",
        exclude_product_ids: set[str] | None = None,
    ) -> dict[str, Any]:
        candidates = await self._collect_search_candidates(
            tokens,
            brand=brand,
            force_brand_pool=match_mode == "any",
        )
        excluded = {str(item) for item in (exclude_product_ids or set())}
        if match_mode == "any":
            scored = [
                (product_token_score(product, tokens), product)
                for product in candidates
                if str(product.get("id") or "") not in excluded
            ]
            scored = [pair for pair in scored if pair[0] > 0]
            scored.sort(key=lambda pair: pair[0], reverse=True)
            matched = [product for _, product in scored]
        else:
            matched = [
                product
                for product in candidates
                if str(product.get("id") or "") not in excluded
                and product_matches_tokens(product, tokens)
            ]
        result = paginate_products(
            matched,
            limit=limit,
            page=page,
            preserve_order=match_mode == "any",
        )
        result["search"] = {
            "match_mode": match_mode,
            "candidate_count": len(candidates),
            "matched_count": len(matched),
            "excluded_count": len(excluded),
            "brand_scoped": bool(brand),
        }
        return result

    async def _collect_search_candidates(
        self,
        tokens: list[str],
        *,
        brand: str | None,
        force_brand_pool: bool = False,
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
            auth_failures = 0
            connection_failures = 0
            for row in rows:
                if isinstance(row, TrayAuthenticationError):
                    auth_failures += 1
                    out.append([])
                    continue
                if isinstance(row, TrayConnectionError):
                    connection_failures += 1
                    out.append([])
                    continue
                if isinstance(row, Exception):
                    out.append([])
                    continue
                out.append(row if isinstance(row, list) else [])
            if auth_failures and auth_failures == len(rows):
                raise TrayAuthenticationError("Tray product search auth failed")
            if connection_failures and connection_failures == len(rows):
                raise TrayConnectionError("Tray product search connection failed")
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
            if probes and not force_brand_pool:
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
        max_name_pages = min(self._SEARCH_NAME_PAGES, self._SEARCH_MAX_PAGES)
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
