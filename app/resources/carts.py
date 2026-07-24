import hashlib
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from ..exceptions import TrayAPIError, TrayConnectionError, TrayError, TrayValidationError
from ..normalizers.cart import normalize_cart
from ..normalizers.variant import normalize_variant

logger = logging.getLogger("uvicorn.error.tray.cart")
logger.setLevel(logging.INFO)


class CartResource:
    def __init__(self, client):
        self.client = client

    async def create(self, payload: dict[str, Any]):
        try:
            cart_payload = _tray_cart_payload(payload)
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            logger.info(
                "[tray.cart.failure] stage=payload_translation "
                "error_type=%s upstream_status=none",
                type(exc).__name__,
            )
            raise TrayValidationError("cart_payload_invalid") from exc

        await self._validate_variant_product(cart_payload["Cart"])
        _log_cart_request(cart_payload["Cart"])

        try:
            response = await self._post_cart(cart_payload, attempt="initial")
        except TrayAPIError as exc:
            if _is_auth_failure(exc):
                return await self._recover_after_auth_failure(payload, cart_payload)
            if exc.diagnostics.get("invalid_response"):
                return await self._recover_after_ambiguous_failure(
                    payload, cart_payload
                )
            raise
        except TrayConnectionError:
            return await self._recover_after_ambiguous_failure(payload, cart_payload)
        return _normalize_create_response(response, recovered=False)

    async def _validate_variant_product(self, cart: dict[str, Any]) -> None:
        variant_id = cart.get("variant_id")
        if variant_id is None:
            return
        response = await self.client.request(
            "GET", f"/products/variants/{variant_id}"
        )
        variant = normalize_variant(response)
        variant_product_id = variant.get("product_id")
        if variant_product_id is None:
            raise TrayValidationError("cart_variant_product_unverified")
        try:
            normalized_variant_product_id = _numeric_identifier(variant_product_id)
        except (TypeError, ValueError) as exc:
            raise TrayValidationError("cart_variant_product_unverified") from exc
        if normalized_variant_product_id != cart["product_id"]:
            raise TrayValidationError("cart_variant_product_mismatch")

    async def _post_cart(self, cart_payload: dict[str, Any], *, attempt: str) -> Any:
        request_sent = False

        def observe_request() -> None:
            nonlocal request_sent
            request_sent = True
            _log_request_sent(attempt)

        try:
            return await self.client.request(
                "POST",
                "/carts",
                json=cart_payload,
                retry_on_auth_failure=False,
                follow_redirects=False,
                reject_redirects=True,
                request_observer=observe_request,
                response_observer=lambda diagnostics: _log_upstream_response(
                    diagnostics, attempt
                ),
            )
        except (TrayAPIError, TrayConnectionError) as exc:
            logger.info(
                "[tray.cart.failure] stage=%s attempt=%s "
                "error_type=%s upstream_status=%s final=%s",
                "upstream_http" if request_sent else "before_send",
                attempt,
                type(exc).__name__,
                getattr(exc, "status_code", None) or "none",
                _boolean(attempt == "retry" or not _is_auth_failure(exc))
                if isinstance(exc, TrayAPIError)
                else "true",
            )
            raise
        except TrayError as exc:
            logger.info(
                "[tray.cart.failure] stage=%s attempt=%s "
                "error_type=%s upstream_status=none final=true",
                "upstream_http" if request_sent else "before_send",
                attempt,
                type(exc).__name__,
            )
            raise

    async def _recover_after_auth_failure(
        self, payload: dict[str, Any], cart_payload: dict[str, Any]
    ) -> dict[str, Any]:
        logger.info("[tray.cart.auth] status=401 action=refresh_started")
        try:
            await self.client.auth.refresh()
        except TrayError as exc:
            logger.info(
                "[tray.cart.failure] stage=refresh error_type=%s upstream_status=%s",
                type(exc).__name__,
                getattr(exc, "status_code", None) or "none",
            )
            raise
        logger.info("[tray.cart.auth] status=401 action=refresh_succeeded")
        return await self._reconcile_then_retry(
            payload, cart_payload, reason="auth_401"
        )

    async def _recover_after_ambiguous_failure(
        self, payload: dict[str, Any], cart_payload: dict[str, Any]
    ) -> dict[str, Any]:
        logger.info(
            "[tray.cart.reconciliation] status=started reason=ambiguous_transport"
        )
        return await self._reconcile_then_retry(
            payload, cart_payload, reason="ambiguous_transport"
        )

    async def _reconcile_then_retry(
        self,
        payload: dict[str, Any],
        cart_payload: dict[str, Any],
        *,
        reason: str,
    ) -> dict[str, Any]:
        session_id = _session_identifier(payload["session_id"])
        if reason != "ambiguous_transport":
            logger.info("[tray.cart.reconciliation] status=started reason=%s", reason)
        try:
            response = await self.client.request(
                "GET",
                f"/carts/{session_id}",
                retry_on_auth_failure=False,
            )
            cart = _normalize_reconciliation_cart(response)
        except TrayAPIError as exc:
            if exc.status_code != 404:
                logger.info(
                    "[tray.cart.failure] stage=reconciliation "
                    "error_type=%s upstream_status=%s",
                    type(exc).__name__,
                    exc.status_code or "none",
                )
                raise
            cart = {}
            logger.info("[tray.cart.reconciliation] status=cart_not_found")
        except TrayError as exc:
            logger.info(
                "[tray.cart.failure] stage=reconciliation "
                "error_type=%s upstream_status=%s",
                type(exc).__name__,
                getattr(exc, "status_code", None) or "none",
            )
            raise

        if _cart_contains_product(cart, payload):
            logger.info(
                "[tray.cart.reconciliation] status=product_already_present "
                "action=completed_without_retry"
            )
            logger.info("operation=create success=true recovered=true retry=false")
            return {"success": True, "cart": cart}

        logger.info(
            "[tray.cart.reconciliation] status=product_not_found action=retry_once"
        )
        response = await self._post_cart(cart_payload, attempt="retry")
        return _normalize_create_response(response, recovered=True)

    async def get(self, session_id: str):
        try:
            response = await self.client.request("GET", f"/carts/{session_id}")
            cart = normalize_cart(response)
            logger.info("operation=read found=%s success=true", str(bool(cart)).lower())
            return {"success": True, "cart": cart}
        except TrayError as exc:
            logger.info(
                "operation=read found=false success=false status_code=%s error_type=%s",
                getattr(exc, "status_code", None), type(exc).__name__,
            )
            raise

    async def complete(self, session_id: str):
        try:
            response = await self.client.request("GET", f"/carts/{session_id}/complete")
            cart = normalize_cart(response)
            logger.info("operation=complete success=true item_count=%s", len(cart.get("items", [])))
            return {"success": True, "cart": cart}
        except TrayError as exc:
            logger.info(
                "operation=complete success=false status_code=%s error_type=%s",
                getattr(exc, "status_code", None), type(exc).__name__,
            )
            raise


def _tray_cart_payload(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    product_id = _numeric_identifier(payload["product_id"])
    session_id = _session_identifier(payload["session_id"])
    quantity = payload["quantity"]
    if not _quantity_is_valid(quantity):
        raise ValueError("quantity must be an integer greater than zero")
    if not _price_is_valid(payload["price"]):
        raise ValueError("price must be a finite non-negative decimal")

    cart = {
        "session_id": session_id,
        "product_id": product_id,
        "quantity": quantity,
    }
    variant_id = _optional_variant_identifier(payload.get("variant_id"))
    if variant_id is not None:
        cart["variant_id"] = variant_id
    return {"Cart": cart}


def _numeric_identifier(value: Any) -> int:
    text = str(value).strip()
    if not text.isascii() or not text.isdecimal() or int(text) < 1:
        raise ValueError("identifier must be a positive integer")
    return int(text)


def _optional_variant_identifier(value: Any) -> int | None:
    if value is None or str(value).strip() == "0":
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        raise ValueError("variant identifier is invalid")
    return _numeric_identifier(text)


def _session_identifier(value: Any) -> str:
    text = str(value).strip()
    if not text or len(text) > 32 or text.lower() in {"none", "null"}:
        raise ValueError("session identifier is invalid")
    return text


def _quantity_is_valid(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _price_is_valid(value: Any) -> bool:
    try:
        decimal = value if isinstance(value, Decimal) else Decimal(str(value))
        return decimal.is_finite() and decimal >= 0
    except (InvalidOperation, TypeError, ValueError):
        return False


def _boolean(value: bool) -> str:
    return str(value).lower()


def _session_length(value: Any) -> int:
    return len(str(value)) if value is not None else 0


def _session_hash(value: Any) -> str:
    if value is None:
        return "none"
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:10]


def _log_cart_request(cart: dict[str, Any]) -> None:
    logger.info(
        "[tray.cart.request] transport=json wrapper=Cart session_present=%s "
        "session_length=%s session_hash=%s product_id=%s product_id_type=%s "
        "variant_present=%s variant_id_type=%s quantity=%s quantity_type=%s "
        "price_forwarded=false",
        _boolean(bool(cart.get("session_id"))),
        _session_length(cart.get("session_id")),
        _session_hash(cart.get("session_id")),
        cart["product_id"],
        type(cart["product_id"]).__name__,
        _boolean("variant_id" in cart),
        type(cart["variant_id"]).__name__ if "variant_id" in cart else "none",
        cart["quantity"],
        type(cart["quantity"]).__name__,
    )


def _is_auth_failure(exc: TrayAPIError) -> bool:
    return exc.status_code == 401 or str(exc.diagnostics.get("error_code", "")) == "401"


def _variant_identity(value: Any) -> str | None:
    if value is None or str(value).strip() in {"", "0"}:
        return None
    return str(value).strip()


def _cart_contains_product(cart: dict[str, Any], payload: dict[str, Any]) -> bool:
    requested_product = str(payload["product_id"]).strip()
    requested_variant = _variant_identity(payload.get("variant_id"))
    candidates = cart.get("items", [])
    if not isinstance(candidates, list):
        candidates = []
    if "product_id" in cart:
        candidates = [cart, *candidates]
    for item in candidates:
        if not isinstance(item, dict):
            continue
        if str(item.get("product_id", "")).strip() != requested_product:
            continue
        if _variant_identity(item.get("variant_id")) == requested_variant:
            return True
    return False


def _normalize_reconciliation_cart(response: Any) -> dict[str, Any]:
    if not isinstance(response, list):
        return normalize_cart(response)
    items: list[dict[str, Any]] = []
    for value in response:
        normalized = normalize_cart(value)
        if "product_id" in normalized:
            items.append(normalized)
        raw_items = normalized.get("items")
        if isinstance(raw_items, list):
            items.extend(item for item in raw_items if isinstance(item, dict))
    return {"items": items}


def _normalize_create_response(response: Any, *, recovered: bool) -> dict[str, Any]:
    try:
        cart_response = normalize_cart(response)
    except Exception as exc:
        logger.info(
            "[tray.cart.failure] stage=normalization "
            "error_type=%s upstream_status=none",
            type(exc).__name__,
        )
        raise
    logger.info(
        "operation=create success=true recovered=%s",
        _boolean(recovered),
    )
    return {"success": True, "cart": cart_response}


def _log_request_sent(attempt: str) -> None:
    logger.info(
        "[tray.cart.upstream] request_sent=true response_received=false "
        "status_code=none response_is_json=unknown response_keys=[] attempt=%s",
        attempt,
    )


def _log_upstream_response(diagnostics: dict[str, Any], attempt: str) -> None:
    logger.info(
        "[tray.cart.upstream] request_sent=true response_received=%s "
        "status_code=%s content_type=%s response_is_json=%s response_keys=%s "
        "final_url_path=%s redirect_count=%s "
        "error_code=%s error_name=%s error_type=%s error_field=%s error_fields=%s "
        "error_causes=%s error_message=%s attempt=%s",
        _boolean(bool(diagnostics.get("response_received"))),
        diagnostics.get("status_code", "none"),
        diagnostics.get("content_type", "none"),
        _boolean(bool(diagnostics.get("response_is_json"))),
        diagnostics.get("response_keys", []),
        diagnostics.get("final_url_path", "none"),
        diagnostics.get("redirect_count", 0),
        diagnostics.get("error_code", "none"),
        diagnostics.get("error_name", "none"),
        diagnostics.get("error_type", "none"),
        diagnostics.get("error_field", "none"),
        diagnostics.get("error_fields", []),
        diagnostics.get("error_causes", []),
        diagnostics.get("error_message", "none"),
        attempt,
    )
