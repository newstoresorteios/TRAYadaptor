import logging

from ..exceptions import TrayError
from ..normalizers.payment import normalize_payment_options

logger = logging.getLogger("tray.payments")


class PaymentOptionsResource:
    def __init__(self, client):
        self.client = client

    async def list_for_cart(self, cart_session_id: str):
        try:
            payload = await self.client.request(
                "GET", "/payments/options", params={"cart_session_id": cart_session_id}
            )
            options = normalize_payment_options(payload)
            logger.info("operation=options success=true count=%d", len(options))
            return {"success": True, "payment_options": options}
        except TrayError as exc:
            logger.info(
                "operation=options success=false status_code=%s error_type=%s",
                getattr(exc, "status_code", None), type(exc).__name__,
            )
            raise
