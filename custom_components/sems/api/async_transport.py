"""aiohttp transport adapter for Home Assistant-hosted SEMS calls."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import aiohttp
import requests


class AioHttpResponseAdapter:
    """Compatibility adapter for the existing SEMS response handling."""

    def __init__(
        self,
        status_code: int,
        headers: Mapping[str, str],
        url: str,
        text: str,
        payload: Any,
    ) -> None:
        self.status_code = status_code
        self.headers = headers
        self.url = url
        self.text = text
        self._payload = payload

    def json(self) -> Any:
        """Return the parsed JSON payload or raise for invalid JSON."""
        if self._payload is not None:
            return self._payload
        if not self.text:
            raise ValueError("Empty response body")
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        """Raise an HTTPError for unsuccessful response statuses."""
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            response.headers.update(dict(self.headers))
            response.url = self.url
            response._content = self.text.encode()
            raise requests.HTTPError(
                f"HTTP {self.status_code}",
                response=response,
            )


class AsyncSemsTransport:
    """HA-injected aiohttp transport for synchronous compatibility callers."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def request(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        data: str | None,
        json_data: dict[str, Any] | None,
    ) -> AioHttpResponseAdapter:
        """Execute one bounded aiohttp request."""
        async with self._session.request(
            method.upper(),
            url,
            headers=headers,
            data=data,
            json=json_data,
            timeout=aiohttp.ClientTimeout(total=30),
            allow_redirects=False,
        ) as response:
            text = await response.text()
            payload: Any = None
            if text:
                try:
                    payload = await response.json(content_type=None)
                except aiohttp.ContentTypeError, json.JSONDecodeError, ValueError:
                    payload = None
            return AioHttpResponseAdapter(
                status_code=response.status,
                headers=dict(response.headers),
                url=str(response.url),
                text=text,
                payload=payload,
            )
