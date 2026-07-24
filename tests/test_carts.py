import json
from decimal import Decimal
from urllib.parse import parse_qsl

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


def settings():
    return Settings("https://tray.test/web_api", "code", "key", "secret", 180, "687890")


def response(request, body, status=200):
    return httpx.Response(status, json=body, request=request)


def client(handler):
    transport = httpx.MockTransport(handler)
    auth = TrayAuth(settings(), httpx.AsyncClient(transport=transport))
    return TrayClient(auth, auth.http_client)


def form_body(request):
    return dict(parse_qsl(request.content.decode("utf-8"), keep_blank_values=True))


def configure(monkeypatch):
    for key, value in {
        "TRAY_API_BASE": "https://tray.test/web_api", "TRAY_CODE": "code",
        "TRAY_CONSUMER_KEY": "key", "TRAY_CONSUMER_SECRET": "secret",
        "TRAY_STORE_CODE": "687890", "TRAY_ADAPTER_TOKEN": "adapter-token",
    }.items():
        monkeypatch.setenv(key, value)


@pytest.mark.asyncio
async def test_cart_create_form_transport_matrix_and_201_normalization(caplog):
    caplog.set_level("INFO", logger="tray.cart")
    requests = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        requests.append(request)
        return response(request, {"id": "77", "session_id": SESSION_32, "cart_url": "https://store.test/cart", "message": "Created", "code": 201}, 201)

    resource = CartResource(client(handler))
    first = await resource.create({"product_id": "123", "variant_id": None, "quantity": 1, "price": Decimal("6399.99"), "session_id": SESSION_32})
    await resource.create({"product_id": "123", "variant_id": "900", "quantity": 1, "price": Decimal("6399.99"), "session_id": SESSION_32})
    await resource.create({"product_id": "456", "variant_id": "0", "quantity": 1, "price": Decimal("100.00"), "session_id": SESSION_32})

    assert all(request.method == "POST" for request in requests)
    assert all(request.url.path == "/web_api/carts/" for request in requests)
    assert all(set(request.url.params.keys()) == {"access_token"} for request in requests)
    assert all(
        request.headers["content-type"] == "application/x-www-form-urlencoded"
        for request in requests
    )
    assert all(not request.content.startswith(b"{") for request in requests)
    assert requests[0].content == (
        b"%5B%22Cart%22%5D%5B%22session_id%22%5D=ssssssssssssssssssssssssssssssss"
        b"&%5B%22Cart%22%5D%5B%22product_id%22%5D=123"
        b"&%5B%22Cart%22%5D%5B%22quantity%22%5D=1"
        b"&%5B%22Cart%22%5D%5B%22price%22%5D=6399.99"
    )
    assert form_body(requests[0]) == {
        '["Cart"]["session_id"]': SESSION_32,
        '["Cart"]["product_id"]': "123",
        '["Cart"]["quantity"]': "1",
        '["Cart"]["price"]': "6399.99",
    }
    assert form_body(requests[1]) == {
        '["Cart"]["session_id"]': SESSION_32,
        '["Cart"]["product_id"]': "123",
        '["Cart"]["quantity"]': "1",
        '["Cart"]["price"]': "6399.99",
        '["Cart"]["variant_id"]': "900",
    }
    assert form_body(requests[2]) == {
        '["Cart"]["session_id"]': SESSION_32,
        '["Cart"]["product_id"]': "456",
        '["Cart"]["quantity"]': "1",
        '["Cart"]["price"]': "100.00",
    }
    assert first == {"success": True, "cart": {"cart_id": "77", "session_id": SESSION_32, "cart_url": "https://store.test/cart", "message": "Created", "code": 201}}
    assert "[tray.cart.request]" in caplog.text
    assert "status_code=201" in caplog.text
    assert "response_is_json=true" in caplog.text
    assert "https://store.test/cart" not in caplog.text


@pytest.mark.asyncio
async def test_json_transport_is_distinct_and_remains_available_to_other_resources():
    requests = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        requests.append(request)
        return response(request, {"message": "Created"}, 200)

    payload = {"Cart": {"product_id": "123", "quantity": 1, "price": "50.00"}}
    await client(handler).request(
        "POST",
        "/carts/",
        json=payload,
        retry_on_auth_failure=False,
    )

    assert requests[0].headers["content-type"] == "application/json"
    assert json.loads(requests[0].content) == payload
    assert form_body(requests[0]) != {
        '["Cart"]["product_id"]': "123",
        '["Cart"]["quantity"]': "1",
        '["Cart"]["price"]': "50.00",
    }


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
    assert result["cart"] == {"session_id": "SESSION", "product_id": "123", "product_name": "Produto", "variant_id": "900", "quantity": 2, "price": 49.9}


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
                        "variant_id": "v2",
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
    assert result["cart"]["items"][1]["variant_id"] == "v2"
    assert len(result["cart"]["items"]) == 2


@pytest.mark.asyncio
async def test_successive_cart_posts_reuse_the_same_required_session_id():
    payloads = []

    async def handler(request):
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        payloads.append(form_body(request))
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
            '["Cart"]["session_id"]': SESSION_32,
            '["Cart"]["product_id"]': "101",
            '["Cart"]["quantity"]': "1",
            '["Cart"]["price"]': "10.00",
        },
        {
            '["Cart"]["session_id"]': SESSION_32,
            '["Cart"]["product_id"]': "202",
            '["Cart"]["quantity"]': "2",
            '["Cart"]["price"]': "20.00",
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
    caplog.set_level("INFO", logger="tray.cart")
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
    assert "variant_id" not in resource.calls[0]
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
    caplog.set_level("INFO", logger="tray.cart")
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
        assert request.url.path == f"/web_api/carts/{SESSION_32}/complete"
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
    caplog.set_level("INFO", logger="tray.cart")
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
    caplog.set_level("INFO", logger="tray.cart")
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
        "tray_error_type": "Bad Request",
        "tray_error_field": None,
        "tray_error_fields": ["variant_id"],
        "tray_error_message": "missing field: session_id",
    }
    assert cart_calls == 1
    assert "stage=upstream_http" in caplog.text
    assert "upstream_status=400" in caplog.text
    assert "response_is_json=true" in caplog.text
    assert "error_fields=['variant_id']" in caplog.text
    assert "error_message=missing field: session_id" in caplog.text
    assert "SECRET" not in caplog.text
    assert "access_token" not in caplog.text
    assert "https://tray.test/carts/" not in caplog.text


@pytest.mark.asyncio
async def test_cart_upstream_sensitive_error_message_is_not_logged(caplog):
    caplog.set_level("INFO", logger="tray.cart")

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
    caplog.set_level("INFO", logger="tray.cart")

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
async def test_cart_post_timeout_is_not_retried(caplog):
    caplog.set_level("INFO", logger="tray.cart")
    cart_calls = 0

    async def handler(request):
        nonlocal cart_calls
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        cart_calls += 1
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(TrayConnectionError):
        await CartResource(client(handler)).create({
            "product_id": "123",
            "quantity": 1,
            "price": Decimal("6399.99"),
            "session_id": SESSION_32,
        })

    assert cart_calls == 1
    assert "stage=upstream_http" in caplog.text
    assert "error_type=TrayConnectionError" in caplog.text


@pytest.mark.asyncio
async def test_cart_payload_translation_failure_is_identified(caplog):
    caplog.set_level("INFO", logger="tray.cart")

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
    caplog.set_level("INFO", logger="tray.cart")

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
