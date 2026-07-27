import logging

from ..exceptions import TrayError, TrayValidationError
from ..normalizers.payment import normalize_payment_methods, normalize_payment_options

logger = logging.getLogger("uvicorn.error.tray.payments")
logger.setLevel(logging.INFO)


class PaymentOptionsResource:
    def __init__(self, client):
        self.client = client

    async def list_options(
        self,
        *,
        cart_session_id: str | None = None,
        order_id: int | None = None,
    ):
        if (cart_session_id is None) == (order_id is None):
            raise TrayValidationError("payment_options_scope_invalid")
        if cart_session_id is not None:
            if not isinstance(cart_session_id, str) or not cart_session_id.strip():
                raise TrayValidationError("payment_options_scope_invalid")
            scope = "cart"
            params = {"cart_session_id": cart_session_id}
        else:
            if (
                not isinstance(order_id, int)
                or isinstance(order_id, bool)
                or order_id < 1
            ):
                raise TrayValidationError("payment_options_scope_invalid")
            scope = "order"
            params = {"order_id": order_id}
        try:
            payload = await self.client.request(
                "GET", "/payments/options", params=params
            )
            options = normalize_payment_options(payload)
            logger.info(
                "operation=options scope=%s success=true option_count=%d",
                scope,
                len(options),
            )
            return {"success": True, "payment_options": options}
        except TrayError as exc:
            logger.info(
                "operation=options scope=%s success=false status_code=%s "
                "error_type=%s",
                scope,
                getattr(exc, "status_code", None),
                type(exc).__name__,
            )
            raise

    async def list_for_cart(self, cart_session_id: str):
        return await self.list_options(cart_session_id=cart_session_id)

    async def list_for_order(self, order_id: int):
        return await self.list_options(order_id=order_id)

    async def list_active_methods(self):
        try:
            payload = await self.client.request(
                "GET", "/payments/methods/1/active"
            )
            methods = normalize_payment_methods(payload)
            logger.info("operation=active_methods success=true count=%d", len(methods))
            return {"success": True, "payment_methods": methods}
        except TrayError as exc:
            logger.info(
                "operation=active_methods success=false status_code=%s error_type=%s",
                getattr(exc, "status_code", None), type(exc).__name__,
            )
            raise
