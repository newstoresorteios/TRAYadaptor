from .common import first, number


def normalize_inventory(value):
    return {"id": value.get("id"), "product_id": value.get("product_id"), "variation_id": value.get("variation_id"), "reference": value.get("reference"), "stock": number(value.get("stock"), True), "distribution_center_id": first(value, "distribution_center_id", "id_cd"), "name": value.get("name"), "active": value.get("active")}
