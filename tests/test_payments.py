import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.resources.payments import PaymentOptionsResource
from app.tray_auth import TrayAuth
from app.tray_client import TrayClient


def settings():
    return Settings("https://tray.test/web_api", "code", "key", "secret", 180, "687890")


def response(request, body, status=200):
    return httpx.Response(status, json=body, request=request)


def client(handler):
    transport = httpx.MockTransport(handler)
    auth = TrayAuth(settings(), httpx.AsyncClient(transport=transport))
    return TrayClient(auth, auth.http_client)


def configure(monkeypatch):
    for key, value in {
        "TRAY_API_BASE": "https://tray.test/web_api",
        "TRAY_CODE": "code",
        "TRAY_CONSUMER_KEY": "key",
        "TRAY_CONSUMER_SECRET": "secret",
        "TRAY_STORE_CODE": "687890",
        "TRAY_ADAPTER_TOKEN": "adapter-token",
    }.items():
        monkeypatch.setenv(key, value)


@pytest.mark.asyncio
async def test_payment_options_preserve_card_plots_and_pix_discount():
    calls = []

    async def handler(request):
        calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        return response(request, {
            "paymentoptions": [
                {
                    "id": "1",
                    "name": "Cartão de crédito",
                    "text": "Visa",
                    "card": "1",
                    "discount_value": "0.00",
                    "increase_value": "0.00",
                    "total_base": "100.00",
                    "tax_value": "0.00",
                    "plots": {
                        "1": {
                            "value": "100.00",
                            "interest": "0",
                            "interest_value": "0.00",
                            "discount_value": "0.00",
                            "base_value": "100.00",
                            "order_total": "100.00",
                        },
                        "2": {
                            "value": "52.50",
                            "interest": "1",
                            "interest_value": "5.00",
                            "discount_value": "0.00",
                            "base_value": "100.00",
                            "order_total": "105.00",
                        },
                    },
                },
                {
                    "id": "2",
                    "name": "Pix",
                    "card": "0",
                    "discount_value": "5.00",
                    "increase_value": "0.00",
                    "total_base": "100.00",
                    "tax_value": "0.00",
                    "plots": [],
                },
            ]
        })

    result = await PaymentOptionsResource(client(handler)).list_for_cart("SESSION")

    assert calls[-1] == (
        "GET",
        "/web_api/payments/options",
        {"cart_session_id": "SESSION", "access_token": "a"},
    )
    card, pix = result["payment_options"]
    assert card["card"] == 1
    assert card["plots"][1] == {
        "installments": 2,
        "value": 52.5,
        "interest_value": 5.0,
        "discount_value": 0.0,
        "base_value": 100.0,
        "order_total": 105.0,
        "interest": "1",
    }
    assert pix["name"] == "Pix"
    assert pix["discount_value"] == 5.0
    assert pix["plots"] == []


class FakePaymentOptionsResource:
    async def list_for_cart(self, cart_session_id):
        return {
            "success": True,
            "payment_options": [{"id": "1", "name": "Pix", "cart_session_id": cart_session_id}],
        }


def test_payment_options_require_bearer_and_cart_session_id(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(main, "_payment_options_resource", lambda: FakePaymentOptionsResource())
    api = TestClient(main.app)

    assert api.get("/internal/payments/options?cart_session_id=SESSION").status_code == 401
    assert api.get(
        "/internal/payments/options?cart_session_id=SESSION",
        headers={"Authorization": "Bearer wrong"},
    ).status_code == 401
    assert api.get(
        "/internal/payments/options",
        headers={"Authorization": "Bearer adapter-token"},
    ).status_code == 422
    result = api.get(
        "/internal/payments/options?cart_session_id=SESSION",
        headers={"Authorization": "Bearer adapter-token"},
    )
    assert result.status_code == 200
    assert result.json()["payment_options"][0]["cart_session_id"] == "SESSION"


def test_payment_options_upstream_error_is_not_an_empty_result(monkeypatch):
    configure(monkeypatch)

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        return response(request, {"message": "Unavailable"}, 503)

    monkeypatch.setattr(
        main,
        "_payment_options_resource",
        lambda: PaymentOptionsResource(client(handler)),
    )
    result = TestClient(main.app).get(
        "/internal/payments/options?cart_session_id=SESSION",
        headers={"Authorization": "Bearer adapter-token"},
    )

    assert result.status_code == 503
    assert result.json() == {
        "success": False,
        "error": "tray_api_error",
        "status_code": 503,
    }


def test_no_payment_write_route_exists():
    payment_routes = [
        route
        for route in main.app.routes
        if getattr(route, "path", "").startswith("/internal/payments")
    ]

    assert [(route.path, route.methods) for route in payment_routes] == [
        ("/internal/payments/options", {"GET"})
    ]
