from typing import Any

from .common import first


def normalize_property(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": first(value, "id", "property_id"),
        "name": first(value, "name", "property"),
        "position": first(value, "position"),
        "display": first(value, "display"),
        "active_display": first(value, "active_display"),
    }
