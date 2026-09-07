from fastapi.testclient import TestClient

from app import main
from app.webhooks import reset_webhooks_for_tests


def configure(monkeypatch, **extra):
    values = {
        "TRAY_API_BASE": "https://tray.test/web_api",
        "TRAY_CODE": "code",
        "TRAY_CONSUMER_KEY": "key",
        "TRAY_CONSUMER_SECRET": "secret",
        "TRAY_STORE_CODE": "687890",
        "TRAY_ADAPTER_TOKEN": "adapter-token",
        **extra,
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def test_tray_webhook_accepts_form_and_dedups(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr("app.webhooks._database_url", lambda: "")
    reset_webhooks_for_tests()
    client = TestClient(main.app)
    payload = {
        "seller_id": "687890",
        "scope_name": "order",
        "scope_id": "55",
        "act": "update",
        "app_code": "app",
    }
    first = client.post("/webhooks/tray", data=payload)
    second = client.post("/webhooks/tray", data=payload)
    assert first.status_code == 200
    assert first.json()["accepted"] is True
    assert first.json()["duplicate"] is False
    assert second.status_code == 200
    assert second.json()["duplicate"] is True

    listed = client.get(
        "/internal/webhooks/events",
        headers={"Authorization": "Bearer adapter-token"},
    )
    assert listed.status_code == 200
    events = listed.json()["events"]
    assert events[0]["scope_id"] == "55"
    assert events[0]["scope_name"] == "order"
    assert events[0]["id"] == 1

    newer = client.get(
        "/internal/webhooks/events?since_id=1",
        headers={"Authorization": "Bearer adapter-token"},
    )
    assert newer.status_code == 200
    assert newer.json()["events"] == []


def test_tray_webhook_ignores_other_seller_and_requires_optional_token(monkeypatch):
    configure(monkeypatch, TRAY_WEBHOOK_TOKEN="hook-secret")
    monkeypatch.setattr("app.webhooks._database_url", lambda: "")
    reset_webhooks_for_tests()
    client = TestClient(main.app)
    denied = client.post(
        "/webhooks/tray",
        data={
            "seller_id": "687890",
            "scope_name": "order",
            "scope_id": "1",
            "act": "insert",
        },
    )
    assert denied.status_code == 401

    accepted = client.post(
        "/webhooks/tray?token=hook-secret",
        data={
            "seller_id": "999",
            "scope_name": "order",
            "scope_id": "1",
            "act": "insert",
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["accepted"] is False
    assert accepted.json()["reason"] == "seller_id_mismatch"


def test_tray_webhook_since_id_returns_newer_events_ascending(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setattr("app.webhooks._database_url", lambda: "")
    reset_webhooks_for_tests()
    client = TestClient(main.app)
    headers = {"Authorization": "Bearer adapter-token"}
    first = client.post(
        "/webhooks/tray",
        data={"seller_id": "687890", "scope_name": "product", "scope_id": "10", "act": "update"},
    )
    second = client.post(
        "/webhooks/tray",
        data={"seller_id": "687890", "scope_name": "product", "scope_id": "11", "act": "update"},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    listed = client.get("/internal/webhooks/events?since_id=1", headers=headers)
    events = listed.json()["events"]
    assert [item["scope_id"] for item in events] == ["11"]
    assert events[0]["id"] == 2
