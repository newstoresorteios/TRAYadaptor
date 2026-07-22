import logging

from ..normalizers.common import items
from ..normalizers.variant import normalize_variant

logger = logging.getLogger("tray.variants")


class VariantResource:
    def __init__(self, client):
        self.client = client

    async def list(self, params=None):
        try:
            payload = await self.client.request("GET", "/products/variants/", params=params)
            plural = "ProductVariants" if isinstance(payload, dict) and "ProductVariants" in payload else "Variants"
            values, paging = items(payload, plural, "variant")
            variants = [normalize_variant(value) for value in values]
            logger.info("operation=list ok=true count=%d", len(variants))
            return {"success": True, "paging": paging, "variants": variants}
        except Exception:
            logger.info("operation=list ok=false")
            raise

    async def get(self, variant_id):
        try:
            payload = await self.client.request("GET", f"/products/variants/{variant_id}")
            logger.info("operation=detail ok=true")
            return {"success": True, "variant": normalize_variant(payload)}
        except Exception:
            logger.info("operation=detail ok=false")
            raise
