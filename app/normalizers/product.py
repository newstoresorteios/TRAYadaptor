from typing import Any
from .common import first, number


def normalize_variant(value: dict[str, Any]) -> dict[str, Any]:
    return {key: value[key] for key in ("id", "reference", "ean", "price", "promotional_price", "stock", "available", "properties", "settings") if key in value}


def normalize_product(value: dict[str, Any]) -> dict[str, Any]:
    settings = value.get("ProductSettings", value.get("product_settings"))
    settings = settings if isinstance(settings, dict) else None
    promotional = first(value, "promotional_price", "promotionalPrice")
    if promotional in ("0", "0.0", "0.00", 0, 0.0):
        promotional = None
    variants = value.get("Variant", value.get("variants", []))
    if isinstance(variants, dict):
        variants = [variants]
    return {
        "id": first(value, "id", "product_id"), "name": value.get("name"), "title": value.get("title"),
        "description": value.get("description"), "description_small": value.get("description_small"),
        "ean": value.get("ean"), "reference": first(value, "reference", "sku"), "brand": value.get("brand"),
        "brand_id": value.get("brand_id"), "model": value.get("model"), "category_id": value.get("category_id"),
        "category_name": value.get("category_name"), "price": number(value.get("price")),
        "promotional_price": number(promotional), "current_price": number(first(value, "current_price", "price")),
        "stock": number(first(value, "stock", "quantity"), True),
        "available": first(value, "available", "availability"), "available_in_store": value.get("available_in_store"),
        "available_in_store_raw": value.get("available_in_store"), "available_for_purchase": value.get("available_for_purchase"),
        "availability": value.get("availability"), "availability_days": value.get("availability_days"),
        "upon_request": value.get("upon_request"), "is_kit": value.get("is_kit"), "has_variation": value.get("has_variation"),
        "quantity_sold": number(value.get("quantity_sold"), True), "free_shipping": value.get("free_shipping"),
        "url": first(value, "url", "product_url"), "images": value.get("images"), "properties": value.get("properties"),
        "variants": [normalize_variant(v) for v in variants if isinstance(v, dict)],
        "payment_option": value.get("payment_option"), "payment_option_details": value.get("payment_option_details"),
        "product_settings": settings or value.get("product_settings"),
        "when_stock_runs_out": value.get("when_stock_runs_out") or (settings or {}).get("when_stock_runs_out"),
        "order_days_availability": value.get("order_days_availability") or (settings or {}).get("order_days_availability"),
        "created": value.get("created"), "modified": value.get("modified"),
    }
