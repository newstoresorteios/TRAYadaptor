import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import main
from app.config import Settings
from app.normalizers.order import (
    normalize_order_complete,
    normalize_order_payment,
)
from app.resources.orders import OrderResource
from app.schemas.orders import OrderPayment
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


def test_pix_uses_official_order_url_and_keeps_type_factual():
    result = normalize_order_complete(
        {
            "Order": {
                "id": "123",
                "payment_method_id": "10545",
                "payment_method": "Pix - Vindi",
                "payment_method_type": "pix",
                "has_payment": "0",
                "payment_date": "",
                "installment": "",
                "urls": {
                    "payment": "https://store.example/pagamento",
                },
            }
        }
    )

    assert result["payment"] == {
        "method_id": "10545",
        "method": "Pix - Vindi",
        "type": "pix",
        "has_payment": False,
        "payment_date": None,
        "installment": None,
        "payment_url": "https://store.example/pagamento",
        "transaction_urls": [],
        "records": [],
    }
    assert result["payment_capability"] == {
        "method_selected": True,
        "payment_url_available": True,
        "native_pix_available": False,
        "native_boleto_available": False,
        "native_card_available": False,
    }


def test_order_transaction_url_is_fallback_and_duplicates_are_removed():
    payment = normalize_order_payment(
        {
            "Order": {
                "OrderTransactions": [
                    {"url_payment": "https://store.example/transaction"},
                    {"url_payment": "https://store.example/transaction"},
                ]
            }
        }
    )

    assert payment["payment_url"] == "https://store.example/transaction"
    assert payment["transaction_urls"] == [
        "https://store.example/transaction"
    ]


def test_order_url_has_priority_but_transactions_remain_available():
    payment = normalize_order_payment(
        {
            "Order": {
                "urls": {"payment": "https://store.example/order"},
                "OrderTransactions": [
                    {"url_payment": "https://store.example/transaction"}
                ],
            }
        }
    )

    assert payment["payment_url"] == "https://store.example/order"
    assert payment["transaction_urls"] == [
        "https://store.example/transaction"
    ]


def test_transaction_urls_prefer_equivalent_https_without_rewriting_others():
    payment = normalize_order_payment(
        {
            "Order": {
                "OrderTransactions": [
                    {"url_payment": "http://store.example/payment?id=1"},
                    {"url_payment": "https://store.example/payment?id=1"},
                    {"url_payment": "http://store.example/other?id=2"},
                ]
            }
        }
    )

    assert payment["transaction_urls"] == [
        "https://store.example/payment?id=1",
        "http://store.example/other?id=2",
    ]
    assert payment["payment_url"] == "https://store.example/payment?id=1"


@pytest.mark.parametrize(
    "invalid_url",
    [
        None,
        "",
        "javascript:alert(1)",
        "https://",
        "https://store.example/value with space",
        "https://user:password@store.example/payment",
    ],
)
def test_invalid_or_missing_urls_never_become_payment_url(invalid_url):
    payment = normalize_order_payment(
        {
            "Order": {
                "urls": {"payment": invalid_url},
                "OrderTransactions": [{"url_payment": invalid_url}],
            }
        }
    )
    assert payment["payment_url"] is None
    assert payment["transaction_urls"] == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", True),
        ("0", False),
        (1, True),
        (0, False),
        ("unknown", None),
        (None, None),
    ],
)
def test_has_payment_is_technical_and_unknown_is_not_true(raw, expected):
    payment = normalize_order_payment({"Order": {"has_payment": raw}})
    assert payment["has_payment"] is expected


@pytest.mark.parametrize(
    "raw",
    ["", "0000-00-00", "0000-00-00 00:00:00", "invalid-date", None],
)
def test_invalid_payment_dates_are_absent(raw):
    payment = normalize_order_payment({"Order": {"payment_date": raw}})
    assert payment["payment_date"] is None


def test_payment_records_keep_only_useful_fields():
    payment = normalize_order_payment(
        {
            "Order": {
                "Payment": [
                    {
                        "id": "1",
                        "order_id": "123",
                        "payment_method_id": "10",
                        "method": "Método A",
                        "payment_place": "interno",
                        "value": "50.00",
                        "date": "2026-07-26",
                        "note": "não expor",
                        "created": "2026-07-26 10:00:00",
                        "modified": "2026-07-26 11:00:00",
                    },
                    {
                        "Payment": {
                            "id": "2",
                            "payment_method_id": "11",
                            "method": "Método B",
                            "value": "25.00",
                            "date": "0000-00-00",
                            "created": "",
                            "modified": None,
                        }
                    },
                ]
            }
        }
    )

    assert payment["records"] == [
        {
            "id": "1",
            "payment_method_id": "10",
            "method": "Método A",
            "value": "50.00",
            "date": "2026-07-26",
            "created": "2026-07-26 10:00:00",
            "modified": "2026-07-26 11:00:00",
        },
        {
            "id": "2",
            "payment_method_id": "11",
            "method": "Método B",
            "value": "25.00",
            "date": None,
            "created": None,
            "modified": None,
        },
    ]
    assert "note" not in payment["records"][0]
    assert "payment_place" not in payment["records"][0]


def test_payments_notification_is_never_a_customer_payment_url():
    payment = normalize_order_payment(
        {
            "Order": {
                "access_code": "must-not-be-exposed",
                "payments_notification": {
                    "notification": "https://callbacks.example/payment"
                }
            }
        }
    )
    assert payment["payment_url"] is None
    assert payment["transaction_urls"] == []
    assert "access_code" not in payment


def test_method_name_does_not_infer_type_or_native_capability():
    result = normalize_order_complete(
        {
            "Order": {
                "payment_method_id": "10",
                "payment_method": "Pix - nome não é capability",
            }
        }
    )
    assert result["payment"]["type"] is None
    assert result["payment_capability"]["native_pix_available"] is False


def test_payment_method_type_accepts_unknown_factual_values():
    payment = normalize_order_payment(
        {"Order": {"payment_method_type": "future_gateway_type"}}
    )
    assert payment["type"] == "future_gateway_type"


@pytest.mark.asyncio
async def test_order_payment_lookup_reuses_complete_once_and_never_logs_url(
    caplog,
):
    caplog.set_level("INFO", logger="uvicorn.error.tray.order")
    upstream_paths = []
    official_url = "https://store.example/payment?token=SECRET&hash=VALUE"

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        upstream_paths.append(request.url.path)
        return response(
            request,
            {
                "Order": {
                    "id": "123",
                    "payment_method_id": "10545",
                    "payment_method_type": "pix",
                    "has_payment": "0",
                    "access_code": "must-not-be-logged",
                    "urls": {"payment": official_url},
                }
            },
        )

    result = await OrderResource(client(handler)).payment(123)

    assert upstream_paths == ["/web_api/orders/123/full"]
    assert result["order_id"] == 123
    assert result["payment"]["payment_url"] == official_url
    assert "[tray.order.payment.lookup]" in caplog.text
    assert "[tray.order.payment.normalized]" in caplog.text
    assert "payment_url_present=true" in caplog.text
    assert official_url not in caplog.text
    assert "SECRET" not in caplog.text
    assert "must-not-be-logged" not in caplog.text
    assert "payment_method_id" not in caplog.text
    assert "transaction_urls_count" not in caplog.text
    assert "payment_records_count" not in caplog.text


def test_internal_order_payment_endpoint_is_get_only_and_requires_bearer(
    monkeypatch,
):
    configure(monkeypatch)

    class FakeOrderResource:
        async def payment(self, order_id):
            return {
                "success": True,
                "order_id": order_id,
                "payment": {
                    "method_id": None,
                    "method": None,
                    "type": None,
                    "has_payment": None,
                    "payment_date": None,
                    "installment": None,
                    "payment_url": None,
                    "transaction_urls": [],
                    "records": [],
                },
                "payment_capability": {
                    "method_selected": False,
                    "payment_url_available": False,
                    "native_pix_available": False,
                    "native_boleto_available": False,
                    "native_card_available": False,
                },
            }

    monkeypatch.setattr(main, "_order_resource", lambda: FakeOrderResource())
    api = TestClient(main.app)
    path = "/internal/orders/123/payment"
    headers = {"Authorization": "Bearer adapter-token"}

    assert api.get(path).status_code == 401
    response_value = api.get(path, headers=headers)
    assert response_value.status_code == 200
    assert response_value.json()["order_id"] == 123
    assert api.post(path, json={}, headers=headers).status_code == 405
    routes = [
        route
        for route in main.app.routes
        if getattr(route, "path", "") == "/internal/orders/{order_id}/payment"
    ]
    assert len(routes) == 1
    assert routes[0].methods == {"GET"}


def test_order_payment_selection_schema_rejects_card_data():
    with pytest.raises(ValidationError):
        OrderPayment.model_validate(
            {
                "method_id": "10",
                "name": "Cartão hospedado",
                "card_number": "4111111111111111",
                "cvv": "123",
            }
        )
