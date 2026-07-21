from fastapi.testclient import TestClient

from app import main


class FakeResource:
    async def list(self, params=None): return {"success": True, "products": []}
    async def get(self, resource_id): return {"success": True}
    async def get_product_stock(self, product_id): return {"success": True}


def configure(monkeypatch):
    for key, value in {
        "TRAY_API_BASE": "https://tray.test/web_api", "TRAY_CODE": "code",
        "TRAY_CONSUMER_KEY": "key", "TRAY_CONSUMER_SECRET": "secret",
        "TRAY_STORE_CODE": "687890", "TRAY_ADAPTER_TOKEN": "adapter-token",
    }.items():
        monkeypatch.setenv(key, value)


def test_internal_routes_require_bearer_and_public_health(monkeypatch):
    configure(monkeypatch)
    original = main._resources
    monkeypatch.setattr(main, "_resources", lambda: (None, FakeResource(), FakeResource(), FakeResource(), FakeResource(), FakeResource(), FakeResource(), FakeResource()))
    client = TestClient(main.app)
    assert client.get("/health").status_code == 200
    assert client.get("/internal/products").status_code == 401
    assert client.get("/internal/products", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/internal/products", headers={"Authorization": "Bearer adapter-token"}).status_code == 200
    assert client.get("/internal/customers").status_code == 401
    assert client.get("/internal/coupons").status_code == 401
    assert client.get("/internal/users").status_code == 401
    assert main._resources is not original
