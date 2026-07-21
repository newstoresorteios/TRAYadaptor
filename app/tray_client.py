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
    ) -> Any:
        token = await self.auth.get_valid_token()
        for attempt in range(2):
            request_params = dict(params or {})
            request_params["access_token"] = token.access_token
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
            if response.status_code == 401 and attempt == 0:
                token = await self.auth.refresh()
                continue
            if response.is_error:
                raise TrayAPIError("Tray API request failed", response.status_code)
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
