"""Builds embed configurations (docs/TECHNICAL_VALIDATION.md §6).

- User-owns-data (default): TokenType.Aad with the signed-in user's Entra token.
  RLS applies naturally to the user. Recommended.
- App-owns-data (service principal): TokenType.Embed from POST /GenerateToken,
  requesting view-only access (allowEdit=false, xmlaPermissions=Off). We never
  send ``identities`` — i.e. never impersonate a user to satisfy RLS. If the
  model requires an effective identity, token generation fails and the failure
  is reported rather than bypassed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import SecretStr

from config.settings import AuthMode
from core.contracts import ReportInfo
from core.security import validate_guid
from powerbi.http_client import PowerBIHttpClient


@dataclass
class EmbedConfig:
    report_id: str
    embed_url: str
    access_token: SecretStr
    token_type: str  # "Aad" | "Embed"
    notes: list[str] = field(default_factory=list)

    def to_js(self, render_timeout_ms: int) -> dict:
        # Token exposed only when handing to the in-memory browser session.
        return {
            "reportId": self.report_id,
            "embedUrl": self.embed_url,
            "accessToken": self.access_token.get_secret_value(),
            "tokenType": self.token_type,
            "renderTimeoutMs": render_timeout_ms,
        }

    def __repr__(self) -> str:
        return f"EmbedConfig(report_id={self.report_id!r}, token_type={self.token_type!r})"


class EmbedManager:
    def __init__(self, http: PowerBIHttpClient, auth_mode: AuthMode, user_token_provider) -> None:
        self.http = http
        self.auth_mode = auth_mode
        self._user_token = user_token_provider

    def build(self, report: ReportInfo) -> EmbedConfig:
        if not report.embed_url:
            raise ValueError(f"Report {report.id} has no embedUrl")
        if self.auth_mode != AuthMode.SERVICE_PRINCIPAL:
            return EmbedConfig(report.id, report.embed_url, SecretStr(self._user_token()), "Aad",
                               ["Embed for your organization (user identity; RLS enforced for the signed-in user)."])
        payload = {"reports": [{"id": validate_guid(report.id), "allowEdit": False}]}
        if report.dataset_id:
            payload["datasets"] = [{"id": validate_guid(report.dataset_id), "xmlaPermissions": "Off"}]
        resp = self.http.post_readonly("/GenerateToken", payload)
        return EmbedConfig(report.id, report.embed_url, SecretStr(resp["token"]), "Embed",
                           ["Embed token (service principal, view-only). No effective identity sent; RLS models will fail rather than be bypassed.",
                            f"tokenId={resp.get('tokenId')} expiration={resp.get('expiration')}"])
