"""Microsoft Entra ID authentication via MSAL (verified usage: TECHNICAL_VALIDATION.md §5).

Supported flows:
- interactive (delegated, system browser)   -> msal.PublicClientApplication.acquire_token_interactive
- device_code (delegated)                    -> initiate_device_flow / acquire_token_by_device_flow
- service_principal (client credentials)     -> msal.ConfidentialClientApplication.acquire_token_for_client

Deliberately NOT supported: username/password (ROPC) — insecure, incompatible with MFA.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import msal
from pydantic import SecretStr

from authentication.token_manager import AccessToken, EncryptedTokenCache, TokenManager
from config.settings import POWERBI_DEFAULT_SCOPE, AuthMode, Settings
from core.security import get_logger

log = get_logger("auth.msal")

SCOPES = [POWERBI_DEFAULT_SCOPE]


class AuthError(Exception):
    def __init__(self, message: str, code: str = "auth_failed") -> None:
        super().__init__(message)
        self.code = code


class MsalAuthenticator:
    def __init__(
        self,
        settings: Settings,
        token_manager: TokenManager | None = None,
        app_factory: Callable[..., Any] | None = None,
        cache: EncryptedTokenCache | None = None,
    ) -> None:
        self.settings = settings
        self.tokens = token_manager or TokenManager()
        self._app_factory = app_factory
        self._cache = cache
        if self._cache is None and settings.persist_token_cache and settings.auth_mode != AuthMode.SERVICE_PRINCIPAL:
            self._cache = EncryptedTokenCache(Path(settings.log_dir).parent / "data" / "msal_cache.bin")
        self._app = None

    # ------------------------------------------------------------------ setup
    def validate_configuration(self) -> list[str]:
        problems: list[str] = []
        if not self.settings.client_id:
            problems.append("CLIENT_ID is not configured.")
        if self.settings.auth_mode == AuthMode.SERVICE_PRINCIPAL:
            if not self.settings.tenant_id:
                problems.append("TENANT_ID is required for service principal authentication.")
            if not self.settings.client_secret or not self.settings.client_secret.get_secret_value():
                problems.append("CLIENT_SECRET is required for service principal authentication.")
        return problems

    def _application(self):
        if self._app is not None:
            return self._app
        problems = self.validate_configuration()
        if problems:
            raise AuthError(" ".join(problems), code="configuration")
        factory = self._app_factory
        cache = self._cache.cache if (self._cache and self._cache.enabled) else None
        if self.settings.auth_mode == AuthMode.SERVICE_PRINCIPAL:
            factory = factory or msal.ConfidentialClientApplication
            self._app = factory(
                self.settings.client_id,
                client_credential=self.settings.client_secret.get_secret_value(),  # type: ignore[union-attr]
                authority=self.settings.authority,
            )
        else:
            factory = factory or msal.PublicClientApplication
            kwargs: dict[str, Any] = {"authority": self.settings.authority}
            if cache is not None:
                kwargs["token_cache"] = cache
            self._app = factory(self.settings.client_id, **kwargs)
        return self._app

    # ------------------------------------------------------------------ flows
    def acquire_token(
        self,
        allow_interactive: bool = True,
        device_code_callback: Callable[[str], None] | None = None,
    ) -> AccessToken:
        current = self.tokens.valid()
        if current is not None:
            return current
        app = self._application()
        mode = self.settings.auth_mode
        if mode == AuthMode.SERVICE_PRINCIPAL:
            result = app.acquire_token_for_client(scopes=SCOPES)
        else:
            result = self._silent(app)
            if result is None:
                if not allow_interactive:
                    raise AuthError("Sign-in required (token expired or no account).", code="interaction_required")
                if mode == AuthMode.DEVICE_CODE:
                    flow = app.initiate_device_flow(scopes=SCOPES)
                    if "user_code" not in flow:
                        raise AuthError(f"Device flow failed: {flow.get('error_description', 'unknown error')}")
                    if device_code_callback:
                        device_code_callback(flow["message"])
                    result = app.acquire_token_by_device_flow(flow)
                else:
                    result = app.acquire_token_interactive(scopes=SCOPES, prompt="select_account")
        token = self._to_token(result, mode.value)
        self.tokens.set(token)
        if self._cache:
            self._cache.save()
        log.info("Token acquired via %s for account=%s", mode.value, token.account or "service-principal")
        return token

    def _silent(self, app) -> dict | None:
        accounts = app.get_accounts()
        if not accounts:
            return None
        res = app.acquire_token_silent(SCOPES, account=accounts[0])
        if res and "access_token" in res:
            return res
        return None

    @staticmethod
    def _to_token(result: dict | None, mode: str) -> AccessToken:
        if not result or "access_token" not in result:
            err = (result or {}).get("error", "unknown_error")
            desc = (result or {}).get("error_description", "No token returned")
            # error_description from Entra contains no secrets; keep first line only
            raise AuthError(f"{err}: {str(desc).splitlines()[0]}", code=str(err))
        claims = result.get("id_token_claims") or {}
        expires_in = int(result.get("expires_in", 3600))
        return AccessToken(
            token=SecretStr(result["access_token"]),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
            mode=mode,
            account=claims.get("preferred_username"),
            scopes=list(SCOPES),
        )

    # ------------------------------------------------------------------ helpers
    def access_token_value(self) -> str:
        """Token provider used by the HTTP client; refreshes silently when expiring."""
        tok = self.tokens.valid()
        if tok is None:
            tok = self.acquire_token(allow_interactive=False)
        return tok.token.get_secret_value()

    def force_refresh(self) -> str:
        self.tokens.clear()
        return self.access_token_value()

    def is_signed_in(self) -> bool:
        return self.tokens.valid() is not None

    def sign_out(self) -> None:
        self.tokens.clear()
        if self._app is not None and self.settings.auth_mode != AuthMode.SERVICE_PRINCIPAL:
            for acc in self._app.get_accounts():
                self._app.remove_account(acc)
        if self._cache:
            self._cache.clear()
        log.info("Signed out; in-memory tokens and cache cleared")
