import logging

from ..normalizers.category import normalize_category
from ..normalizers.common import items

logger = logging.getLogger("tray.categories")


class CategoryResource:
    def __init__(self, client):
        self.client = client

    async def list(self, params=None):
        try:
            payload = await self.client.request("GET", "/categories/", params=params)
            values, paging = items(payload, "Categories", "category")
            categories = [normalize_category(value) for value in values]
            logger.info("operation=list ok=true count=%d", len(categories))
            return {"success": True, "paging": paging, "categories": categories}
        except Exception:
            logger.info("operation=list ok=false")
            raise

    async def get(self, category_id):
        try:
            payload = await self.client.request("GET", f"/categories/{category_id}")
            logger.info("operation=detail ok=true")
            return {"success": True, "category": normalize_category(payload)}
        except Exception:
            logger.info("operation=detail ok=false")
            raise

    async def tree(self, category_id):
        try:
            payload = await self.client.request("GET", f"/categories/tree/{category_id}")
            logger.info("operation=tree ok=true")
            return {"success": True, "category": normalize_category(payload)}
        except Exception:
            logger.info("operation=tree ok=false")
            raise
