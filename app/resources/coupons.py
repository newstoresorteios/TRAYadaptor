from .common import Resource, coupon_dates, validate_coupon_relationship
from ..normalizers.coupon import normalize_coupon, normalize_relationship
from ..normalizers.common import normalized_list


class CouponResource(Resource):
    path, plural, singular, normalizer = "/discount_coupons", "DiscountCoupons", "coupon", staticmethod(normalize_coupon)

    async def create(self, payload):
        validate_coupon_relationship(payload)
        return await self.client.request("POST", self.path, json=coupon_dates(payload, self.client.auth.settings.tray_coupon_valid_days))

    async def relationship(self, kind, coupon_id):
        payload = await self.client.request("GET", f"/discount_coupons/{kind}_relationship/{coupon_id}")
        return normalized_list(payload, kind.capitalize() + "Relationships", kind + "_relationship", normalize_relationship, kind + "s")

    async def create_relationship(self, coupon_id, payload):
        validate_coupon_relationship(payload)
        records = payload.get("customers") or payload.get("customer_ids") if isinstance(payload, dict) else None
        if isinstance(records, list) and records:
            results = []
            for index in range(0, len(records), 100):
                chunk = dict(payload)
                key = "customers" if payload.get("customers") is not None else "customer_ids"
                chunk[key] = records[index:index + 100]
                results.append(await self.client.request("POST", f"/discount_coupons/create_relationship/{coupon_id}", json=chunk))
            return {"success": True, "batches": len(results), "responses": results}
        return await self.client.request("POST", f"/discount_coupons/create_relationship/{coupon_id}", json=payload)

    async def delete_relationship(self, coupon_id, payload):
        return await self.client.request("DELETE", f"/delete_relationship/{coupon_id}", json=payload)
