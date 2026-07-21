def normalize_coupon(v):
    return {key: v.get(key) for key in ("id", "code", "description", "created", "updated", "starts_at", "ends_at", "value", "type", "value_start", "value_end", "usage_counter", "usage_sum", "usage_sum_limit", "usage_counter_limit", "usage_counter_limit_customer", "coupon_type", "local_application", "freight_application", "cumulative_discount")}


def normalize_relationship(v):
    return v if isinstance(v, dict) else {"value": v}
