import httpx
import pytest

from app.config import Settings
from app.resources.categories import CategoryResource
from app.resources.variants import VariantResource
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


@pytest.mark.asyncio
async def test_categories_list_detail_tree_paging_and_recursive_children():
    calls = []

    async def handler(request):
        calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        category = {
            "Category": {
                "id": "10", "name": "Relógios", "slug": "relogios", "parent_id": "0",
                "has_product": "1", "Children": [{"Category": {"id": "11", "name": "Masculinos", "parent_id": "10", "children": [{"Category": {"id": "12", "name": "Automáticos", "parent_id": "11"}}]}}],
            }
        }
        if request.url.path.endswith("/categories/"):
            return response(request, {"paging": {"total": 1, "page": 1, "limit": 20}, "Categories": [category]})
        return response(request, category)

    resource = CategoryResource(client(handler))
    listed = await resource.list({"limit": 20, "page": 1})
    detailed = await resource.get("10")
    tree = await resource.tree("10")

    assert calls[1][1] == "/web_api/categories/"
    assert calls[2][1] == "/web_api/categories/10"
    assert calls[3][1] == "/web_api/categories/tree/10"
    assert listed["paging"] == {"total": 1, "page": 1, "limit": 20}
    assert listed["categories"][0]["children"][0]["children"][0]["name"] == "Automáticos"
    assert detailed["category"]["id"] == "10"
    assert tree["category"]["children"][0]["id"] == "11"


@pytest.mark.asyncio
async def test_variants_list_detail_filters_sku_prices_stock_and_settings():
    calls = []
    variant = {
        "Variant": {
            "id": "900", "product_id": "123", "ean": "789", "price": "139.00",
            "promotional_price": "119.00", "stock": "4", "minimum_stock": "1",
            "reference": "REF-PRETO", "quantity_sold": "7", "availability_days": "3",
            "Sku": [{"Sku": {"type": "Cor", "value": "Preto", "image": "http://tray.test/sku.jpg", "image_secure": "https://tray.test/sku.jpg"}}],
            "VariantImage": [{"http": "http://tray.test/variant.jpg", "https": "https://tray.test/variant.jpg"}],
            "VariationSettings": {"when_stock_runs_out": "sell_extended_lead_time", "order_days_availability": "5"},
        }
    }

    async def handler(request):
        calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path.endswith("/auth"):
            return response(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        if request.url.path.endswith("/variants/"):
            return response(request, {"paging": {"total": 1, "page": 1, "limit": 20}, "Variants": [variant]})
        return response(request, variant)

    resource = VariantResource(client(handler))
    listed = await resource.list({"product_id": "123", "limit": 20})
    detailed = await resource.get("900")

    assert calls[1][1] == "/web_api/products/variants/"
    assert calls[1][2]["product_id"] == "123"
    assert calls[2][1] == "/web_api/products/variants/900"
    normalized = listed["variants"][0]
    assert normalized["sku"] == [{"type": "Cor", "value": "Preto", "image_url": "https://tray.test/sku.jpg"}]
    assert normalized["images"] == [{"url": "https://tray.test/variant.jpg", "thumb_180": None}]
    assert normalized["primary_image_url"] == "https://tray.test/variant.jpg"
    assert normalized["price"] == 139.0
    assert normalized["promotional_price"] == 119.0
    assert normalized["stock"] == 4
    assert normalized["reference"] == "REF-PRETO"
    assert normalized["variation_settings"]["when_stock_runs_out"] == "sell_extended_lead_time"
    assert "available" not in normalized
    assert detailed["variant"]["id"] == "900"
