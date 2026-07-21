from .common import first


def normalize_brand(value):
    return {"id": first(value, "id", "brand_id"), "slug": value.get("slug"), "name": first(value, "name", "brand"), "raw_brand": value.get("brand")}
