import httpx
import pytest

from app.exceptions import TrayAuthenticationError, TrayValidationError
from app.normalizers.customer import normalize_customer
from app.normalizers.product import normalize_product
from app.resources.brands import BrandResource
from app.resources.coupons import CouponResource
from app.resources.customers import CustomerResource
from app.resources.inventory import InventoryResource
from app.resources.kits import KitResource
from app.resources.products import ProductResource
from app.resources.users import UserResource
from app.config import Settings
from app.tray_auth import TrayAuth
from app.tray_client import TrayClient


def settings(days=180): return Settings("https://tray.test/web_api", "code", "key", "secret", days, "687890")


def reply(request, body, status=200): return httpx.Response(status, json=body, request=request)


def client(handler):
    transport = httpx.MockTransport(handler)
    auth = TrayAuth(settings(), httpx.AsyncClient(transport=transport))
    return TrayClient(auth, auth.http_client)


@pytest.mark.asyncio
async def test_client_refreshes_once_on_401_and_supports_json_methods():
    calls = []
    async def handler(request):
        calls.append((request.method, request.url.path, dict(request.url.params)))
        if request.url.path.endswith("/auth"):
            if request.method == "GET": return reply(request, {"access_token": "new", "refresh_token": "new-r", "store_id": "687890"})
            return reply(request, {"access_token": "old", "refresh_token": "r", "store_id": "687890"})
        if len(calls) == 2: return reply(request, {}, 401)
        return reply(request, {"ok": True})
    result = await client(handler).request("POST", "/products", json={"Product": {"name": "x"}})
    assert result == {"ok": True} and calls[-1][2]["access_token"] == "new"


@pytest.mark.asyncio
async def test_product_normalization_and_crud():
    async def handler(request): return reply(request, {"Products": [{"Product": {"id": "1", "price": "139.00", "promotional_price": "0.00", "stock": "51", "available": False, "ProductSettings": {"when_stock_runs_out": "sell_extended_lead_time", "order_days_availability": "7"}, "Variant": [{"id": "v1", "price": "10"}]}}]}) if not request.url.path.endswith("/auth") else reply(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
    resource = ProductResource(client(handler))
    result = await resource.list({"name": "Relogio", "limit": 1, "ean": "1"})
    assert result["products"][0]["promotional_price"] is None
    assert result["products"][0]["when_stock_runs_out"] == "sell_extended_lead_time"
    assert (await resource.get_product_stock("1"))["stock"] == 51
    await resource.create({"Product": {"name": "x"}}); await resource.update("1", {"Product": {"name": "y"}}); await resource.delete("1")


def test_product_normalizes_uppercase_properties_and_recommendation_fields():
    product = normalize_product({
        "id": "1", "name": "Relógio Teste", "brand_id": "10", "model": "Classic",
        "Properties": [{"name": "Cor", "value": "Preto", "property_id": "7"}],
        "related_categories": [{"id": "3"}], "start_promotion": "2026-07-01",
        "end_promotion": "2026-07-31", "hot": "1", "release": "0",
        "promotion": "1", "current_price": "139.00",
    })
    assert product["properties"] == [{"name": "Cor", "value": "Preto", "property_id": "7"}]
    assert product["related_categories"] == [{"id": "3"}]
    assert product["current_price"] == 139.0
    assert product["start_promotion"] == "2026-07-01"


def test_product_keeps_lowercase_properties_compatible():
    properties = [{"name": "Material", "value": "Aço", "extra": "preserved"}]
    assert normalize_product({"id": "2", "properties": properties})["properties"] == properties


def test_product_images_prioritize_https_preserve_all_and_allow_empty():
    product = normalize_product({
        "id": "1",
        "ProductImage": [
            {
                "http": "http://tray.test/original-1.jpg",
                "https": "https://tray.test/original-1.jpg",
                "thumbs": {
                    "180": {
                        "http": "http://tray.test/thumb-1.jpg",
                        "https": "https://tray.test/thumb-1.jpg",
                    }
                },
            },
            {
                "http": "http://tray.test/original-2.jpg",
                "https": "https://tray.test/original-2.jpg",
            },
        ],
    })

    assert product["images"] == [
        {
            "url": "https://tray.test/original-1.jpg",
            "thumb_180": "https://tray.test/thumb-1.jpg",
        },
        {"url": "https://tray.test/original-2.jpg", "thumb_180": None},
    ]
    assert product["primary_image_url"] == "https://tray.test/original-1.jpg"

    without_image = normalize_product({"id": "2"})
    assert without_image["images"] == []
    assert without_image["primary_image_url"] is None


def test_embedded_variant_preserves_only_its_own_image():
    product = normalize_product({
        "id": "1",
        "ProductImage": [{"https": "https://tray.test/product.jpg"}],
        "Variant": [
            {
                "id": "v1",
                "VariantImage": [{"https": "https://tray.test/variant-v1.jpg"}],
            }
        ],
    })

    assert product["primary_image_url"] == "https://tray.test/product.jpg"
    assert product["variants"][0]["images"] == [
        {"url": "https://tray.test/variant-v1.jpg", "thumb_180": None}
    ]
    assert product["variants"][0]["primary_image_url"] == "https://tray.test/variant-v1.jpg"


@pytest.mark.asyncio
async def test_brand_kit_customer_and_user_resources():
    async def handler(request):
        if request.url.path.endswith("/auth"): return reply(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        if "/brands" in request.url.path: return reply(request, {"Brands": [{"Brand": {"id": "b", "brand": "Casio"}}]})
        if "/kits" in request.url.path: return reply(request, {"Kits": [{"Kit": {"id": "k", "ProductVariantKit": [{"variant_id": "v", "price": "2"}]}}]})
        if "/addresses" in request.url.path: return reply(request, {"paging": {"total": 2, "page": 1, "offset": 0, "limit": 2, "maxLimit": 50}, "CustomerAddresses": [{"CustomerAddress": {"id": "a", "customer_id": "c"}}]})
        if "/customers" in request.url.path: return reply(request, {"Customers": [{"Customer": {"id": "c", "token": "secret"}}]})
        return reply(request, {"Users": [{"User": {"id": "u", "cpf": "hidden", "permissions": {"Products": True}}}]})
    c = client(handler)
    assert (await BrandResource(c).list())["brands"][0]["name"] == "Casio"
    assert (await KitResource(c).list())["kits"][0]["variants"][0]["variant_id"] == "v"
    assert "token" not in (await CustomerResource(c).list())["customers"][0]
    assert (await CustomerResource(c).addresses())["addresses"][0]["customer_id"] == "c"
    assert "cpf" not in (await UserResource(c).list())["users"][0]
    await BrandResource(c).create({}); await BrandResource(c).update("b", {}); await BrandResource(c).delete("b")


@pytest.mark.asyncio
async def test_customer_addresses_real_envelope_and_detail():
    async def handler(request):
        if request.url.path.endswith("/auth"):
            return reply(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        if request.url.path.endswith("/addresses"):
            return reply(request, {"paging": {"total": 2, "page": 1, "offset": 0, "limit": 2, "maxLimit": 50}, "CustomerAddresses": [{"CustomerAddress": {"id": "123", "customer_id": "10", "address": "Rua Teste", "number": "100"}}]})
        return reply(request, {"CustomerAddress": {"id": "123", "customer_id": "10", "address": "Rua Teste", "number": "100"}})
    resource = CustomerResource(client(handler))
    result = await resource.addresses({"limit": 2})
    assert len(result["addresses"]) == 1
    assert result["paging"]["total"] == 2
    detail = await resource.address("123")
    assert detail["address"]["id"] == "123" and detail["address"]["number"] == "100"


@pytest.mark.asyncio
async def test_inventory_validation_and_update():
    async def handler(request):
        if request.url.path.endswith("/auth"): return reply(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        return reply(request, {"DistributionCenters": [{"DistributionCenter": {"id": "dc"}}]})
    resource = InventoryResource(client(handler))
    assert (await resource.distribution_centers())["distribution_centers"][0]["id"] == "dc"
    with pytest.raises(TrayValidationError): await resource.update_stock("dc", {"product_id": "p", "reference": "r", "stock": 1})
    with pytest.raises(TrayValidationError): await resource.update_stock("dc", {"stock": 1})
    await resource.update_stock("dc", {"product_id": "p", "stock": 1})


@pytest.mark.asyncio
async def test_coupon_dates_conflicts_relationship_batch_and_delete():
    calls = []
    async def handler(request):
        calls.append(request)
        if request.url.path.endswith("/auth"): return reply(request, {"access_token": "a", "refresh_token": "r", "store_id": "687890"})
        return reply(request, {"DiscountCoupons": [{"DiscountCoupon": {"id": "cp", "type": "%"}}]})
    resource = CouponResource(client(handler))
    created = await resource.create({"code": "X", "starts_at": "2026-01-01T00:00:00+00:00"})
    assert created["DiscountCoupons"][0]["DiscountCoupon"]["type"] == "%"
    await resource.create({"code": "Y", "ends_at": "2099-01-01T00:00:00+00:00"})
    with pytest.raises(TrayValidationError): await resource.create({"products": ["p"], "brands": ["b"]})
    result = await resource.create_relationship("cp", {"customers": list(range(250))})
    assert result["batches"] == 3
    await resource.delete_relationship("cp", {"delete": "all"})
