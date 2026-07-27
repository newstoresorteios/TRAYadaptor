import json
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.exceptions import TrayAPIError, TrayConnectionError
from app.normalizers.order import normalize_order, normalize_order_complete
from app.resources.orders import DEFAULT_ORDER_POINT_SALE, OrderResource
from app.tray_auth import TrayAuth
from app.tray_client import TrayClient


SESSION_ID = "order-session-123"


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


def order_payload(*, variant=False, multiple=False):
    products = [
        {
            "product_id": 803,
            "price": Decimal("4699.99"),
            "original_price": Decimal("4699.99"),
            "quantity": 1,
        }
    ]
    if variant:
        products[0]["variant_id"] = 123
    if multiple:
        products.append(
            {
                "product_id": 804,
                "variant_id": 124,
                "price": Decimal("100.00"),
                "original_price": Decimal("120.00"),
                "quantity": 2,
            }
        )
    return {
        "session_id": SESSION_ID,
        "shipping": {
            "shipping_id": 1,
            "quotation_id": "1",
            "name": "PAC Tray",
            "value": Decimal("35.10"),
            "min_period": 3,
            "max_period": 8,
        },
        "payment": {"method_id": "10545", "name": "Pix factual"},
        "customer": {
            "type": "0",
            "name": "Nome",
            "cpf": "00000000000",
            "email": "email@example.com",
            "phone": "14999999999",
        },
        "address": {
            "address": "Rua Teste",
            "zip_code": "19900000",
            "number": "123",
            "neighborhood": "Centro",
            "city": "Ourinhos",
            "state": "SP",
            "country": "BRA",
            "type": "1",
        },
        "products": products,
    }


@pytest.mark.parametrize(
    ("status", "group"),
    [
        ("AGUARDANDO PAGAMENTO", "awaiting_payment"),
        ("AGUARDANDO VINDI", "awaiting_payment"),
        ("A ENVIAR", "awaiting_shipment"),
        ("A ENVIAR VINDI", "awaiting_shipment"),
        ("ENVIADO", "shipped"),
        ("FINALIZADO", "completed"),
        ("CANCELADO", "cancelled"),
    ],
)
def test_order_status_preserves_original_and_adds_technical_group(status, group):
    result = normalize_order({"Order": {"status": status}})
    assert result == {"status": status, "status_group": group}


@pytest.mark.asyncio
async def test_order_create_wraps_customer_address_products_and_omits_optionals():
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
            {"message": "Created", "id": "123", "code": 201},
            201,
        )

    payload = order_payload()
    payload["products"][0]["variant_id"] = "0"
    result = await OrderResource(client(handler)).create(payload)
    tray_payload = json.loads(requests[0].content)
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/web_api/orders"
    assert tray_payload == {
        "Order": {
            "point_sale": DEFAULT_ORDER_POINT_SALE,
            "session_id": SESSION_ID,
            "shipment": "PAC Tray",
            "shipment_value": "35.10",
            "payment_form": "Pix factual",
            "Customer": {
                "type": "0",
                "name": "Nome",
                "cpf": "00000000000",
                "email": "email@example.com",
                "phone": "14999999999",
                "CustomerAddress": [
                    {
                        "address": "Rua Teste",
                        "zip_code": "19900000",
                        "number": "123",
                        "neighborhood": "Centro",
                        "city": "Ourinhos",
                        "state": "SP",
                        "country": "BRA",
                        "type": "1",
                    }
                ],
            },
            "ProductsSold": [
                {
                    "product_id": 803,
                    "price": "4699.99",
                    "original_price": "4699.99",
                    "quantity": 1,
                }
            ],
        }
    }
    assert "variant_id" not in tray_payload["Order"]["ProductsSold"][0]
    assert "rg" not in tray_payload["Order"]["Customer"]
    assert "gender" not in tray_payload["Order"]["Customer"]
    assert "complement" not in tray_payload["Order"]["Customer"]["CustomerAddress"][0]
    assert result == {
        "success": True,
        "order_id": 123,
        "code": 201,
        "message": "Created",
    }


@pytest.mark.asyncio
async def test_order_create_preserves_variant_and_multiple_product_indices():
    sent = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        sent.append(json.loads(request.content))
        return response(request, {"message": "Created", "id": "99", "code": 201}, 201)

    await OrderResource(client(handler)).create(
        order_payload(variant=True, multiple=True)
    )
    products = sent[0]["Order"]["ProductsSold"]
    assert products[0]["variant_id"] == 123
    assert products[1] == {
        "product_id": 804,
        "variant_id": 124,
        "price": "100.00",
        "original_price": "120.00",
        "quantity": 2,
    }


def test_order_route_normalizes_customer_and_address_and_omits_blank_optional(
    monkeypatch,
):
    configure(monkeypatch)

    class RecordingResource:
        def __init__(self):
            self.payload = None

        async def create(self, payload):
            self.payload = payload
            return {"success": True, "order_id": 1, "code": 201, "message": "Created"}

    resource = RecordingResource()
    monkeypatch.setattr(main, "_order_resource", lambda: resource)
    api = TestClient(main.app)
    headers = {"Authorization": "Bearer adapter-token"}
    body = order_payload()
    body["shipping"]["quotation_id"] = None
    body["shipping"]["value"] = "35.10"
    body["products"][0]["variant_id"] = "0"
    for product in body["products"]:
        product["price"] = str(product["price"])
        product["original_price"] = str(product["original_price"])
    body["customer"].update(
        {"cpf": "000.000.000-00", "phone": "(14) 99999-9999", "rg": "", "gender": ""}
    )
    body["address"].update(
        {"zip_code": "19900-000", "state": "sp", "country": "br", "complement": ""}
    )

    result = api.post("/internal/orders", json=body, headers=headers)
    assert result.status_code == 200
    assert resource.payload["customer"]["cpf"] == "00000000000"
    assert resource.payload["customer"]["phone"] == "14999999999"
    assert "rg" not in resource.payload["customer"]
    assert "gender" not in resource.payload["customer"]
    assert resource.payload["address"]["zip_code"] == "19900000"
    assert resource.payload["address"]["state"] == "SP"
    assert resource.payload["address"]["country"] == "BRA"
    assert "complement" not in resource.payload["address"]
    assert "quotation_id" not in resource.payload["shipping"]
    assert "variant_id" not in resource.payload["products"][0]

    missing_original_price = json.loads(json.dumps(body))
    missing_original_price["products"][0].pop("original_price")
    invalid = api.post(
        "/internal/orders",
        json=missing_original_price,
        headers=headers,
    )
    assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_order_400_is_not_retried_and_keeps_safe_diagnostics():
    posts = 0

    async def handler(request):
        nonlocal posts
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        posts += 1
        return response(
            request,
            {
                "code": 400,
                "name": "Bad Request",
                "type": "validation",
                "field": "ProductsSold",
                "message": "invalid products",
                "causes": [{"field": "quantity", "message": "invalid"}],
                "access_token": "SECRET",
            },
            400,
        )

    with pytest.raises(TrayAPIError) as error:
        await OrderResource(client(handler)).create(order_payload())
    assert posts == 1
    assert error.value.status_code == 400
    assert error.value.diagnostics["error_name"] == "Bad Request"
    assert error.value.diagnostics["error_causes"] == [
        {"field": "quantity", "message": "invalid"}
    ]


@pytest.mark.asyncio
async def test_timeout_reconciles_by_session_and_does_not_repeat_found_order():
    posts = 0
    gets = 0

    async def handler(request):
        nonlocal posts, gets
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        if request.method == "GET":
            gets += 1
            assert request.url.params["session_id"] == SESSION_ID
            return response(
                request,
                {
                    "Orders": [
                        {
                            "Order": {
                                "id": "123",
                                "session_id": SESSION_ID,
                                "status": "AGUARDANDO VINDI",
                            }
                        }
                    ]
                },
            )
        posts += 1
        raise httpx.ReadTimeout("timed out", request=request)

    result = await OrderResource(client(handler)).create(order_payload())
    assert result["order_id"] == 123
    assert result["reconciled"] is True
    assert result["order"]["status_group"] == "awaiting_payment"
    assert posts == 1
    assert gets == 1


@pytest.mark.asyncio
async def test_timeout_without_order_retries_post_at_most_once():
    posts = 0

    async def handler(request):
        nonlocal posts
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        if request.method == "GET":
            return response(request, {"Orders": []})
        posts += 1
        if posts == 1:
            raise httpx.ConnectError("reset", request=request)
        return response(request, {"message": "Created", "id": "124", "code": 201}, 201)

    result = await OrderResource(client(handler)).create(order_payload())
    assert result["order_id"] == 124
    assert posts == 2


@pytest.mark.asyncio
async def test_two_ambiguous_responses_stop_after_two_posts():
    posts = 0
    gets = 0

    async def handler(request):
        nonlocal posts, gets
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        if request.method == "GET":
            gets += 1
            return response(request, {"Orders": []})
        posts += 1
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(TrayConnectionError):
        await OrderResource(client(handler)).create(order_payload())
    assert posts == 2
    assert gets == 2


@pytest.mark.asyncio
async def test_order_401_refreshes_reconciles_and_retries_only_once():
    posts = 0
    refreshes = 0

    async def handler(request):
        nonlocal posts, refreshes
        if request.url.path.endswith("/auth"):
            if request.method == "GET":
                refreshes += 1
            token = "new" if request.method == "GET" else "old"
            return response(
                request,
                {
                    "access_token": token,
                    "refresh_token": "r",
                    "store_id": "687890",
                },
            )
        if request.method == "GET":
            return response(request, {"Orders": []})
        posts += 1
        if posts == 1:
            return response(request, {"code": 401, "message": "Unauthorized"}, 401)
        assert request.url.params["access_token"] == "new"
        return response(request, {"message": "Created", "id": "125", "code": 201}, 201)

    result = await OrderResource(client(handler)).create(order_payload())
    assert result["order_id"] == 125
    assert posts == 2
    assert refreshes == 1


@pytest.mark.asyncio
async def test_order_list_detail_and_session_filter_normalization():
    requests = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        requests.append(request)
        order = {
            "Order": {
                "id": "123",
                "status": "A ENVIAR VINDI",
                "customer_id": "10",
                "shipment": "PAC",
                "shipment_value": "35.10",
                "payment_method": "Pix factual",
                "payment_method_id": "10545",
                "session_id": SESSION_ID,
                "total": "4735.09",
                "estimated_delivery_date": "2026-08-03",
                "sending_code": "AB123",
                "sending_date": "2026-07-26",
                "tracking_url": "https://tracking.test/AB123",
                "has_payment": "1",
                "has_shipment": "0",
                "has_invoice": False,
            }
        }
        return response(request, {"Orders": [order]} if request.url.path.endswith("/orders") else order)

    resource = OrderResource(client(handler))
    listed = await resource.list({"session_id": SESSION_ID, "limit": 20})
    detail = await resource.get(123)
    assert requests[0].url.params["session_id"] == SESSION_ID
    assert listed["orders"][0]["status"] == "A ENVIAR VINDI"
    assert listed["orders"][0]["status_group"] == "awaiting_shipment"
    assert detail["order"]["id"] == 123
    assert detail["order"]["has_payment"] is True
    assert detail["order"]["has_shipment"] is False
    assert detail["order"]["tracking_url"] == "https://tracking.test/AB123"


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback_status", [404, 405])
async def test_order_complete_uses_full_then_legacy_fallback_only_for_404_405(
    fallback_status,
):
    paths = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        paths.append(request.url.path)
        if request.url.path.endswith("/full"):
            return response(request, {"message": "not supported"}, fallback_status)
        return response(
            request,
            {
                "Order": {
                    "id": "123",
                    "status": "ENVIADO",
                    "total": "100.00",
                    "ProductsSold": [
                        {
                            "ProductSold": {
                                "product_id": "803",
                                "variant_id": "123",
                                "name": "Produto",
                                "quantity": "1",
                                "price": "90.00",
                                "original_price": "100.00",
                            }
                        }
                    ],
                }
            },
        )

    result = await OrderResource(client(handler)).complete(123)
    assert paths == [
        "/web_api/orders/123/full",
        "/web_api/orders/123/complete",
    ]
    assert result["order"]["status_group"] == "shipped"
    assert result["products"][0]["variant_id"] == 123


@pytest.mark.asyncio
async def test_order_complete_uses_full_as_primary_without_legacy_request():
    paths = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        paths.append(request.url.path)
        return response(
            request,
            {"Order": {"id": "123", "status": "A ENVIAR", "total": "100.00"}},
        )

    result = await OrderResource(client(handler)).complete(123)
    assert paths == ["/web_api/orders/123/full"]
    assert result["order"]["status_group"] == "awaiting_shipment"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 500])
async def test_order_complete_does_not_fallback_for_other_errors(status):
    paths = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        paths.append(request.url.path)
        return response(request, {"message": "error"}, status)

    with pytest.raises(TrayAPIError):
        await OrderResource(client(handler)).complete(123)
    assert all(path.endswith("/full") for path in paths)


def test_complete_order_normalizer_preserves_nested_facts_only():
    result = normalize_order_complete(
        {
            "Order": {
                "id": "123",
                "status": "FINALIZADO",
                "total": "100.00",
                "partial_total": "95.00",
                "discount": "5.00",
                "taxes": "0.00",
                "payment_method_id": "10",
                "payment_method": "Método factual",
                "installment": "1",
                "payment_date": "2026-07-26",
                "has_payment": "1",
                "shipment": "PAC",
                "shipment_value": "10.00",
                "shipment_integrator": "tray",
                "id_quotation": "9",
                "estimated_delivery_date": "2026-08-03",
                "has_shipment": "1",
                "sending_code": "AB123",
                "sending_date": "2026-07-26",
                "tracking_url": "https://tracking.test/AB123",
                "Customer": {
                    "id": "7",
                    "name": "Nome",
                    "email": "email@example.com",
                    "phone": "14999999999",
                    "cellphone": "14999999999",
                    "cpf": "must-not-be-returned",
                    "CustomerAddress": [
                        {
                            "CustomerAddress": {
                                "address": "Rua",
                                "zip_code": "19900000",
                                "number": "1",
                                "city": "Ourinhos",
                                "state": "SP",
                            }
                        }
                    ],
                },
                "ProductsSold": [
                    {
                        "ProductSold": {
                            "product_id": "803",
                            "variant_id": "0",
                            "name": "Produto",
                            "quantity": "1",
                            "price": "95.00",
                            "original_price": "100.00",
                            "secret": "ignored",
                        }
                    }
                ],
                "access_token": "ignored",
            }
        }
    )
    assert result["order"]["status_group"] == "completed"
    assert result["payment"]["has_payment"] is True
    assert result["shipping"]["tracking_url"] == "https://tracking.test/AB123"
    assert result["customer"] == {
        "id": 7,
        "name": "Nome",
        "email": "email@example.com",
        "phone": "14999999999",
        "cellphone": "14999999999",
    }
    assert result["address"]["zip_code"] == "19900000"
    assert "variant_id" not in result["products"][0]
    assert "access_token" not in json.dumps(result)


@pytest.mark.asyncio
async def test_shipping_update_sends_only_received_fields():
    requests = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        requests.append(request)
        return response(request, {"message": "Updated", "id": "123", "code": 200})

    result = await OrderResource(client(handler)).update_shipping(
        123,
        {
            "status_id": 123,
            "shipment": "PAC Tray",
            "shipment_value": Decimal("35.10"),
            "sending_code": "AB123456789BR",
            "sending_date": "2026-07-26",
            "tracking_url": "https://tracking.test/AB123",
        },
    )
    assert json.loads(requests[0].content) == {
        "Order": {
            "status_id": 123,
            "shipment": "PAC Tray",
            "shipment_value": "35.10",
            "sending_code": "AB123456789BR",
            "sending_date": "2026-07-26",
            "tracking_url": "https://tracking.test/AB123",
        }
    }
    assert result["order_id"] == 123


def test_shipping_update_route_rejects_empty_or_unrelated_fields(monkeypatch):
    configure(monkeypatch)
    api = TestClient(main.app)
    headers = {"Authorization": "Bearer adapter-token"}
    assert api.put(
        "/internal/orders/123/shipping",
        json={},
        headers=headers,
    ).status_code == 422
    assert api.put(
        "/internal/orders/123/shipping",
        json={"total": "1.00"},
        headers=headers,
    ).status_code == 422
