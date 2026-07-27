from typing import Any

from ..identifiers import normalize_optional_variant_id
from .common import first, number
from .image import normalize_images, primary_image_url


def _unwrap_cart(payload: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}, {}
    cart = payload.get("Cart", payload.get("cart", payload))
    return (cart if isinstance(cart, dict) else {}), payload


def _normalize_read_variant_id(value: Any) -> int | None:
    try:
        return normalize_optional_variant_id(value)
    except ValueError:
        return None


def _normalize_cart_product(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    product_id = first(value, "product_id", "id")
    if product_id is not None:
        result["product_id"] = product_id
    for key in ("cart_id", "name", "reference", "additional_information", "available"):
        if key in value:
            result[key] = value[key]
    variant_id = _normalize_read_variant_id(value.get("variant_id"))
    if variant_id is not None:
        result["variant_id"] = variant_id
    if "quantity" in value:
        result["quantity"] = number(value["quantity"], integer=True)
    if "price" in value:
        result["price"] = number(value["price"])
    if "stock" in value:
        result["stock"] = number(value["stock"], integer=True)
    images = normalize_images(value.get("ProductImage") or value.get("images"))
    result["images"] = images
    result["primary_image_url"] = primary_image_url(images)
    methods = value.get("PaymentMethodByProduct")
    if isinstance(methods, dict):
        methods = [methods]
    if isinstance(methods, list):
        result["payment_methods"] = [
            {key: method[key] for key in ("payment_method_id", "blocked", "max_plots") if key in method}
            for method in methods if isinstance(method, dict)
        ]
    return result


def normalize_cart(payload: Any) -> dict[str, Any]:
    cart, root = _unwrap_cart(payload)
    result: dict[str, Any] = {}
    cart_id = first(root, "id", "cart_id") or first(cart, "id", "cart_id")
    if cart_id is not None:
        result["cart_id"] = cart_id

    for output, keys in (
        ("session_id", ("session_id",)),
        ("cart_url", ("cart_url",)),
        ("message", ("message",)),
        ("code", ("code",)),
    ):
        value = first(root, *keys)
        if value is None:
            value = first(cart, *keys)
        if value is not None:
            result[output] = value

    for key in ("product_id", "product_name", "additional_information", "date"):
        if key in cart:
            result[key] = cart[key]
    variant_id = _normalize_read_variant_id(cart.get("variant_id"))
    if variant_id is not None:
        result["variant_id"] = variant_id
    if "quantity" in cart:
        result["quantity"] = number(cart["quantity"], integer=True)
    for key in ("price", "total", "sub_total"):
        if key in cart:
            result[key] = number(cart[key])

    products = cart.get("Products", cart.get("products"))
    if isinstance(products, dict):
        products = [products]
    if isinstance(products, list):
        result["items"] = [_normalize_cart_product(item) for item in products if isinstance(item, dict)]
    return result
