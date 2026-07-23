from typing import Any

from .common import number
from .image import normalize_images, primary_image_url


def _unwrap_variant(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    for key in ("Variant", "ProductVariant", "variant"):
        if isinstance(raw.get(key), dict):
            return raw[key]
    return raw


def _normalize_sku(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        raw = [raw]
    result = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        value = item.get("Sku", item)
        if not isinstance(value, dict):
            continue
        sku = {key: value[key] for key in ("type", "value") if key in value}
        image_url = value.get("image_secure") or value.get("image")
        if image_url:
            sku["image_url"] = image_url
        if sku:
            result.append(sku)
    return result


def normalize_variant(raw: Any) -> dict[str, Any]:
    value = _unwrap_variant(raw)
    result: dict[str, Any] = {}
    for key in ("id", "product_id", "ean", "reference", "order", "availability", "availability_days"):
        if key in value:
            result[key] = value[key]
    for key in ("price", "promotional_price"):
        if key in value:
            result[key] = number(value[key])
    for key in ("stock", "minimum_stock", "quantity_sold"):
        if key in value:
            result[key] = number(value[key], integer=True)

    sku_key = next((key for key in ("Sku", "sku") if key in value), None)
    if sku_key is not None:
        result["sku"] = _normalize_sku(value.get(sku_key))

    settings = value.get("VariationSettings", value.get("variation_settings"))
    if isinstance(settings, dict):
        result["variation_settings"] = {
            key: settings[key]
            for key in ("when_stock_runs_out", "order_days_availability")
            if key in settings
        }
    images = normalize_images(value.get("VariantImage") or value.get("images"))
    result["images"] = images
    result["primary_image_url"] = primary_image_url(images)
    return result
