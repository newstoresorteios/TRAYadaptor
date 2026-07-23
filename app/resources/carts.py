import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from ..exceptions import TrayAPIError, TrayConnectionError, TrayError, TrayValidationError
from ..normalizers.cart import normalize_cart

logger = logging.getLogger("tray.cart")


class CartResource:
    def __init__(self, client):
        self.client = client

    async def create(self, payload: dict[str, Any]):
        logger.info(
            "[tray.cart.request] has_product_id=%s has_variant_id=%s "
            "quantity_valid=%s price_valid=%s has_session_id=%s",
            _boolean(bool(payload.get("product_id"))),
            _boolean(payload.get("variant_id") is not None),
            _boolean(_quantity_is_valid(payload.get("quantity"))),
            _boolean(_price_is_valid(payload.get("price"))),
            _boolean(payload.get("session_id") is not None),
        )
        try:
            cart_form = _tray_cart_form(payload)
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            logger.info(
                "[tray.cart.failure] stage=payload_translation "
                "error_type=%s upstream_status=none",
                type(exc).__name__,
            )
            raise TrayValidationError("cart_payload_invalid") from exc

        try:
            response = await self.client.request(
                "POST",
                "/carts/",
                data=cart_form,
                retry_on_auth_failure=False,
                request_observer=_log_request_sent,
                response_observer=_log_upstream_response,
            )
        except (TrayAPIError, TrayConnectionError) as exc:
            logger.info(
                "[tray.cart.failure] stage=upstream_http "
                "error_type=%s upstream_status=%s",
                type(exc).__name__,
                getattr(exc, "status_code", None) or "none",
            )
            raise
        except TrayError as exc:
            logger.info(
                "[tray.cart.failure] stage=upstream_http "
                "error_type=%s upstream_status=none",
                type(exc).__name__,
            )
            raise

        try:
            cart_response = normalize_cart(response)
        except Exception as exc:
            logger.info(
                "[tray.cart.failure] stage=normalization "
                "error_type=%s upstream_status=none",
                type(exc).__name__,
            )
            raise
        logger.info("operation=create success=true")
        return {"success": True, "cart": cart_response}

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


def _decimal_string(value: Any) -> str:
    return format(value if isinstance(value, Decimal) else Decimal(str(value)), "f")


def _tray_cart_form(payload: dict[str, Any]) -> dict[str, str]:
    product_id = _numeric_identifier(payload["product_id"])
    quantity = payload["quantity"]
    if not _quantity_is_valid(quantity):
        raise ValueError("quantity must be an integer greater than zero")
    if not _price_is_valid(payload["price"]):
        raise ValueError("price must be a finite non-negative decimal")

    cart = {
        '["Cart"]["product_id"]': product_id,
        '["Cart"]["quantity"]': str(quantity),
        '["Cart"]["price"]': _decimal_string(payload["price"]),
    }
    variant_id = _optional_identifier(payload.get("variant_id"), numeric=True)
    if variant_id is not None:
        cart['["Cart"]["variant_id"]'] = variant_id
    session_id = _optional_identifier(payload.get("session_id"))
    if session_id is not None:
        cart['["Cart"]["session_id"]'] = session_id
    return cart


def _numeric_identifier(value: Any) -> str:
    text = str(value).strip()
    if not text.isascii() or not text.isdecimal() or int(text) < 1:
        raise ValueError("identifier must be a positive integer")
    return text


def _optional_identifier(value: Any, *, numeric: bool = False) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null"}:
        raise ValueError("optional identifier is invalid")
    return _numeric_identifier(text) if numeric else text


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


def _log_request_sent() -> None:
    logger.info(
        "[tray.cart.upstream] request_sent=true response_received=false "
        "status_code=none response_is_json=unknown response_keys=[]"
    )


def _log_upstream_response(diagnostics: dict[str, Any]) -> None:
    logger.info(
        "[tray.cart.upstream] request_sent=true response_received=%s "
        "status_code=%s response_is_json=%s response_keys=%s "
        "error_code=%s error_type=%s error_fields=%s error_message=%s",
        _boolean(bool(diagnostics.get("response_received"))),
        diagnostics.get("status_code", "none"),
        _boolean(bool(diagnostics.get("response_is_json"))),
        diagnostics.get("response_keys", []),
        diagnostics.get("error_code", "none"),
        diagnostics.get("error_type", "none"),
        diagnostics.get("error_fields", []),
        diagnostics.get("error_message", "none"),
    )
