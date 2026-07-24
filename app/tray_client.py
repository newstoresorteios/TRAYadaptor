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
        follow_redirects: bool | None = None,
        reject_redirects: bool = False,
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
                request_options = {
                    "params": request_params,
                    "data": data,
                    "json": json,
                    "headers": headers,
                    "timeout": 15.0,
                }
                if follow_redirects is not None:
                    request_options["follow_redirects"] = follow_redirects
                if self.http_client:
                    response = await self.http_client.request(
                        method, self._url(path), **request_options
                    )
                else:
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        response = await client.request(
                            method, self._url(path), **request_options
                        )
            except httpx.TimeoutException as exc:
                raise TrayConnectionError("Tray request timed out") from exc
            except httpx.RequestError as exc:
                raise TrayConnectionError("Could not connect to Tray") from exc
            diagnostics = (
                _safe_response_diagnostics(response)
                if response_observer or response.is_error or response.is_redirect
                else {}
            )
            if response_observer:
                response_observer(diagnostics)
            if response.status_code == 401 and attempt == 0 and retry_on_auth_failure:
                token = await self.auth.refresh()
                continue
            if response.is_error or (reject_redirects and response.is_redirect):
                raise TrayAPIError(
                    "Tray API request failed",
                    response.status_code,
                    diagnostics=diagnostics,
                )
            try:
                return response.json()
            except ValueError as exc:
                invalid_diagnostics = (
                    diagnostics or _safe_response_diagnostics(response)
                )
                invalid_diagnostics["invalid_response"] = True
                raise TrayAPIError(
                    "Tray returned an invalid response",
                    response.status_code,
                    diagnostics=invalid_diagnostics,
                ) from exc
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
        "content_type": _safe_content_type(response.headers.get("content-type")),
        "final_url_path": response.url.path,
        "redirect_count": len(response.history),
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
        ("name", "error_name"),
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
    diagnostics["error_causes"] = _safe_causes(payload.get("causes"))
    error_message = _safe_error_message(payload.get("message"))
    if error_message is None:
        error_message = _safe_nested_error_message(payload)
    if error_message is not None:
        diagnostics["error_message"] = error_message
    return diagnostics


def _safe_content_type(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    media_type = value.split(";", 1)[0].strip().lower()
    if (
        not media_type
        or len(media_type) > 80
        or any(
            not (character.isalnum() or character in "/+.-")
            for character in media_type
        )
    ):
        return None
    return media_type


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
        or any(
            sensitive in lowered
            for sensitive in (
                "token",
                "authorization",
                "secret",
                "password",
                "consumer_key",
            )
        )
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
                "token",
                "authorization",
                "password",
                "secret",
                "consumer_key",
                "consumer_secret",
            )
        )
    ):
        return None
    if "session_id" in lowered:
        if "missing" in lowered or "required" in lowered:
            return "missing field: session_id"
        if "invalid" in lowered:
            return "invalid field: session_id"
        return None
    return text


def _safe_nested_error_message(payload: dict[str, Any]) -> str | None:
    for container_name in ("causes", "errors"):
        container = payload.get(container_name)
        candidates: list[Any]
        if isinstance(container, dict):
            candidates = list(container.values())
        elif isinstance(container, list):
            candidates = container
        else:
            candidates = [container]
        for candidate in candidates:
            if isinstance(candidate, dict):
                for key in ("message", "name", "error"):
                    safe_message = _safe_error_message(candidate.get(key))
                    if safe_message is not None:
                        return safe_message
            else:
                safe_message = _safe_error_message(candidate)
                if safe_message is not None:
                    return safe_message
    return None


def _safe_causes(value: Any) -> list[Any]:
    result: list[Any] = []

    def append(candidate: Any, field: str | None = None) -> None:
        if len(result) >= 10:
            return
        if isinstance(candidate, str):
            safe_message = _safe_error_message(candidate)
            if safe_message is not None:
                if field is None:
                    result.append(safe_message)
                else:
                    result.append({"field": field, "message": safe_message})
            return
        if isinstance(candidate, list):
            for item in candidate:
                append(item, field)
            return
        if not isinstance(candidate, dict):
            return

        known_keys = {
            "code", "name", "type", "field", "attribute",
            "property", "message", "error",
        }
        if any(key in candidate for key in known_keys):
            safe_cause: dict[str, Any] = {}
            for key in ("code", "name", "type"):
                safe_value = _safe_scalar(candidate.get(key))
                if safe_value is not None:
                    safe_cause[key] = safe_value
            for key in ("field", "attribute", "property"):
                safe_value = _safe_label(candidate.get(key))
                if safe_value is not None:
                    safe_cause["field"] = safe_value
                    break
            for key in ("message", "error"):
                safe_message = _safe_error_message(candidate.get(key))
                if safe_message is not None:
                    safe_cause["message"] = safe_message
                    break
            if field is not None and "field" not in safe_cause:
                safe_cause["field"] = field
            if safe_cause:
                result.append(safe_cause)
            return

        for raw_field, nested in candidate.items():
            safe_field = _safe_label(raw_field)
            if safe_field is not None:
                append(nested, safe_field)

    append(value)
    return result


def _error_field_names(payload: dict[str, Any]) -> list[str]:
    result: set[str] = set()
    for container_name in ("errors", "causes"):
        container = payload.get(container_name)
        if isinstance(container, dict):
            explicit_fields = {
                safe_value
                for key in ("field", "attribute", "property")
                if (
                    (raw_value := container.get(key)) is not None
                    and (safe_value := _safe_label(raw_value)) is not None
                )
            }
            if explicit_fields:
                result.update(explicit_fields)
            elif not any(
                key in container
                for key in ("code", "name", "type", "message", "error")
            ):
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
