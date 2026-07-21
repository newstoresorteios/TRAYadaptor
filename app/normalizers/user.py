def normalize_user(v):
    return {key: v.get(key) for key in ("id", "full_name", "name", "email", "main_user", "active", "two_factor_enabled", "image", "last_login", "permissions") if key in v}
