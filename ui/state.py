"""Streamlit session/state helpers. UI code talks to services through these only."""
from __future__ import annotations

from typing import Any

import streamlit as st

from authentication.msal_auth import MsalAuthenticator
from config.settings import Settings, get_settings
from core.contracts import ComparisonConfig
from core.security import configure_logging
from database.repository import Repository
from powerbi.embed_manager import EmbedManager
from powerbi.http_client import PowerBIHttpClient
from powerbi.report_client import ReportClient
from powerbi.workspace_client import WorkspaceClient


@st.cache_resource
def settings() -> Settings:
    s = get_settings()
    s.ensure_dirs()
    configure_logging(s.log_dir)
    return s


@st.cache_resource
def repo() -> Repository:
    return Repository.from_url(settings().database_url)


def ss() -> Any:
    return st.session_state


def init() -> None:
    d = st.session_state
    d.setdefault("mode", "mock")            # "mock" | "live"
    d.setdefault("config", None)
    d.setdefault("original_ext", None)
    d.setdefault("migrated_ext", None)
    d.setdefault("run", None)
    d.setdefault("progress", [])
    d.setdefault("orig_report", None)
    d.setdefault("mig_report", None)
    if d["config"] is None:
        from services.comparison_service import demo_config

        d["config"] = demo_config() if d["mode"] == "mock" else ComparisonConfig()


def config() -> ComparisonConfig:
    return st.session_state["config"]


def authenticator() -> MsalAuthenticator:
    if "auth" not in st.session_state:
        st.session_state["auth"] = MsalAuthenticator(settings())
    return st.session_state["auth"]


def http() -> PowerBIHttpClient:
    a = authenticator()
    s = settings()
    return PowerBIHttpClient(s.powerbi_api_base_url, a.access_token_value, refresh_token=a.force_refresh,
                             max_retries=s.http_max_retries, timeout=s.http_timeout_seconds)


def workspace_client() -> WorkspaceClient:
    return WorkspaceClient(http())


def report_client() -> ReportClient:
    return ReportClient(http())


def embed_manager() -> EmbedManager:
    a = authenticator()
    return EmbedManager(http(), settings().auth_mode, a.access_token_value)


def reset_comparison() -> None:
    for k in ("original_ext", "migrated_ext", "run"):
        st.session_state[k] = None
    st.session_state["progress"] = []
