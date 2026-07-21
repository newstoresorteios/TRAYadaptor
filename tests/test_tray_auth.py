import httpx
import pytest

from app.config import Settings
from app.exceptions import TrayAuthenticationError, TrayConnectionError
from app.main import normalize_products
from app.tray_auth import TrayAuth
from app.tray_client import TrayClient


def settings():
    return Settings("https://tray.test", "code", "key", "secret", 180, "687890")


def response(request, body, status=200):
    return httpx.Response(status, json=body, request=request)


@pytest.mark.asyncio
async def test_auth_success_and_store_string():
    async def handler(request): return response(request, {"access_token": "a", "refresh_token": "r", "store_id": 687890})
    auth = TrayAuth(settings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    state = await auth.authenticate()
    assert state.store_id == "687890"


@pytest.mark.asyncio
async def test_auth_missing_token_and_wrong_store():
    async def missing(request): return response(request, {"refresh_token": "r", "store_id": "687890"})
    with pytest.raises(TrayAuthenticationError): await TrayAuth(settings(), httpx.AsyncClient(transport=httpx.MockTransport(missing))).authenticate()
    async def wrong(request): return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "other"})
    with pytest.raises(TrayAuthenticationError): await TrayAuth(settings(), httpx.AsyncClient(transport=httpx.MockTransport(wrong))).authenticate()


@pytest.mark.asyncio
async def test_timeout_and_http_error():
    async def timeout(request): raise httpx.ReadTimeout("timeout", request=request)
    with pytest.raises(TrayConnectionError): await TrayAuth(settings(), httpx.AsyncClient(transport=httpx.MockTransport(timeout))).authenticate()
    async def error(request): return response(request, {}, 500)
    with pytest.raises(TrayAuthenticationError): await TrayAuth(settings(), httpx.AsyncClient(transport=httpx.MockTransport(error))).authenticate()


@pytest.mark.asyncio
async def test_product_listing():
    async def handler(request):
        if request.url.path.endswith("/auth"): return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        return response(request, {"Products": [{"Product": {"id": "1", "name": "Relógio", "price": "139.00", "stock": "51"}}]})
    auth = TrayAuth(settings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    products = await TrayClient(auth, auth.http_client).list_products()
    assert products["Products"]


def test_normalize_product():
    product = normalize_products({"Products": [{"Product": {"id": "1", "price": "139.00", "stock": "51"}}]})[0]
    assert product["price"] == 139.0 and product["stock"] == 51
