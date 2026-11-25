"""MOCK transport for the Power BI REST client. Routes (method, path) to canned
responses copied from the documented response shapes (TECHNICAL_VALIDATION.md §7).
This is NOT a live Power BI integration."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse


class FakeResponse:
    def __init__(self, status: int, body: Any = None, headers: dict[str, str] | None = None) -> None:
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.content = b"" if body is None else json.dumps(body).encode()
        self.text = self.content.decode()

    def json(self) -> Any:
        if self._body is None:
            raise ValueError("no body")
        return self._body


class FakeSession:
    """routes: {(METHOD, path): FakeResponse | list[FakeResponse | Exception]}"""

    def __init__(self, routes: dict[tuple[str, str], Any]) -> None:
        self.routes = routes
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, headers=None, timeout=None, params=None, json=None):
        path = urlparse(url).path.replace("/v1.0/myorg", "", 1)
        self.calls.append({"method": method, "path": path, "params": params, "json": json, "headers": headers})
        route = self.routes.get((method, path))
        if route is None:
            return FakeResponse(404, {"error": {"code": "NotFound", "message": "no route"}})
        if isinstance(route, list):
            item = route.pop(0) if len(route) > 1 else route[0]
        else:
            item = route
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return item(params=params, json=json)
        return item
