from typing import Any

from .common import items


def _integer(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _money(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def normalize_shipping_option(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    option = value.get("Shipping", value.get("Cotation", value))
    if not isinstance(option, dict):
        return {}
    tax = option.get("taxe", option.get("tax"))
    if not isinstance(tax, dict):
        tax = {}
    return {
        "shipping_id": _integer(option.get("id")),
        "quotation_id": (
            str(option["id_quotation"])
            if option.get("id_quotation") is not None
            else None
        ),
        "name": option.get("name"),
        "identifier": option.get("identifier"),
        "price": _money(option.get("value")),
        "min_period": _integer(option.get("min_period")),
        "max_period": _integer(option.get("max_period")),
        "estimated_delivery_date": option.get("estimated_delivery_date"),
        "information": option.get("information"),
        "tax_name": tax.get("name"),
        "tax_value": _money(tax.get("value")),
    }


def normalize_shipping_quote(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    shipping = payload.get("Shipping", payload.get("shipping", payload))
    raw = (
        shipping.get("cotation", shipping.get("Cotation", []))
        if isinstance(shipping, dict)
        else []
    )
    if isinstance(raw, dict):
        nested = raw.get("Cotation", raw.get("cotation"))
        if isinstance(nested, (dict, list)):
            raw = nested
    if isinstance(raw, dict):
        raw = [raw]
    return [
        normalize_shipping_option(option)
        for option in raw
        if isinstance(option, dict)
    ]


def normalize_shipping_method(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    method = value.get("Shipping", value.get("shipping", value))
    if not isinstance(method, dict):
        return {}
    return {
        key: method[key]
        for key in (
            "id",
            "cod",
            "name",
            "identifier",
            "display_name",
            "status",
            "gateway",
        )
        if key in method
    }


def normalize_shipping_methods(payload: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    values, paging = items(payload, "Shippings", "shipping")
    if not values and isinstance(payload, dict):
        raw = payload.get("Shipping", payload.get("shippings", []))
        if isinstance(raw, dict):
            raw = [raw]
        if isinstance(raw, list):
            values = [value for value in raw if isinstance(value, dict)]
    if not values and isinstance(payload, list):
        values = [value for value in payload if isinstance(value, dict)]
    return [normalize_shipping_method(value) for value in values], paging
