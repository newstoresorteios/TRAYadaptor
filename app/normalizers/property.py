from typing import Any

from .common import first


def _normalize_property_value(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    value = raw.get("PropertyValue", raw)
    if not isinstance(value, dict):
        return None
    result = {
        key: value[key]
        for key in ("id", "name", "property_id", "image")
        if key in value
    }
    return result or None


def normalize_property(value: dict[str, Any]) -> dict[str, Any]:
    raw_values = first(value, "PropertyValues", "property_values", "values")
    if isinstance(raw_values, dict):
        raw_values = [raw_values]
    values = [
        normalized
        for item in (raw_values if isinstance(raw_values, list) else [])
        if (normalized := _normalize_property_value(item)) is not None
    ]
    return {
        "id": first(value, "id", "property_id"),
        "name": first(value, "name", "property"),
        "position": first(value, "position"),
        "display": first(value, "display"),
        "active_display": first(value, "active_display"),
        "has_product": first(value, "has_product"),
        "values": values,
    }
