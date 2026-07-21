import pytest

from app.config import get_settings
from app.exceptions import TrayConfigurationError


def test_valid_config(monkeypatch):
    values = {"TRAY_API_BASE": "https://tray.test/", "TRAY_CODE": "c", "TRAY_CONSUMER_KEY": "k", "TRAY_CONSUMER_SECRET": "s", "TRAY_STORE_CODE": "687890"}
    for key, value in values.items(): monkeypatch.setenv(key, value)
    assert get_settings().tray_api_base == "https://tray.test"
    assert get_settings().tray_coupon_valid_days == 180


def test_missing_required_config(monkeypatch):
    monkeypatch.delenv("TRAY_CODE", raising=False)
    with pytest.raises(TrayConfigurationError): get_settings()
