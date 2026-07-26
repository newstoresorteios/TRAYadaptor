from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.exceptions import TrayAPIError
from app.resources.shippings import ShippingResource
from app.tray_auth import TrayAuth
from app.tray_client import TrayClient


def settings():
    return Settings(
        "https://tray.test/web_api",
        "code",
        "key",
        "secret",
        tray_store_code="687890",
        tray_adapter_token="adapter-token",
    )


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
async def test_shipping_quote_translates_zipcode_products_variants_and_indices():
    seen = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        seen.append(request)
        return response(
            request,
            {
                "Shipping": {
                    "cotation": [
                        {
                            "id": "1",
                            "id_quotation": "9",
                            "name": "PAC Tray",
                            "identifier": "pac",
                            "value": "35.10",
                            "min_period": "2",
                            "max_period": "8",
                            "estimated_delivery_date": "2026-08-03",
                            "information": "factual",
                            "taxe": {"name": None, "value": "0"},
                        }
                    ]
                }
            },
        )

    result = await ShippingResource(client(handler)).quote(
        {
            "zipcode": "19900000",
            "products": [
                {
                    "product_id": 803,
                    "price": Decimal("4699.99"),
                    "quantity": 1,
                },
                {
                    "product_id": 804,
                    "variant_id": 123,
                    "price": Decimal("100.00"),
                    "quantity": 2,
                },
            ],
        }
    )

    params = seen[0].url.params
    assert seen[0].url.path == "/web_api/shippings/cotation/"
    assert params["zipcode"] == "19900000"
    assert params["products[0][product_id]"] == "803"
    assert params["products[0][price]"] == "4699.99"
    assert params["products[0][quantity]"] == "1"
    assert "products[0][sku]" not in params
    assert params["products[1][product_id]"] == "804"
    assert params["products[1][sku]"] == "123"
    assert result == {
        "success": True,
        "zipcode": "19900000",
        "options": [
            {
                "shipping_id": 1,
                "quotation_id": "9",
                "name": "PAC Tray",
                "identifier": "pac",
                "price": "35.10",
                "min_period": 2,
                "max_period": 8,
                "estimated_delivery_date": "2026-08-03",
                "information": "factual",
                "tax_name": None,
                "tax_value": "0",
            }
        ],
    }


def test_shipping_quote_route_normalizes_zipcode_and_rejects_invalid_products(
    monkeypatch,
):
    configure(monkeypatch)

    class RecordingResource:
        def __init__(self):
            self.payloads = []

        async def quote(self, payload):
            self.payloads.append(payload)
            return {"success": True, "zipcode": payload["zipcode"], "options": []}

    resource = RecordingResource()
    monkeypatch.setattr(main, "_shipping_resource", lambda: resource)
    api = TestClient(main.app)
    headers = {"Authorization": "Bearer adapter-token"}
    body = {
        "zipcode": "19900-000",
        "products": [{"product_id": 803, "price": "10.00", "quantity": 1}],
    }

    result = api.post("/internal/shippings/quote", json=body, headers=headers)
    assert result.status_code == 200
    assert resource.payloads[0]["zipcode"] == "19900000"
    assert api.post(
        "/internal/shippings/quote",
        json={**body, "zipcode": "1990"},
        headers=headers,
    ).status_code == 422
    assert api.post(
        "/internal/shippings/quote",
        json={**body, "products": [{**body["products"][0], "quantity": 0}]},
        headers=headers,
    ).status_code == 422
    assert api.post(
        "/internal/shippings/quote",
        json={**body, "products": [{"price": "10.00", "quantity": 1}]},
        headers=headers,
    ).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 500])
async def test_shipping_quote_preserves_tray_http_errors(status):
    upstream_calls = 0

    async def handler(request):
        nonlocal upstream_calls
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        upstream_calls += 1
        return response(
            request,
            {"code": status, "name": "Tray Error", "message": "invalid request"},
            status,
        )

    with pytest.raises(TrayAPIError) as error:
        await ShippingResource(client(handler)).quote(
            {
                "zipcode": "19900000",
                "products": [
                    {
                        "product_id": 803,
                        "price": Decimal("10.00"),
                        "quantity": 1,
                    }
                ],
            }
        )
    assert error.value.status_code == status
    assert upstream_calls == (2 if status == 401 else 1)


@pytest.mark.asyncio
async def test_shipping_methods_forwards_status_and_normalizes_fields():
    requests = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        requests.append(request)
        return response(
            request,
            {
                "Shippings": [
                    {
                        "Shipping": {
                            "id": "1",
                            "cod": "PAC",
                            "name": "PAC",
                            "identifier": "pac",
                            "display_name": "PAC Tray",
                            "status": "1",
                            "gateway": "tray",
                            "ignored": "value",
                        }
                    }
                ]
            },
        )

    result = await ShippingResource(client(handler)).methods("1")
    assert requests[0].url.path == "/web_api/shippings/"
    assert requests[0].url.params["status"] == "1"
    assert result["methods"] == [
        {
            "id": "1",
            "cod": "PAC",
            "name": "PAC",
            "identifier": "pac",
            "display_name": "PAC Tray",
            "status": "1",
            "gateway": "tray",
        }
    ]
