import pytest
from fastapi.testclient import TestClient

from app import main
from app.product_search import (
    fold_text,
    paginate_products,
    parse_tokens,
    product_matches_tokens,
)


class FakeClient:
    class Auth:
        state = None

    auth = Auth()


class FakeSiblingResource:
    async def list(self, params=None):
        return {"success": True}


class RecordingSearchProductResource:
    def __init__(self, products=None):
        self.products = products or []
        self.calls = []

    async def list(self, params=None):
        raise AssertionError("list must not be used directly by the route")

    async def get(self, resource_id):
        return {"success": True, "product": {"id": resource_id}}

    async def get_product_stock(self, product_id):
        return {"success": True, "product_id": str(product_id), "stock": 0}

    async def search_by_tokens(self, tokens, *, brand=None, limit=20, page=1):
        self.calls.append({
            "tokens": tokens,
            "brand": brand,
            "limit": limit,
            "page": page,
        })
        matched = [
            product
            for product in self.products
            if product_matches_tokens(product, tokens)
        ]
        return paginate_products(matched, limit=limit, page=page)


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


def _catalog():
    return [
        {
            "id": "10",
            "name": "Relógio Christopher Ward C63 Sealander Automático Kingfisher",
            "brand": "Christopher Ward",
            "model": "C63 Sealander",
            "reference": "C63-36ADA3",
            "description": "Kingfisher blue dial",
            "price": 8900.0,
            "stock": 2,
            "available": True,
        },
        {
            "id": "20",
            "name": (
                "Relógio Christopher Ward C63 Sealander Automático Rosa "
                "C63-36ADA4-S00P0-B0 36 mm"
            ),
            "brand": "Christopher Ward",
            "model": "C63 Sealander",
            "reference": "C63-36ADA4-S00P0-B0",
            "description": "Caixa aço, automático rosa",
            "price": 9100.0,
            "promotional_price": 8900.0,
            "stock": 1,
            "available": True,
        },
        {
            "id": "30",
            "name": "Relógio Tissot Seastar Automático",
            "brand": "Tissot",
            "model": "Seastar",
            "reference": "T120",
            "description": "",
            "price": 3000.0,
            "stock": 0,
            "available": False,
        },
    ]


def test_parse_tokens_trims_lowers_and_drops_empties():
    assert parse_tokens(" sealander , , Rosa ,AUTOMATICO ") == [
        "sealander",
        "rosa",
        "automatico",
    ]
    assert parse_tokens("   ,  ,") == []
    assert parse_tokens(None) == []


def test_fold_text_strips_accents():
    assert fold_text("Automático") == "automatico"
    assert fold_text("Rosa") == "rosa"


def test_product_matches_tokens_requires_and_and_ignores_order():
    product = _catalog()[1]
    assert product_matches_tokens(product, ["sealander", "rosa"])
    assert product_matches_tokens(product, ["rosa", "sealander", "automatico"])
    assert not product_matches_tokens(product, ["sealander", "kingfisher"])
    assert product_matches_tokens(
        {
            "name": "Relógio Automático",
            "brand": "",
            "model": "",
            "reference": "",
            "description": "",
        },
        ["automatico"],
    )


def test_paginate_products_builds_coherent_paging():
    products = [{"id": "3"}, {"id": "1"}, {"id": "2"}]
    page1 = paginate_products(products, limit=2, page=1)
    assert [item["id"] for item in page1["products"]] == ["1", "2"]
    assert page1["paging"] == {
        "total": 3,
        "page": 1,
        "limit": 2,
        "offset": 0,
        "maxLimit": 50,
    }
    page2 = paginate_products(products, limit=2, page=2)
    assert [item["id"] for item in page2["products"]] == ["3"]
    assert page2["paging"]["offset"] == 2


@pytest.mark.asyncio
async def test_search_by_tokens_filters_brand_pool_with_and_semantics():
    from app.resources.products import ProductResource

    catalog = _catalog()
    calls = []

    resource = ProductResource(client=None)

    async def fake_list(params=None):
        calls.append(params)
        brand = (params or {}).get("brand")
        products = [
            product
            for product in catalog
            if brand is None or product.get("brand") == brand
        ]
        return {"success": True, "products": products, "paging": {}}

    resource.list = fake_list  # type: ignore[method-assign]
    result = await resource.search_by_tokens(
        ["sealander", "rosa", "automatico"],
        brand="Christopher Ward",
        limit=20,
        page=1,
    )

    assert [item["id"] for item in result["products"]] == ["20"]
    assert result["paging"]["total"] == 1
    assert {
        "brand": "Christopher Ward",
        "name": "sealander rosa automatico",
        "limit": 50,
        "page": 1,
    } in calls
    assert all(params.get("name") for params in calls)


def test_internal_products_search_route_contract(monkeypatch):
    configure(monkeypatch)
    products = RecordingSearchProductResource(_catalog())
    monkeypatch.setattr(
        main,
        "_resources",
        lambda: (
            FakeClient(),
            products,
            FakeSiblingResource(),
            FakeSiblingResource(),
            FakeSiblingResource(),
            FakeSiblingResource(),
            FakeSiblingResource(),
            FakeSiblingResource(),
        ),
    )
    client = TestClient(main.app)
    headers = {"Authorization": "Bearer adapter-token"}

    assert client.get("/internal/products/search", headers=headers).status_code == 422
    assert client.get(
        "/internal/products/search?tokens=%20,%20",
        headers=headers,
    ).status_code == 400
    assert client.get(
        "/internal/products/search?tokens=sealander",
        headers={"Authorization": "Bearer wrong"},
    ).status_code == 401

    response = client.get(
        "/internal/products/search"
        "?tokens=sealander,rosa,automatico"
        "&brand=Christopher%20Ward"
        "&limit=20"
        "&page=1",
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert [item["id"] for item in body["products"]] == ["20"]
    assert body["paging"]["total"] == 1
    assert body["paging"]["page"] == 1
    assert body["paging"]["limit"] == 20
    assert products.calls == [{
        "tokens": ["sealander", "rosa", "automatico"],
        "brand": "Christopher Ward",
        "limit": 20,
        "page": 1,
    }]

    assert client.get(
        "/internal/products/search?tokens=sealander&limit=51",
        headers=headers,
    ).status_code == 422
    assert client.get(
        "/internal/products/search?tokens=sealander&page=0",
        headers=headers,
    ).status_code == 422


def test_search_route_is_not_captured_by_product_id(monkeypatch):
    configure(monkeypatch)
    products = RecordingSearchProductResource(_catalog())
    monkeypatch.setattr(
        main,
        "_resources",
        lambda: (
            FakeClient(),
            products,
            FakeSiblingResource(),
            FakeSiblingResource(),
            FakeSiblingResource(),
            FakeSiblingResource(),
            FakeSiblingResource(),
            FakeSiblingResource(),
        ),
    )
    client = TestClient(main.app)
    response = client.get(
        "/internal/products/search?tokens=sealander,rosa",
        headers={"Authorization": "Bearer adapter-token"},
    )
    assert response.status_code == 200
    assert products.calls
    assert response.json()["products"][0]["id"] == "20"
