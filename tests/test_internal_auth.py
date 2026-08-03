from fastapi.testclient import TestClient

from app import main


class FakeResource:
    async def list(self, params=None): return {"success": True, "products": []}
    async def get(self, resource_id): return {"success": True}
    async def get_product_stock(self, product_id): return {"success": True}
    async def distribution_centers(self, params=None): return {"success": True, "distribution_centers": []}


class FakeClient:
    class Auth:
        state = None
    auth = Auth()


class RecordingProductResource(FakeResource):
    def __init__(self):
        self.params = None

    async def list(self, params=None):
        self.params = params
        return {"success": True, "products": []}


class RecordingVariantResource:
    def __init__(self):
        self.calls = []

    async def list(self, params=None):
        self.calls.append(("list", params))
        return {"success": True, "variants": []}

    async def get(self, variant_id):
        self.calls.append(("detail", variant_id))
        return {"success": True, "variant": {"id": variant_id}}


class RecordingCategoryResource:
    def __init__(self):
        self.calls = []

    async def list(self, params=None):
        self.calls.append(("list", params))
        return {"success": True, "categories": []}

    async def get(self, category_id):
        self.calls.append(("detail", category_id))
        return {"success": True, "category": {"id": category_id}}

    async def tree(self, category_id):
        self.calls.append(("tree", category_id))
        return {"success": True, "category": {"id": category_id}}


def configure(monkeypatch):
    for key, value in {
        "TRAY_API_BASE": "https://tray.test/web_api", "TRAY_CODE": "code",
        "TRAY_CONSUMER_KEY": "key", "TRAY_CONSUMER_SECRET": "secret",
        "TRAY_STORE_CODE": "687890", "TRAY_ADAPTER_TOKEN": "adapter-token",
    }.items():
        monkeypatch.setenv(key, value)


class SearchAwareFakeResource(FakeResource):
    async def search_by_tokens(self, tokens, *, brand=None, limit=20, page=1):
        return {"success": True, "paging": {"total": 0, "page": page, "limit": limit}, "products": []}


def test_internal_routes_require_bearer_and_public_health(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr(main, "_resources", lambda: (FakeClient(), SearchAwareFakeResource(), FakeResource(), FakeResource(), FakeResource(), FakeResource(), FakeResource(), FakeResource()))
    client = TestClient(main.app)
    assert client.get("/health").status_code == 200
    assert client.get("/internal/products").status_code == 401
    assert client.get("/internal/products", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/internal/products", headers={"Authorization": "Bearer adapter-token"}).status_code == 200
    assert client.get("/internal/products/search?tokens=sealander", headers={"Authorization": "Bearer adapter-token"}).status_code == 200
    assert client.get("/internal/products/search?tokens=sealander").status_code == 401
    assert client.get("/internal/customers").status_code == 401
    assert client.get("/internal/coupons").status_code == 401
    assert client.get("/internal/users").status_code == 401
    assert client.get("/internal/inventory/distribution-centers").status_code == 401
    assert client.get("/internal/categories").status_code == 401
    assert client.get("/internal/products/variants").status_code == 401
    assert client.get("/tray/test-resources").status_code == 200


def test_internal_products_forwards_candidate_pool_filters(monkeypatch):
    configure(monkeypatch)
    products = RecordingProductResource()
    monkeypatch.setattr(main, "_resources", lambda: (FakeClient(), products, FakeResource(), FakeResource(), FakeResource(), FakeResource(), FakeResource(), FakeResource()))
    client = TestClient(main.app)
    headers = {"Authorization": "Bearer adapter-token"}
    response = client.get(
        "/internal/products?name=relogio&category_id=123&available=true&available_in_store=true&limit=20&page=2&model=Classic&brand_id=10&property_name=Cor&current_price_range=100,200",
        headers=headers,
    )
    assert response.status_code == 200
    assert products.params == {
        "name": "relogio", "category_id": "123", "available": "1",
        "available_in_store": "1", "limit": 20, "page": "2", "model": "Classic",
        "brand_id": "10", "property_name": "Cor", "current_price_range": "100,200",
    }
    assert client.get("/internal/products?limit=0", headers=headers).status_code == 422
    assert client.get("/internal/products?limit=51", headers=headers).status_code == 422


def test_static_variant_and_category_tree_routes_are_not_captured(monkeypatch):
    configure(monkeypatch)
    variants = RecordingVariantResource()
    categories = RecordingCategoryResource()
    monkeypatch.setattr(main, "_variant_resource", lambda: variants)
    monkeypatch.setattr(main, "_category_resource", lambda: categories)
    client = TestClient(main.app)
    headers = {"Authorization": "Bearer adapter-token"}

    assert client.get("/internal/products/variants?product_id=123", headers=headers).status_code == 200
    assert client.get("/internal/products/variants/900", headers=headers).status_code == 200
    assert client.get("/internal/categories/tree/10", headers=headers).status_code == 200

    assert variants.calls[0] == ("list", {"product_id": "123", "limit": 20})
    assert variants.calls[1] == ("detail", "900")
    assert categories.calls == [("tree", "10")]
