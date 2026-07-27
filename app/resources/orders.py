import hashlib
import logging
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from ..exceptions import (
    TrayAPIError,
    TrayConnectionError,
    TrayError,
    TrayValidationError,
)
from ..identifiers import normalize_optional_variant_id
from ..normalizers.order import (
    normalize_order,
    normalize_order_complete,
    normalize_order_create,
    normalize_order_list,
)

DEFAULT_ORDER_POINT_SALE = "PARTICULAR"

logger = logging.getLogger("uvicorn.error.tray.order")
logger.setLevel(logging.INFO)


class OrderResource:
    def __init__(self, client):
        self.client = client

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            tray_payload = _tray_order_payload(payload)
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise TrayValidationError("order_payload_invalid") from exc
        _log_create_request(payload)
        try:
            response = await self._post_order(tray_payload, attempt="initial")
        except TrayAPIError as exc:
            if _is_auth_failure(exc):
                logger.info("[tray.order.reconcile] reason=auth_401 action=refresh")
                await self.client.auth.refresh()
                return await self._reconcile_then_retry(
                    payload,
                    tray_payload,
                    reason="auth_401",
                )
            if _is_ambiguous_api_failure(exc):
                return await self._reconcile_then_retry(
                    payload,
                    tray_payload,
                    reason="ambiguous_response",
                )
            raise
        except TrayConnectionError:
            return await self._reconcile_then_retry(
                payload,
                tray_payload,
                reason="ambiguous_transport",
            )
        return _normalize_created(response, reconciled=False)

    async def _post_order(
        self,
        tray_payload: dict[str, Any],
        *,
        attempt: str,
    ) -> Any:
        return await self.client.request(
            "POST",
            "/orders",
            json=tray_payload,
            retry_on_auth_failure=False,
            follow_redirects=False,
            reject_redirects=True,
            request_observer=lambda: logger.info(
                "[tray.order.create.request] attempt=%s request_sent=true",
                attempt,
            ),
            response_observer=lambda diagnostics: logger.info(
                "[tray.order.create.response] attempt=%s status_code=%s "
                "response_received=%s response_is_json=%s",
                attempt,
                diagnostics.get("status_code", "none"),
                str(bool(diagnostics.get("response_received"))).lower(),
                str(bool(diagnostics.get("response_is_json"))).lower(),
            ),
        )

    async def _reconcile_then_retry(
        self,
        payload: dict[str, Any],
        tray_payload: dict[str, Any],
        *,
        reason: str,
    ) -> dict[str, Any]:
        session_id = payload["session_id"]
        logger.info(
            "[tray.order.reconcile] status=started reason=%s "
            "session_length=%s session_hash=%s",
            reason,
            len(session_id),
            _session_hash(session_id),
        )
        existing = await self._find_by_session(session_id)
        if existing is not None:
            logger.info(
                "[tray.order.reconcile] status=order_found action=completed_without_retry"
            )
            return _normalize_reconciled(existing)

        logger.info(
            "[tray.order.reconcile] status=order_not_found action=retry_once"
        )
        try:
            response = await self._post_order(tray_payload, attempt="retry")
        except TrayConnectionError:
            return await self._final_reconciliation(session_id)
        except TrayAPIError as exc:
            if _is_ambiguous_api_failure(exc):
                return await self._final_reconciliation(session_id)
            raise
        return _normalize_created(response, reconciled=True)

    async def _final_reconciliation(self, session_id: str) -> dict[str, Any]:
        logger.info(
            "[tray.order.reconcile] status=started reason=retry_ambiguous "
            "session_length=%s session_hash=%s",
            len(session_id),
            _session_hash(session_id),
        )
        existing = await self._find_by_session(session_id)
        if existing is not None:
            logger.info(
                "[tray.order.reconcile] status=order_found "
                "action=completed_after_retry"
            )
            return _normalize_reconciled(existing)
        logger.info(
            "[tray.order.reconcile] status=order_not_found "
            "action=stop_without_additional_post"
        )
        raise TrayConnectionError("Order creation outcome is ambiguous")

    async def _find_by_session(self, session_id: str) -> dict[str, Any] | None:
        payload = await self.client.request(
            "GET",
            "/orders",
            params={"session_id": session_id},
        )
        orders, _ = normalize_order_list(payload)
        for order in orders:
            if str(order.get("session_id", "")).strip() == session_id:
                return order
        for order in orders:
            if order.get("session_id") in (None, ""):
                return order
        return None

    async def list(self, params: dict[str, Any]) -> dict[str, Any]:
        payload = await self.client.request("GET", "/orders", params=params)
        orders, paging = normalize_order_list(payload)
        logger.info(
            "[tray.order.get] operation=list success=true count=%s "
            "session_filter_present=%s",
            len(orders),
            str(bool(params.get("session_id"))).lower(),
        )
        return {"success": True, "paging": paging, "orders": orders}

    async def get(self, order_id: int) -> dict[str, Any]:
        payload = await self.client.request("GET", f"/orders/{order_id}")
        order = normalize_order(payload)
        logger.info(
            "[tray.order.get] operation=detail success=true order_id=%s",
            order_id,
        )
        return {"success": True, "order": order}

    async def complete(self, order_id: int) -> dict[str, Any]:
        try:
            payload = await self.client.request("GET", f"/orders/{order_id}/full")
            variant = "full"
        except TrayAPIError as exc:
            if exc.status_code not in {404, 405}:
                logger.info(
                    "[tray.order.full] variant=full accepted=false "
                    "fallback=false status_code=%s",
                    exc.status_code or "none",
                )
                raise
            logger.info(
                "[tray.order.full] variant=full accepted=false fallback=true "
                "status_code=%s",
                exc.status_code,
            )
            payload = await self.client.request(
                "GET",
                f"/orders/{order_id}/complete",
            )
            variant = "complete"
        normalized = normalize_order_complete(payload)
        logger.info(
            "[tray.order.full] variant=%s accepted=true order_id=%s",
            variant,
            order_id,
        )
        return {"success": True, **normalized}

    async def payment(self, order_id: int) -> dict[str, Any]:
        logger.info("[tray.order.payment.lookup] order_id=%s", order_id)
        complete = await self.complete(order_id)
        payment = complete["payment"]
        capability = complete["payment_capability"]
        normalized_order_id = complete.get("order", {}).get("id") or order_id
        logger.info(
            "[tray.order.payment.normalized] order_id=%s payment_type=%s "
            "has_payment=%s payment_url_present=%s",
            normalized_order_id,
            _safe_log_value(payment.get("type")),
            _safe_log_value(payment.get("has_payment")),
            str(bool(payment.get("payment_url"))).lower(),
        )
        return {
            "success": True,
            "order_id": normalized_order_id,
            "payment": payment,
            "payment_capability": capability,
        }

    async def update_shipping(
        self,
        order_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            order_fields = _tray_shipping_update(payload)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise TrayValidationError("order_shipping_payload_invalid") from exc
        logger.info(
            "[tray.order.shipping.update] order_id=%s fields=%s",
            order_id,
            sorted(order_fields),
        )
        response = await self.client.request(
            "PUT",
            f"/orders/{order_id}",
            json={"Order": order_fields},
        )
        normalized = normalize_order_create(response)
        if normalized["order_id"] is None:
            normalized["order_id"] = order_id
        logger.info(
            "[tray.order.shipping.update] order_id=%s success=true",
            order_id,
        )
        return normalized


def _decimal_string(value: Any) -> str:
    decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    if not decimal.is_finite() or decimal < 0:
        raise ValueError("money value must be finite and non-negative")
    return format(decimal, "f")


def _tray_order_payload(payload: dict[str, Any]) -> dict[str, Any]:
    customer = {
        key: payload["customer"][key]
        for key in ("type", "name", "cpf", "email", "phone", "rg", "gender")
        if payload["customer"].get(key) is not None
    }
    address = {
        key: payload["address"][key]
        for key in (
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
        if payload["address"].get(key) is not None
    }
    customer["CustomerAddress"] = [address]

    products = []
    for product in payload["products"]:
        sold = {
            "product_id": product["product_id"],
            "price": _decimal_string(product["price"]),
            "original_price": _decimal_string(product["original_price"]),
            "quantity": product["quantity"],
        }
        variant_id = normalize_optional_variant_id(product.get("variant_id"))
        if variant_id is not None:
            sold["variant_id"] = variant_id
        products.append(sold)

    order = {
        "point_sale": DEFAULT_ORDER_POINT_SALE,
        "session_id": payload["session_id"],
        "shipment": payload["shipping"]["name"],
        "shipment_value": _decimal_string(payload["shipping"]["value"]),
        "payment_form": payload["payment"]["name"],
        "Customer": customer,
        "ProductsSold": products,
    }
    return {"Order": order}


def _tray_shipping_update(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in (
        "status_id",
        "shipment",
        "sending_code",
        "tracking_url",
    ):
        if payload.get(key) is not None:
            result[key] = payload[key]
    if payload.get("shipment_value") is not None:
        result["shipment_value"] = _decimal_string(payload["shipment_value"])
    if payload.get("sending_date") is not None:
        value = payload["sending_date"]
        result["sending_date"] = value.isoformat() if isinstance(value, date) else str(value)
    if not result:
        raise ValueError("at least one shipping field is required")
    return result


def _is_auth_failure(exc: TrayAPIError) -> bool:
    return exc.status_code == 401 or str(exc.diagnostics.get("error_code", "")) == "401"


def _is_ambiguous_api_failure(exc: TrayAPIError) -> bool:
    return bool(exc.diagnostics.get("invalid_response")) or (
        exc.status_code is not None and 300 <= exc.status_code < 400
    )


def _session_hash(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:10]


def _safe_log_value(value: Any) -> str:
    if value is None:
        return "none"
    text = str(value).strip()
    if not text or len(text) > 64:
        return "present"
    if any(not (character.isalnum() or character in "_.-") for character in text):
        return "present"
    return text


def _log_create_request(payload: dict[str, Any]) -> None:
    logger.info(
        "[tray.order.create.request] session_length=%s session_hash=%s "
        "product_count=%s customer_cpf_present=%s address_present=%s "
        "zipcode_prefix=%s variant_count=%s",
        len(payload["session_id"]),
        _session_hash(payload["session_id"]),
        len(payload["products"]),
        str(bool(payload["customer"].get("cpf"))).lower(),
        str(bool(payload.get("address"))).lower(),
        str(payload["address"].get("zip_code", ""))[:3],
        sum(
            1
            for product in payload["products"]
            if (
                normalize_optional_variant_id(product.get("variant_id"))
                is not None
            )
        ),
    )


def _normalize_created(response: Any, *, reconciled: bool) -> dict[str, Any]:
    normalized = normalize_order_create(response)
    logger.info(
        "[tray.order.create.response] success=true order_id=%s reconciled=%s",
        normalized.get("order_id"),
        str(reconciled).lower(),
    )
    return normalized


def _normalize_reconciled(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": True,
        "order_id": order.get("id"),
        "reconciled": True,
        "order": order,
    }
