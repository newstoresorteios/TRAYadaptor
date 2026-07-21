from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .config import Settings
from .exceptions import TrayAPIError, TrayAuthenticationError, TrayConnectionError


@dataclass
class TokenState:
    access_token: str
    refresh_token: str
    access_expires_at: datetime | None
    refresh_expires_at: datetime | None
    api_host: str | None
    store_id: str

    def access_is_valid(self) -> bool:
        return bool(self.access_token) and (
            self.access_expires_at is None
            or self.access_expires_at > datetime.now(timezone.utc) + timedelta(seconds=30)
        )


class TrayAuth:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None):
        self.settings = settings
        self.http_client = http_client
        self.state: TokenState | None = None

    async def authenticate(self) -> TokenState:
        payload = {
            "consumer_key": self.settings.tray_consumer_key,
            "consumer_secret": self.settings.tray_consumer_secret,
            "code": self.settings.tray_code,
        }
        response = await self._post_auth(payload)
        self.state = self._parse_token_response(response)
        return self.state

    async def refresh(self) -> TokenState:
        if not self.state or not self.state.refresh_token:
            raise TrayAuthenticationError("No refresh token available")
        payload = {
            "consumer_key": self.settings.tray_consumer_key,
            "consumer_secret": self.settings.tray_consumer_secret,
            "refresh_token": self.state.refresh_token,
        }
        response = await self._post_auth(payload)
        self.state = self._parse_token_response(response)
        return self.state

    async def get_valid_token(self) -> TokenState:
        if self.state and self.state.access_is_valid():
            return self.state
        if self.state and self.state.refresh_token:
            try:
                return await self.refresh()
            except TrayError:
                self.state = None
        return await self.authenticate()

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
            raise TrayAuthenticationError("Tray authentication failed")
        try:
            body = response.json()
        except ValueError as exc:
            raise TrayAuthenticationError("Tray returned a non-JSON authentication response") from exc
        if not isinstance(body, dict):
            raise TrayAuthenticationError("Tray returned an invalid authentication response")
        return body

    def _parse_token_response(self, body: dict[str, Any]) -> TokenState:
        access = body.get("access_token")
        refresh = body.get("refresh_token")
        store_id = body.get("store_id")
        if not access or not refresh:
            raise TrayAuthenticationError("Tray authentication did not return required tokens")
        if store_id is None or str(store_id) != str(self.settings.tray_store_code):
            raise TrayAuthenticationError("Tray store validation failed")
        return TokenState(
            access_token=str(access),
            refresh_token=str(refresh),
            access_expires_at=_expiry(body, "expires_in", "access_token_expires_in"),
            refresh_expires_at=_expiry(body, "refresh_expires_in", "refresh_token_expires_in"),
            api_host=str(body["api_host"]) if body.get("api_host") else None,
            store_id=str(store_id),
        )


def _expiry(body: dict[str, Any], *keys: str) -> datetime | None:
    for key in keys:
        if body.get(key) is not None:
            try:
                return datetime.now(timezone.utc) + timedelta(seconds=int(body[key]))
            except (TypeError, ValueError):
                return None
    return None


# Kept local to avoid making refresh failure handling depend on implementation details.
from .exceptions import TrayError  # noqa: E402
