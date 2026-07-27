import json
import logging
from decimal import Decimal

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import Settings
from app.exceptions import TrayAPIError, TrayConnectionError, TrayValidationError
from app.resources.carts import CartResource
from app.tray_auth import TrayAuth
from app.tray_client import TrayClient


SESSION_32 = "s" * 32
SESSION_26 = "s" * 26
SESSION_18 = "s" * 18


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
        "TRAY_API_BASE": "https://tray.test/web_api", "TRAY_CODE": "code",
        "TRAY_CONSUMER_KEY": "key", "TRAY_CONSUMER_SECRET": "secret",
        "TRAY_STORE_CODE": "687890", "TRAY_ADAPTER_TOKEN": "adapter-token",
    }.items():
        monkeypatch.setenv(key, value)


def test_cart_logger_uses_uvicorn_info_channel():
    cart_logger = logging.getLogger("uvicorn.error.tray.cart")

    assert cart_logger.getEffectiveLevel() == logging.INFO
    assert cart_logger.name.startswith("uvicorn.error.")


@pytest.mark.asyncio
async def test_cart_create_json_transport_matrix_and_201_normalization(caplog):
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")
    requests = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        if request.url.path.endswith("/products/variants/900"):
            return response(request, {
                "Variant": {"id": "900", "product_id": "123", "price": "6399.99"}
            })
        requests.append(request)
        return response(request, {"id": "77", "session_id": SESSION_32, "cart_url": "https://store.test/cart", "message": "Created", "code": 201}, 201)

    resource = CartResource(client(handler))
    first = await resource.create({"product_id": "123", "variant_id": None, "quantity": 1, "price": Decimal("6399.99"), "session_id": SESSION_32})
    await resource.create({"product_id": "123", "variant_id": "900", "quantity": 1, "price": Decimal("6399.99"), "session_id": SESSION_32})
    await resource.create({"product_id": "456", "variant_id": "0", "quantity": 1, "price": Decimal("100.00"), "session_id": SESSION_32})

    assert all(request.method == "POST" for request in requests)
    assert all(request.url.path == "/web_api/carts" for request in requests)
    assert all(set(request.url.params.keys()) == {"access_token"} for request in requests)
    assert all(
        request.headers["content-type"] == "application/json"
        for request in requests
    )
    assert json.loads(requests[0].content) == {
        "Cart": {
            "session_id": SESSION_32,
            "product_id": 123,
            "quantity": 1,
        }
    }
    assert json.loads(requests[1].content) == {
        "Cart": {
            "session_id": SESSION_32,
            "product_id": 123,
            "variant_id": 900,
            "quantity": 1,
        }
    }
    assert json.loads(requests[2].content) == {
        "Cart": {
            "session_id": SESSION_32,
            "product_id": 456,
            "quantity": 1,
        }
    }
    assert "price" not in json.loads(requests[0].content)["Cart"]
    assert "price" not in json.loads(requests[1].content)["Cart"]
    assert first == {"success": True, "cart": {"cart_id": "77", "session_id": SESSION_32, "cart_url": "https://store.test/cart", "message": "Created", "code": 201}}
    assert "[tray.cart.request]" in caplog.text
    assert "status_code=201" in caplog.text
    assert "response_is_json=true" in caplog.text
    assert "https://store.test/cart" not in caplog.text


@pytest.mark.asyncio
async def test_product_803_simple_cart_omits_variant_and_logs_json_types(caplog):
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")
    cart_requests = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(request, {
                "access_token": "a",
                "refresh_token": "r",
                "store_id": "687890",
            })
        cart_requests.append(request)
        return response(request, {
            "message": "Created",
            "id": "8031",
            "session_id": SESSION_26,
            "cart_url": "https://store.test/cart",
            "code": 201,
        }, 201)

    result = await CartResource(client(handler)).create({
        "product_id": "803",
        "variant_id": None,
        "quantity": 1,
        "price": Decimal("4699.99"),
        "session_id": SESSION_26,
    })

    tray_payload = json.loads(cart_requests[0].content)
    assert tray_payload == {
        "Cart": {
            "session_id": SESSION_26,
            "product_id": 803,
            "quantity": 1,
        }
    }
    assert "price" not in tray_payload["Cart"]
    assert result["cart"]["cart_id"] == "8031"
    assert "product_id=803" in caplog.text
    assert "transport=json wrapper=Cart" in caplog.text
    assert "product_id=803 product_id_type=int" in caplog.text
    assert "variant_present=false variant_id_type=none" in caplog.text
    assert "quantity=1 quantity_type=int" in caplog.text
    assert "price_forwarded=false" in caplog.text
    assert "session_length=26" in caplog.text
    assert "session_hash=" in caplog.text
    assert SESSION_26 not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id", [SESSION_18, SESSION_26, SESSION_32])
async def test_cart_accepts_documented_session_lengths(session_id):
    cart_requests = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(request, {
                "access_token": "a",
                "refresh_token": "r",
                "store_id": "687890",
            })
        cart_requests.append(request)
        return response(request, {
            "id": "1",
            "session_id": session_id,
            "code": 201,
        }, 201)

    await CartResource(client(handler)).create({
        "product_id": "803",
        "quantity": 1,
        "price": Decimal("4699.99"),
        "session_id": session_id,
    })

    cart = json.loads(cart_requests[0].content)["Cart"]
    assert cart["session_id"] == session_id
    assert "variant_id" not in cart


@pytest.mark.asyncio
async def test_cart_resource_passes_json_and_never_passes_form_data():
    class RecordingClient:
        def __init__(self):
            self.calls = []

        async def request(self, *args, **kwargs):
            self.calls.append((args, kwargs))
            return {"message": "Created", "code": 201}

    recording_client = RecordingClient()
    await CartResource(recording_client).create({
        "product_id": "803",
        "quantity": 1,
        "price": Decimal("4699.99"),
        "session_id": "session123",
    })

    args, kwargs = recording_client.calls[0]
    assert args == ("POST", "/carts")
    assert kwargs["json"] == {
        "Cart": {
            "session_id": "session123",
            "product_id": 803,
            "quantity": 1,
        }
    }
    assert "price" not in kwargs["json"]["Cart"]
    assert "data" not in kwargs
    assert kwargs["follow_redirects"] is False
    assert kwargs["reject_redirects"] is True


@pytest.mark.asyncio
async def test_cart_variant_must_belong_to_requested_product():
    post_calls = 0

    async def handler(request):
        nonlocal post_calls
        if request.url.path.endswith("/auth"):
            return response(request, {
                "access_token": "a",
                "refresh_token": "r",
                "store_id": "687890",
            })
        if request.method == "GET":
            return response(request, {
                "Variant": {"id": "9001", "product_id": "999"}
            })
        post_calls += 1
        return response(request, {"code": 201}, 201)

    with pytest.raises(
        TrayValidationError, match="cart_variant_product_mismatch"
    ):
        await CartResource(client(handler)).create({
            "product_id": "803",
            "variant_id": "9001",
            "quantity": 1,
            "price": Decimal("4699.99"),
            "session_id": "session123",
        })

    assert post_calls == 0


@pytest.mark.asyncio
async def test_cart_create_accepts_upstream_200_success():
    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        return response(
            request,
            {
                "id": "78",
                "session_id": "SESSION-200",
                "cart_url": "https://store.test/cart?session=SESSION-200",
                "message": "Created",
                "code": 200,
            },
            200,
        )

    result = await CartResource(client(handler)).create({
        "product_id": "123",
        "quantity": 1,
        "price": Decimal("50.00"),
        "session_id": SESSION_32,
    })

    assert result == {
        "success": True,
        "cart": {
            "cart_id": "78",
            "session_id": "SESSION-200",
            "cart_url": "https://store.test/cart?session=SESSION-200",
            "message": "Created",
            "code": 200,
        },
    }


@pytest.mark.asyncio
async def test_cart_read_uses_session_path_and_normalizes_useful_fields():
    paths = []

    async def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        return response(request, {"Cart": {"session_id": "SESSION", "product_id": "123", "product_name": "Produto", "variant_id": "900", "quantity": "2", "price": "49.90"}})

    result = await CartResource(client(handler)).get("SESSION")
    assert paths[-1] == "/web_api/carts/SESSION"
    assert result["cart"] == {"session_id": "SESSION", "product_id": "123", "product_name": "Produto", "variant_id": 900, "quantity": 2, "price": 49.9}


@pytest.mark.asyncio
async def test_cart_complete_normalizes_multiple_items_prices_quantities_and_images():
    paths = []

    async def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        return response(request, {
            "Cart": {
                "session_id": "SESSION",
                "sub_total": "149.80",
                "total": "149.80",
                "Products": [
                    {
                        "id": "123",
                        "cart_id": "c1",
                        "name": "Produto A",
                        "quantity": "2",
                        "price": "49.90",
                        "stock": "8",
                        "available": "1",
                        "ProductImage": [{"https": "https://tray.test/a.jpg"}],
                    },
                    {
                        "id": "456",
                        "cart_id": "c2",
                        "name": "Produto B",
                        "variant_id": "123",
                        "quantity": "1",
                        "price": "50.00",
                        "stock": "3",
                        "ProductImage": [{"https": "https://tray.test/b.jpg"}],
                    },
                ],
            }
        })

    result = await CartResource(client(handler)).complete("SESSION")

    assert paths[-1] == "/web_api/carts/SESSION/complete"
    assert result["cart"]["sub_total"] == 149.8
    assert result["cart"]["total"] == 149.8
    assert result["cart"]["items"][0]["product_id"] == "123"
    assert result["cart"]["items"][0]["quantity"] == 2
    assert result["cart"]["items"][0]["price"] == 49.9
    assert result["cart"]["items"][0]["primary_image_url"] == "https://tray.test/a.jpg"
    assert result["cart"]["items"][1]["variant_id"] == 123
    assert len(result["cart"]["items"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_methods", "expected"),
    [
        (
            [
                {
                    "payment_method_id": "7",
                    "blocked": "1",
                    "max_plots": "6",
                }
            ],
            [
                {
                    "payment_method_id": "7",
                    "blocked": "1",
                    "max_plots": "6",
                }
            ],
        ),
        ([], []),
    ],
)
async def test_cart_complete_preserves_payment_methods_by_product(
    raw_methods,
    expected,
):
    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        return response(
            request,
            {
                "Cart": {
                    "session_id": "SESSION",
                    "Products": [
                        {
                            "id": "803",
                            "quantity": "1",
                            "price": "4699.99",
                            "PaymentMethodByProduct": raw_methods,
                        }
                    ],
                }
            },
        )

    result = await CartResource(client(handler)).complete("SESSION")

    assert result["cart"]["items"][0]["payment_methods"] == expected


@pytest.mark.asyncio
async def test_successive_cart_posts_reuse_the_same_required_session_id():
    payloads = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        payloads.append(json.loads(request.content))
        return response(
            request,
            {"id": str(len(payloads)), "session_id": SESSION_32, "code": 201},
            201,
        )

    resource = CartResource(client(handler))
    await resource.create({
        "product_id": "101",
        "quantity": 1,
        "price": Decimal("10.00"),
        "session_id": SESSION_32,
    })
    await resource.create({
        "product_id": "202",
        "quantity": 2,
        "price": Decimal("20.00"),
        "session_id": SESSION_32,
    })

    assert payloads == [
        {
            "Cart": {
                "session_id": SESSION_32,
                "product_id": 101,
                "quantity": 1,
            }
        },
        {
            "Cart": {
                "session_id": SESSION_32,
                "product_id": 202,
                "quantity": 2,
            }
        },
    ]


class FakeCartResource:
    def __init__(self):
        self.calls = []

    async def create(self, payload):
        self.calls.append(payload)
        return {"success": True, "cart": {"session_id": "SESSION"}}

    async def get(self, session_id):
        return {"success": True, "cart": {"session_id": session_id}}

    async def complete(self, session_id):
        return {"success": True, "cart": {"session_id": session_id, "items": []}}


def test_cart_routes_validate_quantity_price_and_internal_bearer(monkeypatch, caplog):
    configure(monkeypatch)
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")
    resource = FakeCartResource()
    monkeypatch.setattr(main, "_cart_resource", lambda: resource)
    api = TestClient(main.app)
    body = {"product_id": "123", "variant_id": "0", "quantity": 1, "price": "50.00", "session_id": SESSION_32}
    without_session = dict(body)
    without_session.pop("session_id")

    assert api.post("/internal/carts", json=body).status_code == 401
    assert api.post("/internal/carts", json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert api.get("/internal/carts/SESSION").status_code == 401
    assert api.get("/internal/carts/SESSION/complete").status_code == 401
    assert api.post("/internal/carts", json=without_session, headers={"Authorization": "Bearer adapter-token"}).status_code == 422
    assert api.post("/internal/carts", json={**body, "session_id": "x" * 33}, headers={"Authorization": "Bearer adapter-token"}).status_code == 422
    assert len(resource.calls) == 0
    assert api.post("/internal/carts", json=body, headers={"Authorization": "Bearer adapter-token"}).status_code == 200
    assert api.get("/internal/carts/SESSION", headers={"Authorization": "Bearer adapter-token"}).status_code == 200
    assert api.get("/internal/carts/SESSION/complete", headers={"Authorization": "Bearer adapter-token"}).status_code == 200
    assert api.post("/internal/carts", json={**body, "quantity": 0}, headers={"Authorization": "Bearer adapter-token"}).status_code == 422
    assert api.post("/internal/carts", json={**body, "price": "invalid"}, headers={"Authorization": "Bearer adapter-token"}).status_code == 422
    assert api.post("/internal/carts", json={**body, "product_id": "ABC"}, headers={"Authorization": "Bearer adapter-token"}).status_code == 422
    assert api.post("/internal/carts", json={**body, "variant_id": "ABC"}, headers={"Authorization": "Bearer adapter-token"}).status_code == 422
    assert api.post("/internal/carts", json={**body, "variant_id": "null"}, headers={"Authorization": "Bearer adapter-token"}).status_code == 422
    assert api.post("/internal/carts", json={**body, "session_id": "None"}, headers={"Authorization": "Bearer adapter-token"}).status_code == 422
    assert len(resource.calls) == 1
    assert resource.calls[0].get("variant_id") is None
    assert "stage=internal_validation" in caplog.text


@pytest.mark.asyncio
async def test_cart_resource_missing_session_stops_before_upstream():
    class RecordingClient:
        def __init__(self):
            self.calls = 0

        async def request(self, *args, **kwargs):
            self.calls += 1
            return {}

    recording_client = RecordingClient()
    with pytest.raises(TrayValidationError, match="cart_payload_invalid"):
        await CartResource(recording_client).create({
            "product_id": "123",
            "quantity": 1,
            "price": Decimal("50.00"),
        })

    assert recording_client.calls == 0


@pytest.mark.asyncio
async def test_cart_post_503_is_not_retried():
    cart_calls = 0

    async def handler(request):
        nonlocal cart_calls
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        cart_calls += 1
        return response(request, {"message": "Unavailable"}, 503)

    with pytest.raises(TrayAPIError) as error:
        await CartResource(client(handler)).create({"product_id": "123", "quantity": 1, "price": Decimal("50.00"), "session_id": SESSION_32})
    assert error.value.status_code == 503
    assert cart_calls == 1


@pytest.mark.asyncio
async def test_cart_401_refresh_reconciliation_prevents_duplicate(caplog):
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")
    cart_posts = 0
    refreshes = 0

    async def handler(request):
        nonlocal cart_posts, refreshes
        if request.url.path.endswith("/auth"):
            if request.method == "GET":
                refreshes += 1
                return response(request, {
                    "access_token": "new-token",
                    "refresh_token": "new-refresh",
                    "store_id": "687890",
                })
            return response(request, {
                "access_token": "old-token",
                "refresh_token": "old-refresh",
                "store_id": "687890",
            })
        if request.method == "POST":
            cart_posts += 1
            return response(request, {"code": 401, "message": "Unauthorized"}, 401)
        assert request.url.path == f"/web_api/carts/{SESSION_32}"
        assert request.url.params["access_token"] == "new-token"
        return response(request, {
            "Cart": {
                "session_id": SESSION_32,
                "Products": [{
                    "product_id": "123",
                    "variant_id": "0",
                    "quantity": "1",
                    "price": "50.00",
                }],
            }
        })

    result = await CartResource(client(handler)).create({
        "product_id": "123",
        "quantity": 1,
        "price": Decimal("50.00"),
        "session_id": SESSION_32,
    })

    assert result["success"] is True
    assert result["cart"]["items"][0]["product_id"] == "123"
    assert cart_posts == 1
    assert refreshes == 1
    assert "action=refresh_started" in caplog.text
    assert "status=product_already_present" in caplog.text
    assert "completed_without_retry" in caplog.text
    assert "old-token" not in caplog.text
    assert "new-token" not in caplog.text


@pytest.mark.asyncio
async def test_cart_401_retries_once_only_when_reconciliation_has_no_item(caplog):
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")
    cart_posts = 0

    async def handler(request):
        nonlocal cart_posts
        if request.url.path.endswith("/auth"):
            token = "new-token" if request.method == "GET" else "old-token"
            return response(request, {
                "access_token": token,
                "refresh_token": "refresh",
                "store_id": "687890",
            })
        if request.url.path.endswith("/products/variants/900"):
            return response(request, {
                "Variant": {"id": "900", "product_id": "123", "price": "50.00"}
            })
        if request.method == "GET":
            return response(request, {"Cart": {"session_id": SESSION_32, "Products": []}})
        cart_posts += 1
        if cart_posts == 1:
            return response(request, {"code": 401, "message": "Unauthorized"}, 401)
        assert request.url.params["access_token"] == "new-token"
        return response(request, {
            "id": "77",
            "session_id": SESSION_32,
            "message": "Created",
            "code": 201,
        }, 201)

    result = await CartResource(client(handler)).create({
        "product_id": "123",
        "variant_id": "900",
        "quantity": 2,
        "price": Decimal("50.00"),
        "session_id": SESSION_32,
    })

    assert result["cart"]["cart_id"] == "77"
    assert cart_posts == 2
    assert "status=product_not_found action=retry_once" in caplog.text
    assert "attempt=retry" in caplog.text
    assert "recovered=true" in caplog.text


@pytest.mark.asyncio
async def test_cart_401_second_post_failure_is_not_retried_again():
    cart_posts = 0

    async def handler(request):
        nonlocal cart_posts
        if request.url.path.endswith("/auth"):
            return response(request, {
                "access_token": "new" if request.method == "GET" else "old",
                "refresh_token": "refresh",
                "store_id": "687890",
            })
        if request.method == "GET":
            return response(request, {"Cart": {"Products": []}})
        cart_posts += 1
        return response(request, {"code": 401, "message": "Unauthorized"}, 401)

    with pytest.raises(TrayAPIError) as error:
        await CartResource(client(handler)).create({
            "product_id": "123",
            "quantity": 1,
            "price": Decimal("50.00"),
            "session_id": SESSION_32,
        })

    assert error.value.status_code == 401
    assert cart_posts == 2


def test_cart_upstream_400_is_normalized_with_safe_diagnostics(monkeypatch, caplog):
    configure(monkeypatch)
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")
    cart_calls = 0

    async def handler(request):
        nonlocal cart_calls
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        cart_calls += 1
        return response(
            request,
            {
                "code": 400,
                "name": "Bad Request",
                "message": "missing field: session_id",
                "url": "https://tray.test/carts/?access_token=SECRET",
                "access_token": "SECRET",
                "causes": [{"field": "variant_id", "message": "invalid"}],
            },
            400,
        )

    resource = CartResource(client(handler))
    monkeypatch.setattr(main, "_cart_resource", lambda: resource)
    api = TestClient(main.app)
    result = api.post("/internal/carts", json={"product_id": "123", "quantity": 1, "price": "50.00", "session_id": SESSION_32}, headers={"Authorization": "Bearer adapter-token"})
    assert result.status_code == 400
    assert result.json() == {
        "success": False,
        "error": "tray_api_error",
        "status_code": 400,
        "tray_error_code": 400,
        "tray_error_name": "Bad Request",
        "tray_error_type": None,
        "tray_error_field": None,
        "tray_error_fields": ["variant_id"],
        "tray_error_causes": [{"field": "variant_id", "message": "invalid"}],
        "tray_error_message": "missing field: session_id",
    }
    assert cart_calls == 1
    assert "stage=upstream_http" in caplog.text
    assert "upstream_status=400" in caplog.text
    assert "response_is_json=true" in caplog.text
    assert "content_type=application/json" in caplog.text
    assert "final_url_path=/web_api/carts" in caplog.text
    assert "redirect_count=0" in caplog.text
    assert "error_name=Bad Request" in caplog.text
    assert "error_fields=['variant_id']" in caplog.text
    assert "error_message=missing field: session_id" in caplog.text
    assert "SECRET" not in caplog.text
    assert "access_token" not in caplog.text
    assert "https://tray.test/carts/" not in caplog.text


def test_cart_upstream_non_json_400_preserves_safe_empty_diagnostics(
    monkeypatch, caplog
):
    configure(monkeypatch)
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(request, {
                "access_token": "a",
                "refresh_token": "r",
                "store_id": "687890",
            })
        return httpx.Response(
            400,
            text="upstream non-json diagnostic must not be exposed",
            request=request,
        )

    monkeypatch.setattr(
        main, "_cart_resource", lambda: CartResource(client(handler))
    )
    result = TestClient(main.app).post(
        "/internal/carts",
        json={
            "product_id": "803",
            "quantity": 1,
            "price": "4699.99",
            "session_id": SESSION_32,
        },
        headers={"Authorization": "Bearer adapter-token"},
    )

    assert result.status_code == 400
    assert result.json() == {
        "success": False,
        "error": "tray_api_error",
        "status_code": 400,
        "tray_error_code": None,
        "tray_error_name": None,
        "tray_error_type": None,
        "tray_error_field": None,
        "tray_error_fields": [],
        "tray_error_causes": [],
        "tray_error_message": None,
    }
    assert "response_is_json=false" in caplog.text
    assert "upstream non-json diagnostic" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("causes", "expected_causes", "expected_fields"),
    [
        ([], [], []),
        ({}, [], []),
        (["quantity is invalid"], ["quantity is invalid"], []),
        (
            {"price": ["price is invalid"]},
            [{"field": "price", "message": "price is invalid"}],
            ["price"],
        ),
        (
            {"field": "quantity", "message": "quantity is invalid"},
            [{"field": "quantity", "message": "quantity is invalid"}],
            ["quantity"],
        ),
    ],
)
async def test_cart_error_causes_accept_documented_container_shapes(
    causes, expected_causes, expected_fields
):
    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(request, {
                "access_token": "a",
                "refresh_token": "r",
                "store_id": "687890",
            })
        return response(request, {
            "code": 400,
            "name": "Bad Request",
            "causes": causes,
        }, 400)

    with pytest.raises(TrayAPIError) as error:
        await CartResource(client(handler)).create({
            "product_id": "803",
            "quantity": 1,
            "price": Decimal("4699.99"),
            "session_id": SESSION_32,
        })

    assert error.value.diagnostics["error_causes"] == expected_causes
    assert error.value.diagnostics.get("error_fields", []) == expected_fields


@pytest.mark.asyncio
async def test_cart_post_rejects_redirect_without_following_or_resending(caplog):
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")
    cart_calls = 0

    async def handler(request):
        nonlocal cart_calls
        if request.url.path.endswith("/auth"):
            return response(request, {
                "access_token": "a",
                "refresh_token": "r",
                "store_id": "687890",
            })
        cart_calls += 1
        return httpx.Response(
            307,
            headers={"location": "/web_api/carts/"},
            request=request,
        )

    with pytest.raises(TrayAPIError) as error:
        await CartResource(client(handler)).create({
            "product_id": "803",
            "quantity": 1,
            "price": Decimal("4699.99"),
            "session_id": SESSION_32,
        })

    assert error.value.status_code == 307
    assert error.value.diagnostics["final_url_path"] == "/web_api/carts"
    assert error.value.diagnostics["redirect_count"] == 0
    assert cart_calls == 1
    assert "status_code=307" in caplog.text
    assert "redirect_count=0" in caplog.text


@pytest.mark.asyncio
async def test_cart_upstream_sensitive_error_message_is_not_logged(caplog):
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        return response(
            request,
            {"code": 400, "message": "Invalid access_token=SECRET"},
            400,
        )

    with pytest.raises(TrayAPIError):
        await CartResource(client(handler)).create({
            "product_id": "123",
            "quantity": 1,
            "price": Decimal("50.00"),
            "session_id": SESSION_32,
        })

    assert "error_message=none" in caplog.text
    assert "SECRET" not in caplog.text
    assert "access_token" not in caplog.text


@pytest.mark.asyncio
async def test_cart_upstream_session_value_is_redacted_from_error_message(caplog):
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        return response(
            request,
            {"code": 400, "message": "Invalid session_id cart-session-value-123"},
            400,
        )

    with pytest.raises(TrayAPIError):
        await CartResource(client(handler)).create({
            "product_id": "123",
            "quantity": 1,
            "price": Decimal("50.00"),
            "session_id": SESSION_32,
        })

    assert "error_message=invalid field: session_id" in caplog.text
    assert "cart-session-value-123" not in caplog.text
    assert SESSION_32 not in caplog.text


@pytest.mark.asyncio
async def test_cart_post_timeout_reconciles_then_retries_only_once(caplog):
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")
    cart_calls = 0

    async def handler(request):
        nonlocal cart_calls
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        if request.method == "GET":
            return response(request, [])
        cart_calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(TrayConnectionError):
        await CartResource(client(handler)).create({
            "product_id": "123",
            "quantity": 1,
            "price": Decimal("6399.99"),
            "session_id": SESSION_32,
        })

    assert cart_calls == 2
    assert "reason=ambiguous_transport" in caplog.text
    assert "action=retry_once" in caplog.text
    assert "stage=upstream_http" in caplog.text
    assert "error_type=TrayConnectionError" in caplog.text


@pytest.mark.asyncio
async def test_cart_ambiguous_non_json_success_reconciles_without_duplicate():
    cart_posts = 0
    reconciliation_gets = 0

    async def handler(request):
        nonlocal cart_posts, reconciliation_gets
        if request.url.path.endswith("/auth"):
            return response(request, {
                "access_token": "a",
                "refresh_token": "r",
                "store_id": "687890",
            })
        if request.method == "GET":
            reconciliation_gets += 1
            return response(request, [{
                "Cart": {
                    "session_id": SESSION_32,
                    "product_id": "803",
                    "variant_id": "0",
                    "quantity": "1",
                    "price": "4699.99",
                }
            }])
        cart_posts += 1
        return httpx.Response(200, text="ambiguous upstream body", request=request)

    result = await CartResource(client(handler)).create({
        "product_id": "803",
        "quantity": 1,
        "price": Decimal("4699.99"),
        "session_id": SESSION_32,
    })

    assert result["success"] is True
    assert result["cart"]["items"][0]["product_id"] == "803"
    assert cart_posts == 1
    assert reconciliation_gets == 1


@pytest.mark.asyncio
async def test_cart_payload_translation_failure_is_identified(caplog):
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")

    with pytest.raises(TrayValidationError, match="cart_payload_invalid"):
        await CartResource(client(lambda request: response(request, {}))).create({
            "product_id": "123",
            "quantity": 1,
            "price": "not-a-decimal",
            "session_id": SESSION_32,
        })

    assert "stage=payload_translation" in caplog.text


@pytest.mark.asyncio
async def test_cart_normalization_failure_is_identified(monkeypatch, caplog):
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        return response(request, {"id": "1", "session_id": "S"}, 201)

    def fail_normalization(_):
        raise RuntimeError("normalization failed")

    monkeypatch.setattr("app.resources.carts.normalize_cart", fail_normalization)
    with pytest.raises(RuntimeError, match="normalization failed"):
        await CartResource(client(handler)).create({
            "product_id": "123",
            "quantity": 1,
            "price": Decimal("6399.99"),
            "session_id": SESSION_32,
        })

    assert "stage=normalization" in caplog.text

def _complete_quantity_cart(
    quantity,
    *,
    product_id=803,
    variant_id=None,
    sub_total="3799.99",
):
    product = {
        "id": str(product_id),
        "name": "Relógio",
        "quantity": str(quantity),
        "price": "3799.99",
    }
    if variant_id is not None:
        product["variant_id"] = str(variant_id)
    return {
        "Cart": {
            "session_id": SESSION_32,
            "cart_url": "https://store.test/cart?session=SECRET",
            "sub_total": sub_total,
            "total": sub_total,
            "Products": [product],
        }
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_quantity", [2, 4])
async def test_cart_quantity_reduction_to_one_uses_absolute_put_and_reconciles(
    caplog,
    initial_quantity,
):
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")
    state = {"quantity": initial_quantity}
    calls = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            subtotal = "3799.99" if state["quantity"] == 1 else "15199.96"
            return response(
                request,
                _complete_quantity_cart(state["quantity"], sub_total=subtotal),
            )
        assert json.loads(request.content) == {
            "Cart": {"product_id": 803, "quantity": 1}
        }
        state["quantity"] = 1
        return response(request, {"message": "Saved", "code": 200})

    result = await CartResource(client(handler)).set_item_quantity(
        SESSION_32,
        {"product_id": 803, "quantity": 1},
    )

    assert calls == [
        ("GET", f"/web_api/carts/{SESSION_32}/complete"),
        ("PUT", f"/web_api/carts/{SESSION_32}"),
        ("GET", f"/web_api/carts/{SESSION_32}/complete"),
    ]
    assert result["changed"] is True
    assert result["already_satisfied"] is False
    assert result["item"] == {
        "product_id": 803,
        "variant_id": None,
        "quantity": 1,
    }
    assert result["cart"]["items"][0]["quantity"] == 1
    assert result["cart"]["sub_total"] == 3799.99
    assert result["cart"]["total"] == 3799.99
    assert "[tray.cart.quantity.inspect]" in caplog.text
    assert "[tray.cart.quantity.update]" in caplog.text
    assert "[tray.cart.quantity.reconcile]" in caplog.text
    assert "status_code=200" in caplog.text
    assert "operation=set_item_quantity" in caplog.text
    assert "final_url_path=/web_api/carts/{session_id}" in caplog.text
    assert "session_hash=" in caplog.text
    assert SESSION_32 not in caplog.text
    assert "https://store.test/cart" not in caplog.text
    assert "access_token" not in caplog.text


@pytest.mark.asyncio
async def test_cart_quantity_one_to_one_is_idempotent_and_never_puts():
    calls = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        calls.append(request.method)
        assert request.method == "GET"
        return response(request, _complete_quantity_cart(1))

    result = await CartResource(client(handler)).set_item_quantity(
        SESSION_32,
        {"product_id": 803, "quantity": 1},
    )

    assert calls == ["GET"]
    assert result["changed"] is False
    assert result["already_satisfied"] is True
    assert result["item"]["quantity"] == 1


@pytest.mark.asyncio
async def test_cart_quantity_one_to_two_sets_two_instead_of_adding_two():
    state = {"quantity": 1}
    sent_quantities = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        if request.method == "GET":
            return response(request, _complete_quantity_cart(state["quantity"]))
        sent = json.loads(request.content)["Cart"]
        sent_quantities.append(sent["quantity"])
        state["quantity"] = sent["quantity"]
        return response(request, {"message": "Saved", "code": 200})

    result = await CartResource(client(handler)).set_item_quantity(
        SESSION_32,
        {"product_id": 803, "quantity": 2},
    )

    assert sent_quantities == [2]
    assert result["item"]["quantity"] == 2
    assert result["cart"]["items"][0]["quantity"] == 2
    assert result["cart"]["items"][0]["quantity"] != 3


@pytest.mark.asyncio
async def test_cart_quantity_matches_exact_variant_without_confusing_siblings():
    quantities = {986: 4, 987: 4}
    put_payloads = []

    def cart_body():
        return {
            "Cart": {
                "session_id": SESSION_32,
                "Products": [
                    {
                        "id": "803",
                        "variant_id": str(variant_id),
                        "quantity": str(quantity),
                        "price": "3799.99",
                    }
                    for variant_id, quantity in quantities.items()
                ],
            }
        }

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        if request.method == "GET":
            return response(request, cart_body())
        sent = json.loads(request.content)["Cart"]
        put_payloads.append(sent)
        quantities[sent["variant_id"]] = sent["quantity"]
        return response(request, {"message": "Saved", "code": 200})

    result = await CartResource(client(handler)).set_item_quantity(
        SESSION_32,
        {"product_id": 803, "variant_id": 987, "quantity": 1},
    )

    assert put_payloads == [
        {"product_id": 803, "variant_id": 987, "quantity": 1}
    ]
    final = {
        int(item["variant_id"]): item["quantity"]
        for item in result["cart"]["items"]
    }
    assert final == {986: 4, 987: 1}


@pytest.mark.asyncio
async def test_cart_quantity_missing_item_returns_factual_error_without_put():
    put_calls = 0

    async def handler(request):
        nonlocal put_calls
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        if request.method == "PUT":
            put_calls += 1
        return response(request, _complete_quantity_cart(1, product_id=804))

    with pytest.raises(TrayValidationError, match="cart_item_not_found"):
        await CartResource(client(handler)).set_item_quantity(
            SESSION_32,
            {"product_id": 803, "quantity": 1},
        )

    assert put_calls == 0


@pytest.mark.asyncio
async def test_cart_quantity_timeout_already_applied_reconciles_without_second_put():
    state = {"quantity": 4}
    put_calls = 0

    async def handler(request):
        nonlocal put_calls
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        if request.method == "GET":
            return response(request, _complete_quantity_cart(state["quantity"]))
        put_calls += 1
        state["quantity"] = 1
        raise httpx.ReadTimeout("timed out after apply", request=request)

    result = await CartResource(client(handler)).set_item_quantity(
        SESSION_32,
        {"product_id": 803, "quantity": 1},
    )

    assert put_calls == 1
    assert result["success"] is True
    assert result["cart"]["items"][0]["quantity"] == 1


@pytest.mark.asyncio
async def test_cart_quantity_timeout_not_applied_retries_once_then_reconciles():
    state = {"quantity": 4}
    put_calls = 0
    get_calls = 0

    async def handler(request):
        nonlocal put_calls, get_calls
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        if request.method == "GET":
            get_calls += 1
            return response(request, _complete_quantity_cart(state["quantity"]))
        put_calls += 1
        if put_calls == 1:
            raise httpx.ReadTimeout("timed out before apply", request=request)
        state["quantity"] = 1
        return response(request, {"message": "Saved", "code": 200})

    result = await CartResource(client(handler)).set_item_quantity(
        SESSION_32,
        {"product_id": 803, "quantity": 1},
    )

    assert put_calls == 2
    assert get_calls == 3
    assert result["cart"]["items"][0]["quantity"] == 1


@pytest.mark.asyncio
async def test_cart_quantity_401_refreshes_reconciles_then_retries_once():
    state = {"quantity": 4}
    put_calls = 0
    refreshes = 0

    async def handler(request):
        nonlocal put_calls, refreshes
        if request.url.path.endswith("/auth"):
            if request.method == "GET":
                refreshes += 1
            token = "new-token" if request.method == "GET" else "old-token"
            return response(
                request,
                {
                    "access_token": token,
                    "refresh_token": "refresh",
                    "store_id": "687890",
                },
            )
        if request.method == "GET":
            return response(request, _complete_quantity_cart(state["quantity"]))
        put_calls += 1
        if put_calls == 1:
            assert request.url.params["access_token"] == "old-token"
            return response(request, {"code": 401, "message": "Unauthorized"}, 401)
        assert request.url.params["access_token"] == "new-token"
        state["quantity"] = 1
        return response(request, {"message": "Saved", "code": 200})

    result = await CartResource(client(handler)).set_item_quantity(
        SESSION_32,
        {"product_id": 803, "quantity": 1},
    )

    assert put_calls == 2
    assert refreshes == 1
    assert result["cart"]["items"][0]["quantity"] == 1


def test_cart_quantity_upstream_error_preserves_diagnostics_and_safe_path(
    monkeypatch,
    caplog,
):
    configure(monkeypatch)
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(
                request,
                {"access_token": "a", "refresh_token": "r", "store_id": "687890"},
            )
        if request.method == "GET":
            return response(request, _complete_quantity_cart(2))
        return response(
            request,
            {
                "code": 400,
                "name": "Bad Request",
                "type": "validation",
                "field": "quantity",
                "causes": [
                    {"field": "quantity", "message": "quantity is invalid"}
                ],
                "message": "invalid quantity",
            },
            400,
        )

    monkeypatch.setattr(
        main,
        "_cart_resource",
        lambda: CartResource(client(handler)),
    )
    result = TestClient(main.app).put(
        f"/internal/carts/{SESSION_32}/items",
        json={"product_id": 803, "quantity": 1},
        headers={"Authorization": "Bearer adapter-token"},
    )

    assert result.status_code == 400
    assert result.json() == {
        "success": False,
        "error": "tray_api_error",
        "status_code": 400,
        "tray_error_code": 400,
        "tray_error_type": "validation",
        "tray_error_field": "quantity",
        "tray_error_fields": ["quantity"],
        "tray_error_message": "invalid quantity",
        "tray_error_name": "Bad Request",
        "tray_error_causes": [
            {"field": "quantity", "message": "quantity is invalid"}
        ],
    }
    assert "status_code=400" in caplog.text
    assert "final_url_path=/web_api/carts/{session_id}" in caplog.text
    assert "error_code=400" in caplog.text
    assert "error_name=Bad Request" in caplog.text
    assert "quantity is invalid" in caplog.text
    assert SESSION_32 not in caplog.text
    assert "access_token" not in caplog.text


def test_cart_quantity_route_has_dedicated_schema_without_price(monkeypatch, caplog):
    configure(monkeypatch)
    caplog.set_level("INFO", logger="uvicorn.error.tray.cart")

    class RecordingQuantityResource:
        def __init__(self):
            self.calls = []

        async def set_item_quantity(self, session_id, payload):
            self.calls.append((session_id, payload))
            return {
                "success": True,
                "changed": False,
                "already_satisfied": True,
                "session_id": session_id,
                "item": {**payload, "variant_id": payload.get("variant_id")},
                "cart": {"items": []},
            }

    resource = RecordingQuantityResource()
    monkeypatch.setattr(main, "_cart_resource", lambda: resource)
    api = TestClient(main.app)
    path = f"/internal/carts/{SESSION_32}/items"
    headers = {"Authorization": "Bearer adapter-token"}
    body = {"product_id": 803, "variant_id": None, "quantity": 1}

    assert api.put(path, json=body).status_code == 401
    assert api.put(path, json=body, headers=headers).status_code == 200
    assert resource.calls == [
        (SESSION_32, {"product_id": 803, "quantity": 1})
    ]
    for sentinel in (0, "0", ""):
        zero_variant = {**body, "variant_id": sentinel}
        assert api.put(path, json=zero_variant, headers=headers).status_code == 200
    assert resource.calls == [
        (SESSION_32, {"product_id": 803, "quantity": 1}),
        (SESSION_32, {"product_id": 803, "quantity": 1}),
        (SESSION_32, {"product_id": 803, "quantity": 1}),
        (SESSION_32, {"product_id": 803, "quantity": 1}),
    ]
    for invalid in (
        {**body, "quantity": 0},
        {**body, "product_id": 0},
        {**body, "variant_id": -1},
        {**body, "variant_id": "invalid"},
        {**body, "price": "3799.99"},
    ):
        assert api.put(path, json=invalid, headers=headers).status_code == 422
    assert len(resource.calls) == 4
    assert "[tray.cart.quantity.update]" in caplog.text
    routes = [
        route
        for route in main.app.routes
        if getattr(route, "path", "") == "/internal/carts/{session_id}/items"
    ]
    assert len(routes) == 1
    assert routes[0].methods == {"PUT"}
