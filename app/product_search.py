"""Token AND search over Tray product candidates (accent/case insensitive)."""

from __future__ import annotations

import unicodedata
from typing import Any


def fold_text(value: Any) -> str:
    text = str(value or "")
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", text).lower()
        if not unicodedata.combining(char)
    )


def parse_tokens(raw: str | None) -> list[str]:
    if raw is None:
        return []
    tokens: list[str] = []
    for part in str(raw).split(","):
        token = fold_text(part).strip()
        if token:
            tokens.append(token)
    return tokens


def product_search_blob(product: dict[str, Any]) -> str:
    return fold_text(
        " ".join(
            str(product.get(field) or "")
            for field in ("name", "brand", "model", "reference", "description")
        )
    )


# Catalog typos / marketing aliases that should still AND-match Story OCR.
_TOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    "sealander": ("sealander", "seander"),
    "seander": ("sealander", "seander"),
    "aquascaphe": ("aquascaphe", "aquascape"),
}


def _token_present(blob: str, token: str) -> bool:
    key = fold_text(token)
    if not key:
        return False
    if key in blob:
        return True
    for alias in _TOKEN_ALIASES.get(key, ()):
        if alias in blob:
            return True
    return False


def product_matches_tokens(product: dict[str, Any], tokens: list[str]) -> bool:
    if not tokens:
        return False
    blob = product_search_blob(product)
    return all(_token_present(blob, token) for token in tokens)


def _product_id_sort_key(product: dict[str, Any]) -> tuple[int, int | str]:
    product_id = product.get("id")
    try:
        return (0, int(product_id))
    except (TypeError, ValueError):
        return (1, str(product_id or ""))


def paginate_products(
    products: list[dict[str, Any]],
    *,
    limit: int,
    page: int,
) -> dict[str, Any]:
    ordered = sorted(products, key=_product_id_sort_key)
    offset = (page - 1) * limit
    return {
        "success": True,
        "paging": {
            "total": len(ordered),
            "page": page,
            "limit": limit,
            "offset": offset,
            "maxLimit": 50,
        },
        "products": ordered[offset : offset + limit],
    }
