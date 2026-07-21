from .common import first, number


def normalize_kit(value):
    variants = value.get("ProductVariantKit", value.get("variants", []))
    if isinstance(variants, dict):
        variants = [variants]
    return {"id": value.get("id"), "product_parent_id": value.get("product_parent_id"), "product_id": value.get("product_id"), "quantity": number(value.get("quantity"), True), "price": number(value.get("price")), "price_rule": value.get("price_rule"), "discount_type": value.get("discount_type"), "discount_value": number(value.get("discount_value")), "brand": value.get("brand"), "warranty": value.get("warranty"), "availability_days": value.get("availability_days"), "variants": [{"variant_id": first(v, "variant_id", "id"), "product_kit_id": v.get("product_kit_id"), "price": number(v.get("price"))} for v in variants if isinstance(v, dict)]}
