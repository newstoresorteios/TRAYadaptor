"""Optional Postgres cache so Tray OAuth survives restarts and multi-instance deploys."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _database_url() -> str:
    return (os.getenv("DATABASE_URL") or os.getenv("TRAY_TOKEN_DATABASE_URL") or "").strip()


def _store_id(settings: Any) -> str:
    return str(getattr(settings, "tray_store_code", "") or "").strip()


def load_token_state(settings: Any) -> dict[str, Any] | None:
    url = _database_url()
    store_id = _store_id(settings)
    if not url or not store_id:
        return None
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT access_token, refresh_token, access_expires_at
                    FROM public.tray_oauth_cache
                    WHERE store_id = %s
                    LIMIT 1
                    """,
                    (store_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        access_token, refresh_token, access_expires_at = row
        if not refresh_token:
            return None
        return {
            "access_token": str(access_token or ""),
            "refresh_token": str(refresh_token or ""),
            "access_expires_at": access_expires_at,
        }
    except Exception as exc:
        logger.warning("tray_oauth_cache load failed: %s", exc)
        return None


def save_token_state(
    settings: Any,
    *,
    access_token: str,
    refresh_token: str,
    access_expires_at: datetime | None,
) -> None:
    url = _database_url()
    store_id = _store_id(settings)
    if not url or not store_id or not refresh_token:
        return
    try:
        import psycopg

        now = datetime.now(timezone.utc)
        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.tray_oauth_cache (
                        store_id,
                        access_token,
                        refresh_token,
                        access_expires_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (store_id) DO UPDATE SET
                        access_token = EXCLUDED.access_token,
                        refresh_token = EXCLUDED.refresh_token,
                        access_expires_at = EXCLUDED.access_expires_at,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        store_id,
                        access_token,
                        refresh_token,
                        access_expires_at,
                        now,
                    ),
                )
            conn.commit()
    except Exception as exc:
        logger.warning("tray_oauth_cache save failed: %s", exc)


def ensure_token_table() -> None:
    url = _database_url()
    if not url:
        return
    try:
        import psycopg

        with psycopg.connect(url, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS public.tray_oauth_cache (
                        store_id text PRIMARY KEY,
                        access_token text NOT NULL DEFAULT '',
                        refresh_token text NOT NULL,
                        access_expires_at timestamptz,
                        updated_at timestamptz NOT NULL DEFAULT now()
                    )
                    """
                )
            conn.commit()
    except Exception as exc:
        logger.warning("tray_oauth_cache ensure table failed: %s", exc)
