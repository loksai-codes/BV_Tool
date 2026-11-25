"""MOCK authentication tests (fake MSAL application objects). Not live."""
from __future__ import annotations

import pytest
from pydantic import SecretStr

from authentication.msal_auth import SCOPES, AuthError, MsalAuthenticator
from config.settings import POWERBI_DEFAULT_SCOPE, AuthMode
from core.security import sanitize

FAKE_JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0dXNlciJ9.c2lnbmF0dXJlc2lnbmF0dXJl"


class FakeApp:
    def __init__(self, client_id, **kwargs):
        self.client_id = client_id
        self.kwargs = kwargs
        self.accounts: list[dict] = []
        self.calls: list[str] = []
        self.interactive_result = {"access_token": FAKE_JWT, "expires_in": 3600,
                                   "id_token_claims": {"preferred_username": "user@contoso.com"}}

    def get_accounts(self):
        return self.accounts

    def acquire_token_silent(self, scopes, account):
        self.calls.append("silent")
        return {"access_token": FAKE_JWT, "expires_in": 3600}

    def acquire_token_interactive(self, scopes, prompt=None):
        self.calls.append("interactive")
        assert scopes == [POWERBI_DEFAULT_SCOPE]
        self.accounts = [{"username": "user@contoso.com"}]
        return self.interactive_result

    def acquire_token_for_client(self, scopes):
        self.calls.append("client")
        return {"access_token": FAKE_JWT, "expires_in": 3599}

    def initiate_device_flow(self, scopes):
        return {"user_code": "ABC", "message": "Go to https://microsoft.com/devicelogin and enter ABC"}

    def acquire_token_by_device_flow(self, flow):
        self.calls.append("device")
        return {"access_token": FAKE_JWT, "expires_in": 3600}

    def remove_account(self, acc):
        self.accounts.remove(acc)


def _auth(settings, mode, holder):
    settings.auth_mode = mode

    def factory(cid, **kw):
        holder["app"] = FakeApp(cid, **kw)
        return holder["app"]

    return MsalAuthenticator(settings, app_factory=factory)


def test_scope_is_verified_powerbi_default():
    assert SCOPES == ["https://analysis.windows.net/powerbi/api/.default"]


def test_interactive_flow_and_cached_token(settings):
    h: dict = {}
    auth = _auth(settings, AuthMode.INTERACTIVE, h)
    tok = auth.acquire_token()
    assert tok.account == "user@contoso.com"
    assert h["app"].kwargs["authority"].endswith(settings.tenant_id)
    assert FAKE_JWT not in repr(tok)
    auth.acquire_token()  # served from TokenManager, no new call
    assert h["app"].calls == ["interactive"]


def test_non_interactive_requires_signin(settings):
    auth = _auth(settings, AuthMode.INTERACTIVE, {})
    with pytest.raises(AuthError) as e:
        auth.acquire_token(allow_interactive=False)
    assert e.value.code == "interaction_required"


def test_silent_refresh_used_when_account_exists(settings):
    h: dict = {}
    auth = _auth(settings, AuthMode.INTERACTIVE, h)
    auth.acquire_token()
    auth.tokens.clear()  # simulate expiry
    assert auth.access_token_value() == FAKE_JWT
    assert h["app"].calls == ["interactive", "silent"]


def test_service_principal_requires_secret(settings):
    auth = _auth(settings, AuthMode.SERVICE_PRINCIPAL, {})
    with pytest.raises(AuthError) as e:
        auth.acquire_token()
    assert e.value.code == "configuration"


def test_service_principal_flow(settings):
    settings.client_secret = SecretStr("s3cret-value")
    h: dict = {}
    auth = _auth(settings, AuthMode.SERVICE_PRINCIPAL, h)
    tok = auth.acquire_token()
    assert tok.mode == "service_principal"
    assert h["app"].kwargs["client_credential"] == "s3cret-value"
    assert "s3cret" not in repr(settings)


def test_device_code_flow(settings):
    msgs: list[str] = []
    h: dict = {}
    auth = _auth(settings, AuthMode.DEVICE_CODE, h)
    auth.acquire_token(device_code_callback=msgs.append)
    assert "devicelogin" in msgs[0]
    assert h["app"].calls == ["device"]


def test_auth_error_mapped(settings):
    h: dict = {}
    auth = _auth(settings, AuthMode.INTERACTIVE, h)
    auth._application().interactive_result = {"error": "access_denied", "error_description": "User cancelled\nTrace"}
    with pytest.raises(AuthError) as e:
        auth.acquire_token()
    assert str(e.value) == "access_denied: User cancelled"


def test_sign_out_clears(settings):
    h: dict = {}
    auth = _auth(settings, AuthMode.INTERACTIVE, h)
    auth.acquire_token()
    auth.sign_out()
    assert not auth.is_signed_in()
    assert h["app"].accounts == []


def test_log_sanitizer_redacts_tokens():
    s = sanitize(f'Authorization: Bearer {FAKE_JWT} {{"access_token": "abcd1234efgh"}} client_secret=xyz12345')
    assert FAKE_JWT not in s and "abcd1234efgh" not in s and "xyz12345" not in s
