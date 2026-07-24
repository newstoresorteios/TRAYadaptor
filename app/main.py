from typing import Any

import hmac
import logging

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .exceptions import TrayAPIError, TrayAuthenticationError, TrayConfigurationError, TrayConnectionError, TrayError, TrayValidationError
from .resources.brands import BrandResource
from .resources.categories import CategoryResource
from .resources.carts import CartResource
from .resources.coupons import CouponResource
from .resources.customers import CustomerResource
from .resources.inventory import InventoryResource
from .resources.kits import KitResource
from .resources.payments import PaymentOptionsResource
from .resources.products import ProductResource
from .resources.users import UserResource
from .resources.variants import VariantResource
from .schemas.carts import CartCreateRequest
from .normalizers.common import items
from .normalizers.product import normalize_product
from .tray_auth import TrayAuth
from .tray_client import TrayClient

app = FastAPI(title="TrayAdapter")
_tray_client: TrayClient | None = None
cart_logger = logging.getLogger("uvicorn.error.tray.cart")
cart_logger.setLevel(logging.INFO)


@app.middleware("http")
async def cart_validation_observability(request: Request, call_next):
    response = await call_next(request)
    if (
        request.method == "POST"
        and request.url.path == "/internal/carts"
        and response.status_code == 422
    ):
        cart_logger.info(
            "[tray.cart.failure] stage=internal_validation "
            "error_type=request_validation upstream_status=none"
        )
    return response


def _client() -> TrayClient:
    global _tray_client
    settings = get_settings()
    if _tray_client is None or _tray_client.auth.settings != settings:
        _tray_client = TrayClient(TrayAuth(settings))
    return _tray_client


def _resources():
    client = _client()
    return client, ProductResource(client), BrandResource(client), KitResource(client), InventoryResource(client), CustomerResource(client), CouponResource(client), UserResource(client)


def _category_resource() -> CategoryResource:
    return CategoryResource(_client())


def _variant_resource() -> VariantResource:
    return VariantResource(_client())


def _cart_resource() -> CartResource:
    return CartResource(_client())


def _payment_options_resource() -> PaymentOptionsResource:
    return PaymentOptionsResource(_client())


def require_internal_token(request: Request) -> None:
    authorization = request.headers.get("Authorization", "")
    scheme, _, supplied = authorization.partition(" ")
    expected = get_settings().tray_adapter_token
    if scheme.lower() != "bearer" or not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Bearer"})


@app.exception_handler(TrayConfigurationError)
@app.exception_handler(TrayAuthenticationError)
@app.exception_handler(TrayConnectionError)
@app.exception_handler(TrayAPIError)
@app.exception_handler(TrayValidationError)
async def tray_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, TrayConfigurationError): code, status = "tray_configuration_error", 503
    elif isinstance(exc, TrayAuthenticationError): code, status = "tray_authentication_failed", 503
    elif isinstance(exc, TrayConnectionError): code, status = "tray_connection_failed", 503
    elif isinstance(exc, TrayValidationError): code, status = str(exc), 400
    else: code, status = "tray_api_error", getattr(exc, "status_code", None) or 503
    content = {"success": False, "error": code}
    if isinstance(exc, TrayAPIError):
        diagnostics = exc.diagnostics
        content.update({
            "status_code": status,
            "tray_error_code": diagnostics.get("error_code"),
            "tray_error_type": diagnostics.get("error_type"),
            "tray_error_field": diagnostics.get("error_field"),
            "tray_error_fields": diagnostics.get("error_fields", []),
            "tray_error_message": diagnostics.get("error_message"),
        })
        if request.url.path == "/internal/carts":
            content.update({
                "tray_error_name": diagnostics.get("error_name"),
                "tray_error_causes": diagnostics.get("error_causes", []),
            })
    return JSONResponse(status_code=status, content=content)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "tray-adapter"}


@app.get("/tray/test-auth")
async def test_auth():
    state = await _client().auth.authenticate()
    return {"success": True, "authenticated": True, "store_id": state.store_id, "access_token_received": True, "refresh_token_received": True}


@app.get("/tray/test-products")
async def test_products():
    client, products, *_ = _resources()
    state = await client.auth.get_valid_token()
    result = await products.list({"limit": 1})
    return {"success": True, "tray_connected": True, "store_id": state.store_id, "products_api": True, "products_returned": len(result["products"])}


def _params(request: Request, allowed: set[str], limit_default: int = 20, limit_max: int = 50):
    values = {key: value for key, value in request.query_params.items() if key in allowed and value != ""}
    if "limit" in allowed:
        values["limit"] = min(int(values.get("limit", limit_default)), limit_max)
    return values


PRODUCT_FILTERS = {
    "id", "name", "reference", "category_id", "ean", "price", "price_range",
    "brand", "brand_id", "model", "available", "available_in_store", "stock",
    "promotion", "free_shipping", "release", "hot", "quantity_sold",
    "release_date", "rand", "sort", "limit", "page", "attrs", "created",
    "modified", "property_name", "property_id", "property_value",
    "property_value_id", "current_price", "current_price_range",
}
CUSTOMER_FILTERS = {"id", "name", "email", "cpf", "cnpj", "created", "modified", "attrs", "limit", "page", "sort"}


def _product_params(request: Request) -> dict[str, Any]:
    values = {
        key: value
        for key, value in request.query_params.items()
        if key in PRODUCT_FILTERS and value != ""
    }
    try:
        limit = int(values.get("limit", 20))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="limit must be an integer") from exc
    if not 1 <= limit <= 50:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 50")
    values["limit"] = limit
    for key in ("available", "available_in_store"):
        if key in values:
            lowered = values[key].lower()
            if lowered == "true":
                values[key] = "1"
            elif lowered == "false":
                values[key] = "0"
    return values


def _catalog_params(request: Request, allowed: set[str]) -> dict[str, Any]:
    values = {
        key: value
        for key, value in request.query_params.items()
        if key in allowed and value != ""
    }
    try:
        limit = int(values.get("limit", 20))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="limit must be an integer") from exc
    if not 1 <= limit <= 50:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 50")
    values["limit"] = limit
    return values


def normalize_products(payload: Any) -> list[dict[str, Any]]:
    values, _ = items(payload, "Products", "product")
    return [normalize_product(value) for value in values]


@app.get("/internal/products", dependencies=[Depends(require_internal_token)])
async def internal_products(request: Request):
    _, resource, *_ = _resources()
    return await resource.list(_product_params(request))


@app.get("/internal/products/variants", dependencies=[Depends(require_internal_token)])
async def internal_variants(request: Request):
    allowed = {"id", "product_id", "ean", "price", "promotional_price", "stock", "minimum_stock", "modified", "sort", "limit", "page"}
    return await _variant_resource().list(_catalog_params(request, allowed))


@app.get("/internal/products/variants/{variant_id}", dependencies=[Depends(require_internal_token)])
async def internal_variant(variant_id: str):
    return await _variant_resource().get(variant_id)


@app.get("/internal/products/{product_id}", dependencies=[Depends(require_internal_token)])
async def internal_product(product_id: str):
    return await _resources()[1].get(product_id)


@app.get("/internal/products/{product_id}/stock", dependencies=[Depends(require_internal_token)])
async def internal_product_stock(product_id: str):
    return await _resources()[1].get_product_stock(product_id)


@app.get("/internal/categories", dependencies=[Depends(require_internal_token)])
async def internal_categories(request: Request):
    return await _category_resource().list(_catalog_params(request, {"attrs", "limit", "page", "sort"}))


@app.get("/internal/categories/tree/{category_id}", dependencies=[Depends(require_internal_token)])
async def internal_category_tree(category_id: str):
    return await _category_resource().tree(category_id)


@app.get("/internal/categories/{category_id}", dependencies=[Depends(require_internal_token)])
async def internal_category(category_id: str):
    return await _category_resource().get(category_id)


@app.post("/internal/carts", dependencies=[Depends(require_internal_token)])
async def internal_cart_create(payload: CartCreateRequest):
    return await _cart_resource().create(payload.model_dump(exclude_none=True))


@app.get("/internal/carts/{session_id}/complete", dependencies=[Depends(require_internal_token)])
async def internal_cart_complete(session_id: str):
    return await _cart_resource().complete(session_id)


@app.get("/internal/carts/{session_id}", dependencies=[Depends(require_internal_token)])
async def internal_cart(session_id: str):
    return await _cart_resource().get(session_id)


@app.get("/internal/payments/options", dependencies=[Depends(require_internal_token)])
async def internal_payment_options(cart_session_id: str = Query(..., min_length=1)):
    return await _payment_options_resource().list_for_cart(cart_session_id)


@app.get("/internal/payments/methods/active", dependencies=[Depends(require_internal_token)])
async def internal_active_payment_methods():
    return await _payment_options_resource().list_active_methods()


@app.get("/internal/brands", dependencies=[Depends(require_internal_token)])
async def internal_brands(request: Request):
    return await _resources()[2].list(_params(request, {"attrs", "sort", "limit", "page"}))


@app.get("/internal/brands/{brand_id}", dependencies=[Depends(require_internal_token)])
async def internal_brand(brand_id: str):
    return await _resources()[2].get(brand_id)


@app.get("/internal/kits", dependencies=[Depends(require_internal_token)])
async def internal_kits(request: Request):
    return await _resources()[3].list(_params(request, {"limit", "page", "sort", "attrs"}))


@app.get("/internal/inventory/distribution-centers", dependencies=[Depends(require_internal_token)])
async def internal_distribution_centers(request: Request):
    return await _resources()[4].distribution_centers(_params(request, {"limit", "page", "sort", "attrs"}))


@app.get("/internal/inventory/distribution-centers/{center_id}", dependencies=[Depends(require_internal_token)])
async def internal_distribution_center(center_id: str):
    return await _resources()[4].distribution_center(center_id)


@app.get("/internal/inventory/products/{product_id}/distribution-centers", dependencies=[Depends(require_internal_token)])
async def internal_product_distribution_centers(product_id: str):
    return await _resources()[4].detailed_product_stock(product_id)


@app.get("/internal/customers", dependencies=[Depends(require_internal_token)])
async def internal_customers(request: Request):
    return await _resources()[5].list(_params(request, CUSTOMER_FILTERS))


@app.get("/internal/customers/{customer_id}", dependencies=[Depends(require_internal_token)])
async def internal_customer(customer_id: str):
    return await _resources()[5].get(customer_id)


@app.get("/internal/customer-addresses", dependencies=[Depends(require_internal_token)])
async def internal_customer_addresses(request: Request):
    return await _resources()[5].addresses(_params(request, {"customer_id", "attrs", "limit", "page", "sort"}))


@app.get("/internal/customer-addresses/{address_id}", dependencies=[Depends(require_internal_token)])
async def internal_customer_address(address_id: str):
    return await _resources()[5].address(address_id)


@app.get("/internal/coupons", dependencies=[Depends(require_internal_token)])
async def internal_coupons(request: Request):
    return await _resources()[6].list(_params(request, {"limit", "page", "sort", "attrs", "code"}))


@app.get("/internal/coupons/{coupon_id}", dependencies=[Depends(require_internal_token)])
async def internal_coupon(coupon_id: str):
    return await _resources()[6].get(coupon_id)


async def _coupon_relationship(kind: str, coupon_id: str):
    return await _resources()[6].relationship(kind, coupon_id)


@app.get("/internal/coupons/{coupon_id}/customers", dependencies=[Depends(require_internal_token)])
async def coupon_customers(coupon_id: str): return await _coupon_relationship("customer", coupon_id)
@app.get("/internal/coupons/{coupon_id}/products", dependencies=[Depends(require_internal_token)])
async def coupon_products(coupon_id: str): return await _coupon_relationship("product", coupon_id)
@app.get("/internal/coupons/{coupon_id}/categories", dependencies=[Depends(require_internal_token)])
async def coupon_categories(coupon_id: str): return await _coupon_relationship("category", coupon_id)
@app.get("/internal/coupons/{coupon_id}/brands", dependencies=[Depends(require_internal_token)])
async def coupon_brands(coupon_id: str): return await _coupon_relationship("brand", coupon_id)
@app.get("/internal/coupons/{coupon_id}/shipping", dependencies=[Depends(require_internal_token)])
async def coupon_shipping(coupon_id: str): return await _coupon_relationship("shipping", coupon_id)
@app.get("/internal/coupons/{coupon_id}/gifts", dependencies=[Depends(require_internal_token)])
async def coupon_gifts(coupon_id: str): return await _coupon_relationship("gift", coupon_id)


@app.get("/internal/users", dependencies=[Depends(require_internal_token)])
async def internal_users(request: Request):
    return await _resources()[7].list(_params(request, {"limit", "page", "sort", "attrs"}))


@app.get("/tray/test-resources")
async def test_resources():
    client, products, brands, kits, inventory, customers, coupons, users = _resources()
    checks = {"products": (products.list, {"limit": 1}), "brands": (brands.list, {"limit": 1}), "kits": (kits.list, {"limit": 1}), "customers": (customers.list, {"limit": 1}), "coupons": (coupons.list, {"limit": 1}), "users": (users.list, {"limit": 1}), "multicd": (inventory.distribution_centers, {"limit": 1})}
    resources = {}
    for name, (operation, params) in checks.items():
        try:
            await operation(params)
            resources[name] = True
        except TrayError as exc:
            resources[name] = {"success": False, "status": getattr(exc, "status_code", None) or 503, "error": "resource_unavailable"}
    return {"success": all(value is True for value in resources.values()), "store_id": (client.auth.state.store_id if client.auth.state else None), "resources": resources}
