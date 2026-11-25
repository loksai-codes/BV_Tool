"""Read-only Power BI REST client with safe retries.

Read-only enforcement: only GET is allowed, plus POST to an explicit allow-list
of read-only endpoints (executeQueries, GenerateToken with view-only payload).
Any other method/path raises ``ReadOnlyViolation`` before a request is sent.
"""
from __future__ import annotations

import random
import re
import time
from enum import Enum
from typing import Any, Callable

import requests

from core.security import get_logger, sanitize

log = get_logger("powerbi.http")

_READ_ONLY_POSTS = [
    re.compile(r"^/groups/[0-9a-fA-F-]{36}/datasets/[0-9a-fA-F-]{36}/executeQueries$"),
    re.compile(r"^/GenerateToken$"),
]
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ErrorCategory(str, Enum):
    AUTH_EXPIRED = "AUTH_EXPIRED"
    PERMISSION = "PERMISSION"
    NOT_FOUND = "NOT_FOUND"
    THROTTLED = "THROTTLED"
    NETWORK = "NETWORK"
    INVALID_INPUT = "INVALID_INPUT"
    SERVER = "SERVER"
    UNKNOWN = "UNKNOWN"


_FRIENDLY = {
    ErrorCategory.AUTH_EXPIRED: "Authentication expired or invalid. Please sign in again.",
    ErrorCategory.PERMISSION: "Access denied. Check workspace role / report permissions (and that permissions have propagated).",
    ErrorCategory.NOT_FOUND: "Not found. The workspace or report ID may be invalid, deleted, or not visible to this identity.",
    ErrorCategory.THROTTLED: "Power BI API throttled the request. Retries were exhausted; try again later.",
    ErrorCategory.NETWORK: "Network failure contacting Power BI.",
    ErrorCategory.INVALID_INPUT: "The request was rejected as invalid.",
    ErrorCategory.SERVER: "Power BI service error.",
    ErrorCategory.UNKNOWN: "Unexpected Power BI API error.",
}


class ReadOnlyViolation(RuntimeError):
    pass


class PowerBIApiError(Exception):
    def __init__(
        self,
        category: ErrorCategory,
        status_code: int | None = None,
        code: str | None = None,
        detail: str | None = None,
        request_id: str | None = None,
    ) -> None:
        self.category = category
        self.status_code = status_code
        self.code = code
        self.detail = sanitize(detail or "")[:500]
        self.request_id = request_id
        super().__init__(self.friendly)

    @property
    def friendly(self) -> str:
        parts = [_FRIENDLY[self.category]]
        if self.status_code:
            parts.append(f"(HTTP {self.status_code}{', ' + self.code if self.code else ''})")
        if self.request_id:
            parts.append(f"RequestId={self.request_id}")
        return " ".join(parts)


def categorize(status: int) -> ErrorCategory:
    if status == 401:
        return ErrorCategory.AUTH_EXPIRED
    if status == 403:
        return ErrorCategory.PERMISSION
    if status == 404:
        return ErrorCategory.NOT_FOUND
    if status == 429:
        return ErrorCategory.THROTTLED
    if status == 400:
        return ErrorCategory.INVALID_INPUT
    if status >= 500:
        return ErrorCategory.SERVER
    return ErrorCategory.UNKNOWN


class PowerBIHttpClient:
    def __init__(
        self,
        base_url: str,
        token_provider: Callable[[], str],
        refresh_token: Callable[[], str] | None = None,
        session: requests.Session | None = None,
        max_retries: int = 4,
        timeout: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        max_backoff: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = token_provider
        self._refresh = refresh_token
        self.session = session or requests.Session()
        self.max_retries = max_retries
        self.timeout = timeout
        self._sleep = sleep
        self.max_backoff = max_backoff

    # ------------------------------------------------------------------ public
    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._request("GET", path, params=params)

    def get_all(self, path: str, page_size: int | None = None) -> list[dict[str, Any]]:
        """Fetch a collection. Uses $top/$skip only when ``page_size`` is given (documented for /groups)."""
        if not page_size:
            return list(self.get(path).get("value", []))
        out: list[dict[str, Any]] = []
        skip = 0
        while True:
            batch = self.get(path, params={"$top": page_size, "$skip": skip}).get("value", [])
            out.extend(batch)
            if len(batch) < page_size:
                return out
            skip += page_size

    def post_readonly(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not any(p.match(path) for p in _READ_ONLY_POSTS):
            raise ReadOnlyViolation(f"POST to {path!r} is not an allow-listed read-only endpoint")
        return self._request("POST", path, json=payload)

    # ------------------------------------------------------------------ core
    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        if method not in ("GET", "POST"):
            raise ReadOnlyViolation(f"HTTP {method} is not permitted (application is read-only)")
        if method == "POST" and not any(p.match(path) for p in _READ_ONLY_POSTS):
            raise ReadOnlyViolation(f"POST to {path!r} is not permitted")
        if not path.startswith("/"):
            path = "/" + path
        url = self.base_url + path
        refreshed = False
        attempt = 0
        while True:
            headers = {"Authorization": f"Bearer {self._token()}", "Accept": "application/json"}
            try:
                resp = self.session.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                if attempt < self.max_retries:
                    self._backoff(attempt, None)
                    attempt += 1
                    continue
                raise PowerBIApiError(ErrorCategory.NETWORK, detail=type(exc).__name__) from exc

            if resp.status_code < 400:
                if not resp.content:
                    return {}
                try:
                    return resp.json()
                except ValueError as exc:
                    raise PowerBIApiError(ErrorCategory.UNKNOWN, resp.status_code, detail="Non-JSON response") from exc

            if resp.status_code == 401 and self._refresh and not refreshed:
                refreshed = True
                self._refresh()
                continue
            if resp.status_code in _RETRYABLE_STATUS and attempt < self.max_retries:
                self._backoff(attempt, resp.headers.get("Retry-After"))
                attempt += 1
                continue
            raise self._error(resp)

    def _backoff(self, attempt: int, retry_after: str | None) -> None:
        delay: float
        if retry_after:
            try:
                delay = float(retry_after)
            except ValueError:
                delay = 2 ** attempt
        else:
            delay = (2 ** attempt) + random.uniform(0, 0.5)
        delay = min(delay, self.max_backoff)
        log.info("Retrying Power BI request in %.1fs (attempt %d)", delay, attempt + 1)
        self._sleep(delay)

    @staticmethod
    def _error(resp: requests.Response) -> PowerBIApiError:
        code = detail = None
        try:
            body = resp.json()
            err = body.get("error", {}) if isinstance(body, dict) else {}
            code = err.get("code")
            detail = err.get("message") or (err.get("pbi.error") or {}).get("code")
        except ValueError:
            detail = resp.text[:300]
        request_id = resp.headers.get("RequestId") or resp.headers.get("x-ms-request-id")
        return PowerBIApiError(categorize(resp.status_code), resp.status_code, code, detail, request_id)
