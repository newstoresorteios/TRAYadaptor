from typing import Any
import unicodedata
from .common import first, number
from .image import normalize_images, primary_image_url


def normalize_variant(value: dict[str, Any]) -> dict[str, Any]:
    result = {key: value[key] for key in ("id", "reference", "ean", "price", "promotional_price", "stock", "available", "properties", "settings") if key in value}
    images = normalize_images(value.get("VariantImage") or value.get("images"))
    result["images"] = images
    result["primary_image_url"] = primary_image_url(images)
    return result


def _product_url(value: dict[str, Any]) -> str | None:
    raw = first(value, "url", "product_url")
    if isinstance(raw, str):
        return raw
    if isinstance(raw, dict):
        for key in ("https", "http"):
            candidate = raw.get(key)
            if isinstance(candidate, str):
                return candidate
    return None


def _explicit_specs(value: dict[str, Any], properties: Any) -> dict[str, Any]:
    """Preserve explicitly supplied specs; never infer facts from a model name."""
    aliases = {
        "mechanism": ("mechanism", "movement", "mecanismo", "movimento"),
        "case_size": ("case_size", "case_size_mm", "diametro da caixa", "tamanho da caixa"),
        "water_resistance_m": ("water_resistance_m",),
        "water_resistance": ("water_resistance", "resistencia a agua"),
        "gender": ("gender", "genero"),
    }
    def folded(text):
        return "".join(c for c in unicodedata.normalize("NFKD", str(text).casefold()) if not unicodedata.combining(c)).strip()
    supplied = {folded(k): (v, "field:" + k) for k, v in value.items() if isinstance(v, (str, int, float)) and v != ""}
    if isinstance(properties, dict):
        for key, item in properties.items():
            if isinstance(item, (str, int, float)):
                supplied.setdefault(folded(key), (item, "property:" + key))
        entries = list(properties.values())
    else:
        entries = properties if isinstance(properties, list) else []
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        item = raw.get("Property", raw)
        if not isinstance(item, dict):
            continue
        name, content = first(item, "name", "property"), first(item, "value", "content")
        if name and isinstance(content, (str, int, float)) and content != "":
            supplied.setdefault(folded(name), (content, "property:" + str(name)))
    result, sources = {}, {}
    for key, names in aliases.items():
        for name in names:
            if name in supplied:
                result[key], sources[key] = supplied[name]
                break
    return {**result, "attribute_sources": sources}


def normalize_product(value: dict[str, Any]) -> dict[str, Any]:
    settings = first(value, "ProductSettings", "product_settings", "settings")
    settings = settings if isinstance(settings, dict) else None
    properties = first(value, "properties", "Properties")
    promotional = first(value, "promotional_price", "promotionalPrice")
    if promotional in ("0", "0.0", "0.00", 0, 0.0):
        promotional = None
    variants = value.get("Variant", value.get("variants", []))
    if isinstance(variants, dict):
        variants = [variants]
    images = normalize_images(value.get("ProductImage") or value.get("images"))
    return {
        **_explicit_specs(value, properties),
        "id": first(value, "id", "product_id"), "name": value.get("name"), "title": value.get("title"),
        "description": value.get("description"), "description_small": value.get("description_small"),
        "ean": value.get("ean"), "reference": first(value, "reference", "sku"), "brand": value.get("brand"),
        "brand_id": value.get("brand_id"), "model": value.get("model"), "category_id": value.get("category_id"),
        "related_categories": first(value, "related_categories", "RelatedCategories"),
        "category_name": value.get("category_name"), "price": number(value.get("price")),
        "promotional_price": number(promotional), "current_price": number(value.get("current_price")),
        "start_promotion": value.get("start_promotion"), "end_promotion": value.get("end_promotion"),
        "stock": number(first(value, "stock", "quantity"), True),
        "available": value.get("available"), "available_in_store": value.get("available_in_store"),
        "available_in_store_raw": value.get("available_in_store"), "available_for_purchase": value.get("available_for_purchase"),
        "availability": value.get("availability"), "availability_days": value.get("availability_days"),
        "upon_request": value.get("upon_request"), "is_kit": value.get("is_kit"), "has_variation": value.get("has_variation"),
        "quantity_sold": number(value.get("quantity_sold"), True), "hot": value.get("hot"),
        "release": value.get("release"), "promotion": value.get("promotion"),
        "free_shipping": value.get("free_shipping"),
        "url": _product_url(value), "images": images,
        "primary_image_url": primary_image_url(images),
        "properties": properties if properties is not None else [],
        "variants": [normalize_variant(v) for v in variants if isinstance(v, dict)],
        "payment_option": value.get("payment_option"), "payment_option_details": value.get("payment_option_details"),
        "product_settings": settings or value.get("product_settings"),
        "when_stock_runs_out": value.get("when_stock_runs_out") or (settings or {}).get("when_stock_runs_out"),
        "order_days_availability": value.get("order_days_availability") or (settings or {}).get("order_days_availability"),
        "created": value.get("created"), "modified": value.get("modified"),
    }
