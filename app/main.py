from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse

from .config import get_settings
from .exceptions import TrayAPIError, TrayAuthenticationError, TrayConfigurationError, TrayConnectionError
from .tray_auth import TrayAuth
from .tray_client import TrayClient

app = FastAPI(title="TrayAdapter")
_tray_client: TrayClient | None = None


def _client() -> TrayClient:
    global _tray_client
    settings = get_settings()
    if _tray_client is None or _tray_client.auth.settings != settings:
        _tray_client = TrayClient(TrayAuth(settings))
    return _tray_client


@app.exception_handler(TrayConfigurationError)
@app.exception_handler(TrayAuthenticationError)
@app.exception_handler(TrayConnectionError)
@app.exception_handler(TrayAPIError)
async def tray_error_handler(_: Request, exc: Exception) -> JSONResponse:
    code = "tray_configuration_error" if isinstance(exc, TrayConfigurationError) else "tray_authentication_failed" if isinstance(exc, TrayAuthenticationError) else "tray_connection_failed" if isinstance(exc, TrayConnectionError) else "tray_api_error"
    return JSONResponse(status_code=503, content={"success": False, "error": code})


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "tray-adapter"}


@app.get("/tray/test-auth")
async def test_auth() -> dict[str, Any]:
    client = _client()
    state = await client.auth.authenticate()
    return {"success": True, "authenticated": True, "store_id": state.store_id, "access_token_received": True, "refresh_token_received": True}


@app.get("/tray/test-products")
async def test_products() -> dict[str, Any]:
    client = _client()
    state = await client.auth.get_valid_token()
    payload = await client.list_products(limit=1)
    products = normalize_products(payload)
    return {"success": True, "tray_connected": True, "store_id": state.store_id, "products_api": True, "products_returned": len(products)}


@app.get("/internal/products")
async def internal_products(name: str | None = None, limit: int = Query(10, ge=1, le=50)) -> dict[str, Any]:
    products = normalize_products(await _client().list_products(name=name, limit=limit))
    return {"success": True, "products": products}


def normalize_products(payload: Any) -> list[dict[str, Any]]:
    raw = payload.get("Products", payload.get("products", [])) if isinstance(payload, dict) else payload
    if isinstance(raw, dict):
        raw = [raw]
    result = []
    for item in raw if isinstance(raw, list) else []:
        product = item.get("Product", item) if isinstance(item, dict) else {}
        if not isinstance(product, dict):
            continue
        explicit = product.get("available", product.get("availability"))
        result.append({
            "id": _first(product, "id", "product_id"), "name": _first(product, "name", "title"),
            "sku": _first(product, "sku", "reference"), "price": _number(product.get("price")),
            "promotional_price": _number(product.get("promotional_price", product.get("promotionalPrice"))),
            "current_price": _number(product.get("current_price", product.get("price"))),
            "stock": _number(product.get("stock", product.get("quantity")), integer=True),
            "available": explicit if explicit is not None else None,
            "image_url": _first(product, "image_url", "image"), "product_url": _first(product, "product_url", "url"),
        })
    return result


def _first(value: dict[str, Any], *keys: str) -> Any:
    return next((value[k] for k in keys if value.get(k) is not None), None)


def _number(value: Any, integer: bool = False) -> float | int | None:
    if value is None or value == "":
        return None
    try:
        number = float(str(value).replace(",", "."))
        return int(number) if integer else number
    except (TypeError, ValueError):
        return None
