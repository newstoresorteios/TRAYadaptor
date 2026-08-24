import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .config import Settings
from .exceptions import TrayAPIError, TrayAuthenticationError, TrayConnectionError
from .tray_token_store import load_token_state, save_token_state

logger = logging.getLogger(__name__)

_REFRESH_AHEAD_SECONDS = 300


@dataclass
class TokenState:
    access_token: str
    refresh_token: str
    access_expires_at: datetime | None
    refresh_expires_at: datetime | None
    api_host: str | None
    store_id: str

    def access_is_valid(self, *, skew_seconds: int = 30) -> bool:
        return bool(self.access_token) and (
            self.access_expires_at is None
            or self.access_expires_at
            > datetime.now(timezone.utc) + timedelta(seconds=skew_seconds)
        )

    def should_refresh_proactively(self) -> bool:
        if not self.access_token or not self.refresh_token:
            return True
        if self.access_expires_at is None:
            return False
        return self.access_expires_at <= datetime.now(timezone.utc) + timedelta(
            seconds=_REFRESH_AHEAD_SECONDS
        )


class TrayAuth:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.http_client = http_client
        self.state: TokenState | None = None
        self._lock = asyncio.Lock()
        self._bootstrap_refresh_configured = bool(
            (getattr(settings, "tray_refresh_token", "") or "").strip()
        )

    async def authenticate(self) -> TokenState:
        payload = {
            "consumer_key": self.settings.tray_consumer_key,
            "consumer_secret": self.settings.tray_consumer_secret,
            "code": self.settings.tray_code,
        }
        response = await self._post_auth(payload)
        self.state = self._parse_token_response(response)
        self._persist_state(self.state)
        return self.state

    async def refresh(self) -> TokenState:
        if not self.state or not self.state.refresh_token:
            raise TrayAuthenticationError("No refresh token available")
        params = {
            "consumer_key": self.settings.tray_consumer_key,
            "consumer_secret": self.settings.tray_consumer_secret,
            "refresh_token": self.state.refresh_token,
        }
        try:
            if self.http_client:
                response = await self.http_client.get(
                    f"{self.settings.tray_api_base}/auth", params=params, timeout=15.0
                )
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.get(
                        f"{self.settings.tray_api_base}/auth", params=params
                    )
        except httpx.TimeoutException as exc:
            raise TrayConnectionError("Tray token refresh timed out") from exc
        except httpx.RequestError as exc:
            raise TrayConnectionError("Could not connect to Tray") from exc
        if response.is_error:
            raise TrayAuthenticationError(
                f"Tray token refresh failed status={response.status_code}"
            )
        try:
            response_body = response.json()
        except ValueError as exc:
            raise TrayAuthenticationError(
                "Tray returned a non-JSON refresh response"
            ) from exc
        if not isinstance(response_body, dict):
            raise TrayAuthenticationError("Tray returned an invalid refresh response")
        self.state = self._parse_token_response(response_body)
        self._persist_state(self.state)
        return self.state

    async def get_valid_token(self) -> TokenState:
        async with self._lock:
            if self.state and self.state.access_is_valid() and not self.state.should_refresh_proactively():
                return self.state

            cached = load_token_state(self.settings)
            if cached and not self.state:
                self.state = TokenState(
                    access_token=str(cached.get("access_token") or ""),
                    refresh_token=str(cached.get("refresh_token") or ""),
                    access_expires_at=cached.get("access_expires_at"),
                    refresh_expires_at=None,
                    api_host=None,
                    store_id=str(self.settings.tray_store_code),
                )

            if self.state and self.state.access_is_valid() and not self.state.should_refresh_proactively():
                return self.state

            if self.state and self.state.refresh_token:
                try:
                    return await self.refresh()
                except TrayError as exc:
                    logger.warning(
                        "Tray refresh failed; will re-authenticate if needed: %s",
                        exc,
                    )
                    if self.state.access_is_valid():
                        return self.state
                    self.state = None

            bootstrap = (getattr(self.settings, "tray_refresh_token", "") or "").strip()
            if bootstrap and not self.state:
                self.state = TokenState(
                    access_token="",
                    refresh_token=bootstrap,
                    access_expires_at=None,
                    refresh_expires_at=None,
                    api_host=None,
                    store_id=str(self.settings.tray_store_code),
                )
                try:
                    return await self.refresh()
                except TrayError as exc:
                    logger.warning("Tray bootstrap refresh failed: %s", exc)
                    self.state = None

            if cached and cached.get("refresh_token") and not self.state:
                self.state = TokenState(
                    access_token="",
                    refresh_token=str(cached["refresh_token"]),
                    access_expires_at=None,
                    refresh_expires_at=None,
                    api_host=None,
                    store_id=str(self.settings.tray_store_code),
                )
                try:
                    return await self.refresh()
                except TrayError as exc:
                    logger.warning("Tray cached refresh failed: %s", exc)
                    self.state = None

            state = await self.authenticate()
            if not self._bootstrap_refresh_configured:
                logger.warning(
                    "TRAY_REFRESH_TOKEN is not configured; OAuth may fail after restart. "
                    "Copy the refresh token from a successful auth into Render env vars."
                )
            return state

    async def _post_auth(self, payload: dict[str, str]) -> dict[str, Any]:
        try:
            if self.http_client:
                response = await self.http_client.post(
                    f"{self.settings.tray_api_base}/auth", data=payload, timeout=15.0
                )
            else:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    response = await client.post(
                        f"{self.settings.tray_api_base}/auth", data=payload
                    )
        except httpx.TimeoutException as exc:
            raise TrayConnectionError("Tray authentication timed out") from exc
        except httpx.RequestError as exc:
            raise TrayConnectionError("Could not connect to Tray") from exc
        if response.is_error:
            raise TrayAuthenticationError(
                f"Tray authentication failed status={response.status_code}"
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise TrayAuthenticationError(
                "Tray returned a non-JSON authentication response"
            ) from exc
        if not isinstance(body, dict):
            raise TrayAuthenticationError(
                "Tray returned an invalid authentication response"
            )
        return body

    def _parse_token_response(self, body: dict[str, Any]) -> TokenState:
        access = body.get("access_token")
        refresh = body.get("refresh_token")
        store_id = body.get("store_id")
        if not access or not refresh:
            raise TrayAuthenticationError(
                "Tray authentication did not return required tokens"
            )
        if store_id is None or str(store_id) != str(self.settings.tray_store_code):
            raise TrayAuthenticationError("Tray store validation failed")
        return TokenState(
            access_token=str(access),
            refresh_token=str(refresh),
            access_expires_at=_expiry(body, "expires_in", "access_token_expires_in"),
            refresh_expires_at=_expiry(
                body, "refresh_expires_in", "refresh_token_expires_in"
            ),
            api_host=str(body["api_host"]) if body.get("api_host") else None,
            store_id=str(store_id),
        )

    def _persist_state(self, state: TokenState) -> None:
        save_token_state(
            self.settings,
            access_token=state.access_token,
            refresh_token=state.refresh_token,
            access_expires_at=state.access_expires_at,
        )


def _expiry(body: dict[str, Any], *keys: str) -> datetime | None:
    for key in keys:
        if body.get(key) is not None:
            try:
                return datetime.now(timezone.utc) + timedelta(seconds=int(body[key]))
            except (TypeError, ValueError):
                return None
    return None


from .exceptions import TrayError  # noqa: E402
