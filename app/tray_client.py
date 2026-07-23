from collections.abc import Callable
from typing import Any

import httpx

from .exceptions import TrayAPIError, TrayConnectionError
from .tray_auth import TrayAuth


class TrayClient:
    def __init__(self, auth: TrayAuth, http_client: httpx.AsyncClient | None = None):
        self.auth = auth
        self.http_client = http_client

    async def request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None,
        data: Any = None, json: Any = None, headers: dict[str, str] | None = None,
        retry_on_auth_failure: bool = True,
        request_observer: Callable[[], None] | None = None,
        response_observer: Callable[[dict[str, Any]], None] | None = None,
    ) -> Any:
        token = await self.auth.get_valid_token()
        for attempt in range(2):
            request_params = dict(params or {})
            request_params["access_token"] = token.access_token
            if request_observer:
                request_observer()
            try:
                if self.http_client:
                    response = await self.http_client.request(method, self._url(path), params=request_params, data=data, json=json, headers=headers, timeout=15.0)
                else:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        response = await client.request(method, self._url(path), params=request_params, data=data, json=json, headers=headers)
            except httpx.TimeoutException as exc:
                raise TrayConnectionError("Tray request timed out") from exc
            except httpx.RequestError as exc:
                raise TrayConnectionError("Could not connect to Tray") from exc
            diagnostics = (
                _safe_response_diagnostics(response)
                if response_observer or response.is_error
                else {}
            )
            if response_observer:
                response_observer(diagnostics)
            if response.status_code == 401 and attempt == 0 and retry_on_auth_failure:
                token = await self.auth.refresh()
                continue
            if response.is_error:
                raise TrayAPIError(
                    "Tray API request failed",
                    response.status_code,
                    diagnostics=diagnostics,
                )
            try:
                return response.json()
            except ValueError as exc:
                raise TrayAPIError("Tray returned an invalid response") from exc
        raise TrayAPIError("Tray API request failed")

    def _url(self, path: str) -> str:
        return f"{self.auth.settings.tray_api_base}/{path.lstrip('/')}"

    async def list_products(self, name: str | None = None, limit: int = 1) -> Any:
        params: dict[str, Any] = {"limit": min(max(limit, 1), 50)}
        if name:
            params["name"] = name
        return await self.request("GET", "/products", params=params)


def _safe_response_diagnostics(response: httpx.Response) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "status_code": response.status_code,
        "response_received": True,
        "response_is_json": False,
        "response_keys": [],
    }
    try:
        payload = response.json()
    except ValueError:
        return diagnostics

    diagnostics["response_is_json"] = True
    if not isinstance(payload, dict):
        return diagnostics

    diagnostics["response_keys"] = sorted(
        safe_key
        for key in payload
        if (safe_key := _safe_label(key)) is not None
    )
    for source, target in (
        ("code", "error_code"),
        ("name", "error_type"),
        ("type", "error_type"),
        ("field", "error_field"),
        ("attribute", "error_field"),
        ("property", "error_field"),
    ):
        safe_value = _safe_scalar(payload.get(source))
        if safe_value is not None and target not in diagnostics:
            diagnostics[target] = safe_value

    field_names = _error_field_names(payload)
    if field_names:
        diagnostics["error_fields"] = field_names
    error_message = _safe_error_message(payload.get("message"))
    if error_message is not None:
        diagnostics["error_message"] = error_message
    return diagnostics


def _safe_label(value: Any) -> str | None:
    text = str(value).strip()
    lowered = text.lower()
    if (
        not text
        or len(text) > 80
        or any(not (character.isalnum() or character in " _.-:") for character in text)
        or any(
            sensitive in lowered
            for sensitive in ("token", "authorization", "secret", "password", "url")
        )
    ):
        return None
    return text


def _safe_scalar(value: Any) -> str | int | float | bool | None:
    if not isinstance(value, (str, int, float, bool)):
        return None
    text = str(value).strip()
    lowered = text.lower()
    if (
        not text
        or len(text) > 80
        or any(not (character.isalnum() or character in " _.-:") for character in text)
        or "http://" in lowered
        or "https://" in lowered
        or "access_token" in lowered
        or "authorization" in lowered
    ):
        return None
    return value


def _safe_error_message(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    lowered = text.lower()
    if (
        not text
        or len(text) > 160
        or "@" in text
        or "http://" in lowered
        or "https://" in lowered
        or any(
            sensitive in lowered
            for sensitive in (
                "access_token",
                "authorization",
                "password",
                "secret",
                "session_id",
                "consumer_key",
                "consumer_secret",
            )
        )
    ):
        return None
    return text


def _error_field_names(payload: dict[str, Any]) -> list[str]:
    result: set[str] = set()
    for container_name in ("errors", "causes"):
        container = payload.get(container_name)
        if isinstance(container, dict):
            result.update(
                safe_key
                for key in container
                if (safe_key := _safe_label(key)) is not None
            )
        elif isinstance(container, list):
            for item in container:
                if not isinstance(item, dict):
                    continue
                for key in ("field", "attribute", "property"):
                    value = _safe_scalar(item.get(key))
                    safe_value = _safe_label(value) if value is not None else None
                    if safe_value is not None:
                        result.add(safe_value)
    return sorted(result)[:10]
