import os
from dataclasses import dataclass

from .exceptions import TrayConfigurationError


@dataclass(frozen=True)
class Settings:
    tray_api_base: str
    tray_code: str
    tray_consumer_key: str
    tray_consumer_secret: str
    tray_coupon_valid_days: int = 180
    tray_store_code: str = ""
    tray_adapter_token: str = ""
    tray_refresh_token: str = ""
    customer_birth_date_fallback: str = "1900-01-01"
    tray_webhook_token: str = ""
    tray_rate_limit_per_minute: int = 90
    tray_rate_limit_per_day: int = 4000


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise TrayConfigurationError(f"{name} must be an integer") from exc


def get_settings() -> Settings:
    names = (
        "TRAY_API_BASE",
        "TRAY_CODE",
        "TRAY_CONSUMER_KEY",
        "TRAY_CONSUMER_SECRET",
        "TRAY_STORE_CODE",
        "TRAY_ADAPTER_TOKEN",
    )
    values = {name: os.getenv(name) for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise TrayConfigurationError(
            "Missing required Tray configuration: " + ", ".join(missing)
        )
    coupon_days = _int_env("TRAY_COUPON_VALID_DAYS", 180)
    return Settings(
        tray_api_base=values["TRAY_API_BASE"].rstrip("/"),
        tray_code=values["TRAY_CODE"],
        tray_consumer_key=values["TRAY_CONSUMER_KEY"],
        tray_consumer_secret=values["TRAY_CONSUMER_SECRET"],
        tray_coupon_valid_days=coupon_days,
        tray_store_code=values["TRAY_STORE_CODE"],
        tray_adapter_token=values["TRAY_ADAPTER_TOKEN"],
        tray_refresh_token=os.getenv("TRAY_REFRESH_TOKEN", "") or "",
        customer_birth_date_fallback=os.getenv(
            "CUSTOMER_BIRTH_DATE_FALLBACK", "1900-01-01"
        ),
        tray_webhook_token=(os.getenv("TRAY_WEBHOOK_TOKEN") or "").strip(),
        tray_rate_limit_per_minute=_int_env("TRAY_RATE_LIMIT_PER_MINUTE", 90),
        tray_rate_limit_per_day=_int_env("TRAY_RATE_LIMIT_PER_DAY", 4000),
    )
