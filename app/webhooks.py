"""Inbound Tray notifications (application/x-www-form-urlencoded)."""

from __future__ import annotations

import hmac
import logging
import os
from collections import deque
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_DEDUP_SECONDS = 120
_MAX_EVENTS = 100
_events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
_recent_keys: dict[tuple[str, str, str, str], float] = {}
_memory_seq = 0


def reset_webhooks_for_tests() -> None:
    global _memory_seq
    _events.clear()
    _recent_keys.clear()
    _memory_seq = 0


def _database_url() -> str:
    return (
        os.getenv("DATABASE_URL") or os.getenv("TRAY_TOKEN_DATABASE_URL") or ""
    ).strip()


def ensure_webhook_table() -> None:
    url = _database_url()
    if not url:
        return
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public.tray_webhook_events (
                        id bigserial PRIMARY KEY,
                        seller_id text NOT NULL,
                        scope_name text NOT NULL,
                        scope_id text NOT NULL,
                        act text NOT NULL,
                        app_code text,
                        received_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE INDEX IF NOT EXISTS tray_webhook_events_received_at_idx
                    ON public.tray_webhook_events (received_at DESC)
                    """
                )
            conn.commit()
    except Exception as exc:
        logger.warning("tray_webhook_events ensure table failed: %s", exc)


def webhook_token_matches(supplied: str, expected: str) -> bool:
    if not expected:
        return True
    if len(supplied) != len(expected):
        hmac.compare_digest(expected, expected)
        return False
    return hmac.compare_digest(supplied, expected)


def ingest_tray_notification(
    *,
    seller_id: str,
    scope_name: str,
    scope_id: str,
    act: str,
    app_code: str = "",
    expected_seller_id: str = "",
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    stamp = now.timestamp()
    _prune_recent(stamp)

    if expected_seller_id and str(seller_id) != str(expected_seller_id):
        logger.info(
            "tray.webhook ignored seller_id_mismatch scope_name=%s act=%s",
            _safe_label(scope_name),
            _safe_label(act),
        )
        return {"accepted": False, "reason": "seller_id_mismatch", "duplicate": False}

    global _memory_seq
    key = (str(seller_id), str(scope_name), str(scope_id), str(act))
    duplicate = key in _recent_keys
    _memory_seq += 1
    event = {
        "id": _memory_seq,
        "seller_id": str(seller_id),
        "scope_name": str(scope_name),
        "scope_id": str(scope_id),
        "act": str(act),
        "app_code": str(app_code or ""),
        "received_at": now.isoformat(),
        "duplicate": duplicate,
    }
    if duplicate:
        logger.info(
            "tray.webhook duplicate scope_name=%s act=%s",
            _safe_label(scope_name),
            _safe_label(act),
        )
        return {"accepted": True, "reason": "duplicate", "duplicate": True}

    _recent_keys[key] = stamp
    persisted_id = _persist_event(event)
    if persisted_id is not None:
        event["id"] = int(persisted_id)
    _events.appendleft(event)
    logger.info(
        "tray.webhook accepted scope_name=%s act=%s",
        _safe_label(scope_name),
        _safe_label(act),
    )
    return {"accepted": True, "reason": "stored", "duplicate": False}


def list_recent_events(
    limit: int = 50, since_id: int | None = None
) -> list[dict[str, Any]]:
    limit = min(max(int(limit), 1), _MAX_EVENTS)
    persisted = _load_persisted_events(limit, since_id=since_id)
    if persisted:
        return persisted[:limit]
    events = list(_events)
    if since_id is not None:
        newer = [
            event
            for event in reversed(events)
            if int(event.get("id") or 0) > int(since_id)
        ]
        return newer[:limit]
    return events[:limit]


def _prune_recent(now_ts: float) -> None:
    expired = [
        key for key, seen_at in _recent_keys.items() if now_ts - seen_at > _DEDUP_SECONDS
    ]
    for key in expired:
        _recent_keys.pop(key, None)


def _persist_event(event: dict[str, Any]) -> int | None:
    url = _database_url()
    if not url:
        return None
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.tray_webhook_events (
                        seller_id, scope_name, scope_id, act, app_code, received_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        event["seller_id"],
                        event["scope_name"],
                        event["scope_id"],
                        event["act"],
                        event.get("app_code") or None,
                        datetime.fromisoformat(event["received_at"]),
                    ),
                )
                row = cur.fetchone()
            conn.commit()
        return int(row[0]) if row else None
    except Exception as exc:
        logger.warning("tray_webhook_events persist failed: %s", exc)
        return None


def _row_to_event(row: Any) -> dict[str, Any]:
    received_at = row[6]
    return {
        "id": int(row[0]) if row[0] is not None else None,
        "seller_id": str(row[1] or ""),
        "scope_name": str(row[2] or ""),
        "scope_id": str(row[3] or ""),
        "act": str(row[4] or ""),
        "app_code": str(row[5] or ""),
        "received_at": (
            received_at.isoformat()
            if hasattr(received_at, "isoformat")
            else str(received_at)
        ),
        "duplicate": False,
    }


def _load_persisted_events(
    limit: int, since_id: int | None = None
) -> list[dict[str, Any]]:
    url = _database_url()
    if not url:
        return []
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                if since_id is None:
                    cur.execute(
                        """
                        SELECT id, seller_id, scope_name, scope_id, act, app_code, received_at
                        FROM public.tray_webhook_events
                        ORDER BY id DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id, seller_id, scope_name, scope_id, act, app_code, received_at
                        FROM public.tray_webhook_events
                        WHERE id > %s
                        ORDER BY id ASC
                        LIMIT %s
                        """,
                        (int(since_id), limit),
                    )
                rows = cur.fetchall()
        return [_row_to_event(row) for row in rows]
    except Exception as exc:
        logger.warning("tray_webhook_events load failed: %s", exc)
        return []


def _safe_label(value: Any) -> str:
    text = str(value or "").strip()[:40]
    if any(
        marker in text.lower()
        for marker in ("token", "secret", "password", "http://", "https://")
    ):
        return "redacted"
    return text or "unknown"
