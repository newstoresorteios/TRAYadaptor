from typing import Any


def _unwrap_category(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    for key in ("Category", "category", "CategoryTree"):
        if isinstance(raw.get(key), dict):
            return _unwrap_category(raw[key])
    return raw


def normalize_category(raw: Any) -> dict[str, Any]:
    value = _unwrap_category(raw)
    result: dict[str, Any] = {}
    for key in (
        "id", "name", "slug", "parent_id", "title", "small_description",
        "has_product", "link",
    ):
        if key in value:
            result[key] = value[key]

    children_key = next((key for key in ("children", "Children") if key in value), None)
    if children_key is not None:
        children = value.get(children_key)
        if isinstance(children, dict):
            children = [children]
        result["children"] = [
            normalize_category(child)
            for child in children or []
            if isinstance(child, dict)
        ]
    return result
