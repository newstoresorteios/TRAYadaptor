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
    value = value.get("PaymentOption", value.get("PaymentMethod", value))
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in (
        "id",
        "integrator_id",
        "facilitator_id",
        "name",
        "image",
        "thumbnail",
        "additional",
        "integration_code",
        "text",
        "text_pag",
        "finalize_action",
        "interest_formula",
    ):
        if key in value:
            result[key] = value[key]
    for key in (
        "card",
        "min_splot",
        "max_splot",
        "facilitator",
        "increase",
        "display_increase",
        "deactivate",
        "is_intermediator",
    ):
        if key in value:
            result[key] = number(value[key], integer=True)
    for key in (
        "application_value",
        "discount_value",
        "increase_value",
        "total_base",
        "tax_value",
    ):
        if key in value:
            result[key] = number(value[key])
    if "equivalent" in value:
        result["equivalent"] = value["equivalent"]
    result["plots"] = _normalize_plots(value.get("plots"))
    return result


def normalize_payment_options(payload: Any) -> list[dict[str, Any]]:
    raw = _payment_collection(
        payload, ("paymentoptions", "payment_options", "PaymentOptions")
    )
    return [
        normalize_payment_option(value)
        for value in raw
        if isinstance(value, dict)
    ]


def normalize_payment_methods(payload: Any) -> list[dict[str, Any]]:
    raw = _payment_collection(
        payload,
        (
            "paymentmethods",
            "payment_methods",
            "PaymentMethods",
            "methods",
            "Methods",
            "paymentoptions",
        ),
    )
    return [
        normalize_payment_option(value)
        for value in raw
        if isinstance(value, dict)
    ]


def _payment_collection(payload: Any, keys: tuple[str, ...]) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    raw: Any = []
    for key in keys:
        if key in payload:
            raw = payload[key]
            break
    if raw == [] and ("id" in payload or "name" in payload):
        raw = payload
    if isinstance(raw, dict):
        raw = [raw]
    return raw if isinstance(raw, list) else []
