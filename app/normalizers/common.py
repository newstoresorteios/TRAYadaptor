from typing import Any


def items(payload: Any, plural: str, singular: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(payload, dict):
        return [], {}
    raw = payload.get(plural, payload.get(singular, []))
    if isinstance(raw, dict):
        raw = [raw]
    result = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict):
            camel = "".join(part.capitalize() for part in singular.split("_"))
            wrapper_names = (singular, singular.capitalize(), camel, "DiscountCoupon" if singular == "coupon" else camel)
            value = next((item[name] for name in wrapper_names if isinstance(item.get(name), dict)), item)
            result.append(value if isinstance(value, dict) else item)
    paging = payload.get("paging", payload.get("Paging", {}))
    return result, paging if isinstance(paging, dict) else {}


def first(value: dict[str, Any], *keys: str) -> Any:
    return next((value[key] for key in keys if value.get(key) is not None), None)


def number(value: Any, integer: bool = False) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        result = float(str(value).replace(",", "."))
        return int(result) if integer else result
    except (TypeError, ValueError):
        return None


def normalized_list(payload: Any, plural: str, singular: str, normalizer, output_key: str | None = None) -> dict[str, Any]:
    values, paging = items(payload, plural, singular)
    return {"success": True, "paging": paging, output_key or singular: [normalizer(value) for value in values]}
