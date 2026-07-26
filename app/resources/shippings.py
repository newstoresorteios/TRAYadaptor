import logging
from decimal import Decimal
from typing import Any

from ..exceptions import TrayError, TrayValidationError
from ..normalizers.shipping import normalize_shipping_methods, normalize_shipping_quote

logger = logging.getLogger("uvicorn.error.tray.shipping")
logger.setLevel(logging.INFO)


class ShippingResource:
    def __init__(self, client):
        self.client = client

    async def quote(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            params = _quote_params(payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise TrayValidationError("shipping_quote_payload_invalid") from exc
        zipcode = str(payload["zipcode"])
        logger.info(
            "[tray.shipping.quote.request] zipcode_prefix=%s product_count=%s "
            "variant_count=%s",
            zipcode[:3],
            len(payload["products"]),
            sum(
                1
                for product in payload["products"]
                if product.get("variant_id") is not None
            ),
        )
        try:
            response = await self.client.request(
                "GET",
                "/shippings/cotation/",
                params=params,
            )
            options = normalize_shipping_quote(response)
            logger.info(
                "[tray.shipping.quote.response] success=true option_count=%s",
                len(options),
            )
            return {"success": True, "zipcode": zipcode, "options": options}
        except TrayError as exc:
            logger.info(
                "[tray.shipping.quote.response] success=false status_code=%s "
                "error_type=%s",
                getattr(exc, "status_code", None) or "none",
                type(exc).__name__,
            )
            raise

    async def methods(self, status: str | None = None) -> dict[str, Any]:
        params = {"status": status} if status is not None else None
        payload = await self.client.request("GET", "/shippings/", params=params)
        methods, paging = normalize_shipping_methods(payload)
        return {"success": True, "paging": paging, "methods": methods}


def _decimal_string(value: Any) -> str:
    decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    if not decimal.is_finite() or decimal < 0:
        raise ValueError("price must be a finite non-negative decimal")
    return format(decimal, "f")


def _quote_params(payload: dict[str, Any]) -> dict[str, Any]:
    zipcode = str(payload["zipcode"])
    if len(zipcode) != 8 or not zipcode.isascii() or not zipcode.isdecimal():
        raise ValueError("zipcode must contain 8 digits")
    products = payload["products"]
    if not isinstance(products, list) or not products:
        raise ValueError("products must not be empty")
    params: dict[str, Any] = {"zipcode": zipcode}
    for index, product in enumerate(products):
        product_id = product["product_id"]
        quantity = product["quantity"]
        if (
            not isinstance(product_id, int)
            or isinstance(product_id, bool)
            or product_id < 1
        ):
            raise ValueError("product_id must be a positive integer")
        if (
            not isinstance(quantity, int)
            or isinstance(quantity, bool)
            or quantity < 1
        ):
            raise ValueError("quantity must be a positive integer")
        prefix = f"products[{index}]"
        params[f"{prefix}[product_id]"] = product_id
        params[f"{prefix}[price]"] = _decimal_string(product["price"])
        params[f"{prefix}[quantity]"] = quantity
        variant_id = product.get("variant_id")
        if variant_id is not None:
            if (
                not isinstance(variant_id, int)
                or isinstance(variant_id, bool)
                or variant_id < 1
            ):
                raise ValueError("variant_id must be a positive integer")
            params[f"{prefix}[sku]"] = variant_id
    return params
