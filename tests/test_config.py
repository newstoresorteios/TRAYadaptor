import pytest

from app.config import get_settings
from app.exceptions import TrayConfigurationError


def test_valid_config(monkeypatch):
    values = {"TRAY_API_BASE": "https://tray.test/", "TRAY_CODE": "c", "TRAY_CONSUMER_KEY": "k", "TRAY_CONSUMER_SECRET": "s", "TRAY_STORE_CODE": "687890", "TRAY_ADAPTER_TOKEN": "adapter-token"}
    for key, value in values.items(): monkeypatch.setenv(key, value)
    assert get_settings().tray_api_base == "https://tray.test"
    assert get_settings().tray_coupon_valid_days == 180


def test_missing_required_config(monkeypatch):
    monkeypatch.delenv("TRAY_CODE", raising=False)
    with pytest.raises(TrayConfigurationError): get_settings()


def _primary(monkeypatch):
    values = {
        "TRAY_API_BASE": "https://www.example.test/web_api",
        "TRAY_CODE": "c",
        "TRAY_CONSUMER_KEY": "k",
        "TRAY_CONSUMER_SECRET": "s",
        "TRAY_STORE_CODE": "687890",
        "TRAY_ADAPTER_TOKEN": "adapter-token",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    for key in ("TRAY2_STORE_CODE", "TRAY2_API_BASE", "TRAY2_CODE", "TRAY2_REFRESH_TOKEN"):
        monkeypatch.delenv(key, raising=False)


def test_second_store_reuses_app_credentials(monkeypatch):
    from app.config import configured_stores

    _primary(monkeypatch)
    monkeypatch.setenv("TRAY2_STORE_CODE", "1490060")
    monkeypatch.setenv("TRAY2_API_BASE", "https://loja-nova.test/web_api/")
    monkeypatch.setenv("TRAY2_CODE", "install-code")
    stores = configured_stores()
    assert set(stores) == {"687890", "1490060"}
    second = stores["1490060"]
    assert second.tray_api_base == "https://loja-nova.test/web_api"
    assert second.tray_code == "install-code"
    assert second.tray_consumer_key == "k"
    assert second.tray_consumer_secret == "s"
    assert stores["687890"].tray_api_base == "https://www.example.test/web_api"


def test_request_store_selects_second_credentials(monkeypatch):
    from fastapi import HTTPException

    from app import main

    _primary(monkeypatch)
    monkeypatch.setenv("TRAY2_STORE_CODE", "1490060")
    monkeypatch.setenv("TRAY2_API_BASE", "https://loja-nova.test/web_api")
    monkeypatch.setenv("TRAY2_CODE", "install-code")
    main._clients.clear()
    token = main._store_scope.set("1490060")
    try:
        selected = main._client()
    finally:
        main._store_scope.reset(token)
    assert selected.auth.settings.tray_store_code == "1490060"
    assert selected.auth.settings.tray_api_base == "https://loja-nova.test/web_api"
    assert main._client().auth.settings.tray_store_code == "687890"

    rejected = main._store_scope.set("000")
    try:
        with pytest.raises(HTTPException) as error:
            main._client()
    finally:
        main._store_scope.reset(rejected)
    assert error.value.status_code == 404


def test_second_store_requires_its_own_host(monkeypatch):
    from app.config import configured_stores

    _primary(monkeypatch)
    monkeypatch.setenv("TRAY2_STORE_CODE", "1490060")
    with pytest.raises(TrayConfigurationError):
        configured_stores()
