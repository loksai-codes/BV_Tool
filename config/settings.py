"""Application settings loaded from environment variables / .env.

Secrets (CLIENT_SECRET) are held as ``SecretStr`` so they never appear in
``repr()``/logs. Nothing here hardcodes workspace IDs, report IDs or field names.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Verified 2026-11-25 (docs/TECHNICAL_VALIDATION.md §5, source S19).
POWERBI_DEFAULT_SCOPE = "https://analysis.windows.net/powerbi/api/.default"
AUTHORITY_HOST = "https://login.microsoftonline.com"

# Verified documented limits (docs/TECHNICAL_VALIDATION.md §2, §8).
EXPORT_DATA_MAX_ROWS = 30_000
EXECUTE_QUERIES_MAX_ROWS = 100_000


class AuthMode(str, Enum):
    INTERACTIVE = "interactive"          # delegated, browser sign-in (PublicClientApplication)
    DEVICE_CODE = "device_code"          # delegated, device code flow
    SERVICE_PRINCIPAL = "service_principal"  # client credentials (ConfidentialClientApplication)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    tenant_id: str = Field(default="", alias="TENANT_ID")
    client_id: str = Field(default="", alias="CLIENT_ID")
    client_secret: SecretStr | None = Field(default=None, alias="CLIENT_SECRET")
    redirect_uri: str = Field(default="http://localhost", alias="REDIRECT_URI")
    auth_mode: AuthMode = Field(default=AuthMode.INTERACTIVE, alias="AUTH_MODE")
    powerbi_api_base_url: str = Field(
        default="https://api.powerbi.com/v1.0/myorg", alias="POWERBI_API_BASE_URL"
    )
    database_url: str = Field(
        default=f"sqlite:///{(PROJECT_ROOT / 'data' / 'comparator.db').as_posix()}",
        alias="DATABASE_URL",
    )
    log_dir: Path = Field(default=PROJECT_ROOT / "logs", alias="LOG_DIR")
    export_dir: Path = Field(default=PROJECT_ROOT / "exports", alias="EXPORT_DIR")
    screenshot_dir: Path = Field(default=PROJECT_ROOT / "exports" / "screenshots", alias="SCREENSHOT_DIR")
    persist_token_cache: bool = Field(default=False, alias="PERSIST_TOKEN_CACHE")
    http_timeout_seconds: float = Field(default=60.0, alias="HTTP_TIMEOUT_SECONDS")
    http_max_retries: int = Field(default=4, alias="HTTP_MAX_RETRIES")
    embed_render_timeout_ms: int = Field(default=90_000, alias="EMBED_RENDER_TIMEOUT_MS")
    headless_browser: bool = Field(default=True, alias="HEADLESS_BROWSER")
    data_retention_days: int = Field(default=90, alias="DATA_RETENTION_DAYS")

    @field_validator("powerbi_api_base_url")
    @classmethod
    def _https_only(cls, v: str) -> str:
        v = v.rstrip("/")
        if not v.startswith("https://"):
            raise ValueError("POWERBI_API_BASE_URL must use https")
        return v

    @property
    def authority(self) -> str:
        """Authority URL. Tenant-specific when a tenant is configured (required for SP)."""
        tenant = self.tenant_id.strip() or "organizations"
        return f"{AUTHORITY_HOST}/{tenant}"

    def ensure_dirs(self) -> None:
        for d in (self.log_dir, self.export_dir, self.screenshot_dir):
            Path(d).mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            Path(self.database_url.replace("sqlite:///", "", 1)).parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
