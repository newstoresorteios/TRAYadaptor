from typing import Any


def normalize_sold_product(value: dict[str, Any]) -> dict[str, Any]:
    """Preserve the identifiers and commercial fields exposed by Tray."""
    return {
        key: value.get(key)
        for key in (
            "id",
            "product_id",
            "order_id",
            "name",
            "price",
            "original_price",
            "quantity",
            "model",
            "reference",
            "variant_id",
            "additional_information",
        )
        if value.get(key) is not None
    }
