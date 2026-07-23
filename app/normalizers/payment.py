from typing import Any

from .common import number


def _normalize_plot(plot_id: Any, raw: Any) -> dict[str, Any]:
    value = raw if isinstance(raw, dict) else {}
    result: dict[str, Any] = {}
    installments = number(value.get("installments", plot_id), integer=True)
    if installments is not None:
        result["installments"] = installments
    for key in ("value", "interest_value", "discount_value", "base_value", "order_total"):
        if key in value:
            result[key] = number(value[key])
    if "interest" in value:
        result["interest"] = value["interest"]
    return result


def _normalize_plots(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        return [_normalize_plot(plot_id, value) for plot_id, value in raw.items()]
    if isinstance(raw, list):
        return [
            _normalize_plot(value.get("id", value.get("installments", index + 1)), value)
            for index, value in enumerate(raw) if isinstance(value, dict)
        ]
    return []


def normalize_payment_option(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    value = value.get("PaymentOption", value)
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("id", "name", "text"):
        if key in value:
            result[key] = value[key]
    if "card" in value:
        result["card"] = number(value["card"], integer=True)
    for key in ("discount_value", "increase_value", "total_base", "tax_value"):
        if key in value:
            result[key] = number(value[key])
    result["plots"] = _normalize_plots(value.get("plots"))
    return result


def normalize_payment_options(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    raw = payload.get("paymentoptions", payload.get("payment_options", payload.get("PaymentOptions", [])))
    if isinstance(raw, dict):
        raw = [raw]
    return [normalize_payment_option(value) for value in raw if isinstance(value, dict)] if isinstance(raw, list) else []
