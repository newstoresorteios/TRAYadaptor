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


def get_settings() -> Settings:
    names = (
        "TRAY_API_BASE",
        "TRAY_CODE",
        "TRAY_CONSUMER_KEY",
        "TRAY_CONSUMER_SECRET",
        "TRAY_STORE_CODE",
    )
    values = {name: os.getenv(name) for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise TrayConfigurationError(
            "Missing required Tray configuration: " + ", ".join(missing)
        )
    try:
        coupon_days = int(os.getenv("TRAY_COUPON_VALID_DAYS", "180"))
    except ValueError as exc:
        raise TrayConfigurationError("TRAY_COUPON_VALID_DAYS must be an integer") from exc
    return Settings(
        tray_api_base=values["TRAY_API_BASE"].rstrip("/"),
        tray_code=values["TRAY_CODE"],
        tray_consumer_key=values["TRAY_CONSUMER_KEY"],
        tray_consumer_secret=values["TRAY_CONSUMER_SECRET"],
        tray_coupon_valid_days=coupon_days,
        tray_store_code=values["TRAY_STORE_CODE"],
    )
