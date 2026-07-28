from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from ..identifiers import normalize_optional_variant_id
from .common import items


STATUS_GROUPS = {
    "AGUARDANDO PAGAMENTO": "awaiting_payment",
    "AGUARDANDO VINDI": "awaiting_payment",
    "A ENVIAR": "awaiting_shipment",
    "A ENVIAR VINDI": "awaiting_shipment",
    "ENVIADO": "shipped",
    "FINALIZADO": "completed",
    "CANCELADO": "cancelled",
}


def _unwrap(value: Any, *names: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    current = value
    for _ in range(3):
        nested = next(
            (
                current[name]
                for name in names
                if isinstance(current.get(name), dict)
            ),
            None,
        )
        if nested is None:
            break
        current = nested
    return current


def _identifier(value: Any) -> Any:
    if value is None or value == "":
        return None
    text = str(value).strip()
    return int(text) if text.isascii() and text.isdecimal() else value


def _first_present(*values: Any) -> Any:
    return next(
        (
            value
            for value in values
            if value is not None and str(value).strip() != ""
        ),
        None,
    )


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


def _optional_date(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.startswith("0000-00-00"):
        return None
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value


def _boolean(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None or value == "":
        return None
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes"}:
        return True
    if lowered in {"0", "false", "no"}:
        return False
    return None


def _copy_present(
    result: dict[str, Any],
    source: dict[str, Any],
    keys: tuple[str, ...],
) -> None:
    for key in keys:
        if source.get(key) is not None:
            result[key] = source[key]


def status_group(status: Any) -> str | None:
    if status is None:
        return None
    return STATUS_GROUPS.get(" ".join(str(status).upper().split()))


def normalize_order(payload: Any) -> dict[str, Any]:
    order = _unwrap(payload, "Order", "order")
    result: dict[str, Any] = {}
    for key in ("id", "customer_id"):
        if order.get(key) is not None:
            result[key] = _identifier(order[key])
    _copy_present(
        result,
        order,
        (
            "status",
            "shipment",
            "payment_method",
            "payment_method_id",
            "session_id",
            "estimated_delivery_date",
            "sending_code",
            "sending_date",
            "tracking_url",
        ),
    )
    if "payment_method" not in result and order.get("payment_form") is not None:
        result["payment_method"] = order["payment_form"]
    for key in ("shipment_value", "total"):
        if order.get(key) is not None:
            result[key] = _money(order[key])
    for key in ("has_payment", "has_shipment", "has_invoice"):
        if order.get(key) is not None:
            result[key] = _boolean(order[key])
    if "status" in result:
        group = status_group(result["status"])
        if group is not None:
            result["status_group"] = group
    return result


def normalize_order_list(
    payload: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if isinstance(payload, list):
        values = [value for value in payload if isinstance(value, dict)]
        paging: dict[str, Any] = {}
    else:
        values, paging = items(payload, "Orders", "order")
        if (
            not values
            and isinstance(payload, dict)
            and isinstance(payload.get("Order"), dict)
        ):
            values = [payload["Order"]]
    return [normalize_order(value) for value in values], paging


def extract_order_id(payload: Any) -> Any:
    order = _unwrap(payload, "Order", "order")
    root = payload if isinstance(payload, dict) else {}
    return _identifier(
        _first_present(
            root.get("order_id"),
            root.get("id"),
            order.get("order_id"),
            order.get("id"),
        )
    )


def normalize_order_create(payload: Any) -> dict[str, Any]:
    order = _unwrap(payload, "Order", "order")
    root = payload if isinstance(payload, dict) else {}
    code = root.get("code", order.get("code"))
    message = root.get("message", order.get("message"))
    return {
        "success": True,
        "order_id": extract_order_id(payload),
        "code": _integer(code),
        "message": message,
    }


def _nested_dict(source: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = source.get(key)
        if isinstance(value, list):
            value = value[0] if value else {}
        if isinstance(value, dict):
            return _unwrap(value, key, key.removesuffix("s"))
    return {}


def _valid_payment_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url or any(character.isspace() for character in url):
        return None
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    if port is not None and not 1 <= port <= 65535:
        return None
    return url


def _equivalent_url_key(url: str) -> tuple[Any, ...]:
    parsed = urlsplit(url)
    port = parsed.port
    if (parsed.scheme.lower(), port) in {("http", 80), ("https", 443)}:
        port = None
    return (
        parsed.hostname.lower() if parsed.hostname else "",
        port,
        parsed.path or "/",
        parsed.query,
        parsed.fragment,
    )


def _transaction_urls(order: dict[str, Any]) -> list[str]:
    raw = order.get("OrderTransactions", [])
    if isinstance(raw, dict):
        nested = raw.get("OrderTransaction", raw.get("OrderTransactions"))
        raw = nested if isinstance(nested, (dict, list)) else raw
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    result: list[str] = []
    positions: dict[tuple[Any, ...], int] = {}
    for value in raw:
        transaction = _unwrap(
            value,
            "OrderTransaction",
            "OrderTransactions",
            "transaction",
        )
        url = _valid_payment_url(transaction.get("url_payment"))
        if url is None:
            continue
        key = _equivalent_url_key(url)
        if key not in positions:
            positions[key] = len(result)
            result.append(url)
            continue
        index = positions[key]
        if result[index].lower().startswith("http://") and url.lower().startswith(
            "https://"
        ):
            result[index] = url
    return result


def _official_payment_url(order: dict[str, Any]) -> str | None:
    urls = order.get("urls")
    if not isinstance(urls, dict):
        return None
    payment = urls.get("payment")
    if isinstance(payment, dict):
        for key in ("https", "http"):
            url = _valid_payment_url(payment.get(key))
            if url is not None:
                return url
        return None
    return _valid_payment_url(payment)


def _payment_records(order: dict[str, Any]) -> list[dict[str, Any]]:
    raw = order.get("Payment", order.get("payment", []))
    if isinstance(raw, dict):
        nested = raw.get("Payment", raw.get("payments"))
        raw = nested if isinstance(nested, (dict, list)) else raw
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        return []

    records: list[dict[str, Any]] = []
    for value in raw:
        record = _unwrap(value, "Payment", "payment")
        if not record:
            continue
        records.append(
            {
                "id": record.get("id"),
                "payment_method_id": record.get("payment_method_id"),
                "method": record.get("method"),
                "value": _money(record.get("value")),
                "date": _optional_date(record.get("date")),
                "created": _optional_date(record.get("created")),
                "modified": _optional_date(record.get("modified")),
            }
        )
    return records


def normalize_order_payment(payload: Any) -> dict[str, Any]:
    order = _unwrap(payload, "Order", "order")
    transaction_urls = _transaction_urls(order)
    payment_url = _official_payment_url(order)
    if payment_url is None and transaction_urls:
        payment_url = transaction_urls[0]
    method = order.get("payment_method")
    if method is None:
        method = order.get("payment_form")
    return {
        "method_id": order.get("payment_method_id"),
        "method": method,
        "type": order.get("payment_method_type"),
        "has_payment": _boolean(order.get("has_payment")),
        "payment_date": _optional_date(order.get("payment_date")),
        "installment": (
            order.get("installment")
            if order.get("installment") not in (None, "")
            else None
        ),
        "payment_url": payment_url,
        "transaction_urls": transaction_urls,
        "records": _payment_records(order),
    }


def normalize_payment_capability(payment: dict[str, Any]) -> dict[str, bool]:
    return {
        "method_selected": payment.get("method_id") not in (None, "")
        or payment.get("method") not in (None, ""),
        "payment_url_available": payment.get("payment_url") is not None,
        "native_pix_available": False,
        "native_boleto_available": False,
        "native_card_available": False,
    }


def _normalize_customer(value: Any) -> dict[str, Any]:
    customer = _unwrap(value, "Customer", "customer")
    result: dict[str, Any] = {}
    if customer.get("id") is not None:
        result["id"] = _identifier(customer["id"])
    _copy_present(
        result,
        customer,
        ("name", "email", "phone", "cellphone"),
    )
    return result


def _normalize_address(value: Any) -> dict[str, Any]:
    address = _unwrap(
        value,
        "CustomerAddress",
        "customer_address",
        "Address",
        "address",
    )
    allowed = (
        "id",
        "customer_id",
        "address",
        "zip_code",
        "number",
        "complement",
        "neighborhood",
        "city",
        "state",
        "country",
        "type",
    )
    result = {key: address[key] for key in allowed if address.get(key) is not None}
    for key in ("id", "customer_id"):
        if key in result:
            result[key] = _identifier(result[key])
    return result


def _normalize_product(value: Any) -> dict[str, Any]:
    product = _unwrap(value, "ProductsSold", "ProductSold", "product")
    result: dict[str, Any] = {}
    if product.get("product_id") is not None:
        result["product_id"] = _identifier(product["product_id"])
    try:
        variant_id = normalize_optional_variant_id(product.get("variant_id"))
    except ValueError:
        variant_id = None
    if variant_id is not None:
        result["variant_id"] = variant_id
    _copy_present(result, product, ("name",))
    if product.get("quantity") is not None:
        result["quantity"] = _integer(product["quantity"])
    for key in ("price", "original_price"):
        if product.get(key) is not None:
            result[key] = _money(product[key])
    return result


def normalize_order_complete(payload: Any) -> dict[str, Any]:
    order = _unwrap(payload, "Order", "order")
    basic = normalize_order(order)
    order_result = {
        key: basic[key]
        for key in ("id", "status", "status_group", "total")
        if key in basic
    }
    for key in ("partial_total", "discount", "taxes"):
        if order.get(key) is not None:
            order_result[key] = _money(order[key])

    payment = normalize_order_payment(order)
    payment_capability = normalize_payment_capability(payment)

    shipping_source = {
        **order,
        **_nested_dict(order, "Shipping", "shipping"),
    }
    shipping: dict[str, Any] = {}
    _copy_present(
        shipping,
        shipping_source,
        (
            "shipment",
            "shipment_integrator",
            "id_quotation",
            "estimated_delivery_date",
            "sending_code",
            "sending_date",
            "tracking_url",
        ),
    )
    if shipping_source.get("shipment_value") is not None:
        shipping["shipment_value"] = _money(shipping_source["shipment_value"])
    if shipping_source.get("has_shipment") is not None:
        shipping["has_shipment"] = _boolean(shipping_source["has_shipment"])

    customer_source = _nested_dict(order, "Customer", "customer")
    address_source = (
        _nested_dict(customer_source, "CustomerAddress", "customer_address")
        or _nested_dict(
            order,
            "CustomerAddress",
            "customer_address",
            "DeliveryAddress",
            "address",
        )
    )
    raw_products = order.get("ProductsSold", order.get("products", []))
    if isinstance(raw_products, dict):
        raw_products = [raw_products]
    products = [
        _normalize_product(value)
        for value in raw_products
        if isinstance(value, dict)
    ]
    return {
        "order": order_result,
        "payment": payment,
        "payment_capability": payment_capability,
        "shipping": shipping,
        "customer": _normalize_customer(customer_source),
        "address": _normalize_address(address_source),
        "products": products,
    }
