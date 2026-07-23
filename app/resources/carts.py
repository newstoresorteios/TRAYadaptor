import logging
from decimal import Decimal
from typing import Any

from ..exceptions import TrayError
from ..normalizers.cart import normalize_cart

logger = logging.getLogger("tray.cart")


class CartResource:
    def __init__(self, client):
        self.client = client

    async def create(self, payload: dict[str, Any]):
        cart = {
            "product_id": payload["product_id"],
            "quantity": payload["quantity"],
            "price": _decimal_string(payload["price"]),
        }
        for key in ("variant_id", "session_id"):
            if payload.get(key) is not None:
                cart[key] = payload[key]

        logger.info(
            "operation=create has_product_id=true has_variant_id=%s quantity=%s has_session_id=%s",
            str("variant_id" in cart).lower(), cart["quantity"], str("session_id" in cart).lower(),
        )
        try:
            response = await self.client.request(
                "POST", "/carts/", json={"Cart": cart}, retry_on_auth_failure=False
            )
            logger.info("operation=create success=true")
            return {"success": True, "cart": normalize_cart(response)}
        except TrayError as exc:
            logger.info(
                "operation=create success=false status_code=%s error_type=%s",
                getattr(exc, "status_code", None), type(exc).__name__,
            )
            raise

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
