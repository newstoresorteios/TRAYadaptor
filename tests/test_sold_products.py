from fastapi.testclient import TestClient

from app import main
from app.resources.sold_products import SoldProductResource


class FakeClient:
    def __init__(self):
        self.requested = None

    async def request(self, method, path, *, params=None):
        self.requested = (method, path, params)
        return {
            "paging": {"total": 1, "page": 1, "limit": 50},
            "ProductsSolds": [
                {
                    "ProductsSold": {
                        "id": "123",
                        "product_id": "456",
                        "order_id": "789",
                        "name": "Produto",
                        "price": "51.80",
                        "quantity": "1",
                    }
                }
            ],
        }


def test_internal_products_sold_forwards_safe_pagination(monkeypatch):
    for key, value in {
        "TRAY_API_BASE": "https://tray.test/web_api",
        "TRAY_CODE": "code",
        "TRAY_CONSUMER_KEY": "key",
        "TRAY_CONSUMER_SECRET": "secret",
        "TRAY_STORE_CODE": "687890",
        "TRAY_ADAPTER_TOKEN": "adapter-token",
    }.items():
        monkeypatch.setenv(key, value)
    fake = FakeClient()
    monkeypatch.setattr(
        main,
        "_sold_product_resource",
        lambda: SoldProductResource(fake),
    )
    api = TestClient(main.app)
    result = api.get(
        "/internal/products-sold?page=2&limit=50&ignored=value",
        headers={"Authorization": "Bearer adapter-token"},
    )

    assert result.status_code == 200
    assert fake.requested == (
        "GET",
        "/products_solds",
        {"page": "2", "limit": 50},
    )
    assert result.json()["sold_products"] == [
        {
            "id": "123",
            "product_id": "456",
            "order_id": "789",
            "name": "Produto",
            "price": "51.80",
            "quantity": "1",
        }
    ]
