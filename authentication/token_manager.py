"""Token holding and optional *encrypted* MSAL cache persistence.

Default: in-memory only (nothing written to disk).
Optional (PERSIST_TOKEN_CACHE=true): the MSAL SerializableTokenCache is encrypted
with Fernet; the Fernet key lives in the OS keyring (Windows Credential Manager,
macOS Keychain, Secret Service). If no secure keyring backend is available,
persistence is refused — we never fall back to plaintext.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import msal
from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from core.security import get_logger

log = get_logger("auth.token_manager")

KEYRING_SERVICE = "pbi-visual-comparator"
KEYRING_USER = "msal-cache-key"
REFRESH_SKEW = timedelta(minutes=5)


@dataclass
class AccessToken:
    token: SecretStr
    expires_at: datetime
    mode: str
    account: str | None = None   # UPN/display only — no other personal data stored
    scopes: list[str] = field(default_factory=list)

    def is_expiring(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return now + REFRESH_SKEW >= self.expires_at

    def __repr__(self) -> str:  # never leak the token
        return f"AccessToken(mode={self.mode!r}, account={self.account!r}, expires_at={self.expires_at.isoformat()})"


class TokenManager:
    """Thread-safe holder of the current access token."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._token: AccessToken | None = None

    def set(self, token: AccessToken) -> None:
        with self._lock:
            self._token = token

    def get(self) -> AccessToken | None:
        with self._lock:
            return self._token

    def valid(self) -> AccessToken | None:
        tok = self.get()
        if tok is None or tok.is_expiring():
            return None
        return tok

    def clear(self) -> None:
        with self._lock:
            self._token = None


class EncryptedTokenCache:
    """Wraps msal.SerializableTokenCache with encrypted-at-rest persistence."""

    def __init__(self, path: Path, keyring_module=None) -> None:
        self.path = path
        self.cache = msal.SerializableTokenCache()
        self._keyring = keyring_module
        self._fernet: Fernet | None = None
        self.enabled = False
        try:
            self._fernet = Fernet(self._get_or_create_key())
            self.enabled = True
        except Exception as exc:  # no secure backend -> memory only
            log.warning("Token cache persistence disabled (no secure keyring backend): %s", type(exc).__name__)
        if self.enabled:
            self._load()

    def _kr(self):
        if self._keyring is None:
            import keyring  # imported lazily; optional at runtime

            self._keyring = keyring
        return self._keyring

    def _get_or_create_key(self) -> bytes:
        kr = self._kr()
        backend = getattr(kr, "get_keyring", lambda: None)()
        if backend is not None and "fail" in type(backend).__module__.lower():
            raise RuntimeError("keyring fail backend")
        key = kr.get_password(KEYRING_SERVICE, KEYRING_USER)
        if not key:
            key = Fernet.generate_key().decode()
            kr.set_password(KEYRING_SERVICE, KEYRING_USER, key)
        return key.encode()

    def _load(self) -> None:
        if not self.path.exists() or self._fernet is None:
            return
        try:
            self.cache.deserialize(self._fernet.decrypt(self.path.read_bytes()).decode("utf-8"))
        except (InvalidToken, ValueError):
            log.warning("Encrypted token cache unreadable; discarding")
            self.path.unlink(missing_ok=True)

    def save(self) -> None:
        if not self.enabled or self._fernet is None or not self.cache.has_state_changed:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(self._fernet.encrypt(self.cache.serialize().encode("utf-8")))

    def clear(self) -> None:
        self.cache = msal.SerializableTokenCache()
        self.path.unlink(missing_ok=True)
