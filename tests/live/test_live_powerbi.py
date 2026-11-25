"""LIVE Power BI tests — never run by default (marker `live`, deselected in pyproject).

Run explicitly after configuring .env and a signed-in-capable identity:
    LIVE_ORIGINAL_WS=<guid> LIVE_ORIGINAL_REPORT=<guid> LIVE_MIGRATED_WS=<guid> LIVE_MIGRATED_REPORT=<guid> \
    LIVE_COUNTRY_TABLE=<table> LIVE_COUNTRY_COLUMN=<column> pytest -m live -s

These tests make only read-only calls (GET discovery, embed in View mode, exportData).
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live

REQUIRED = ["LIVE_ORIGINAL_WS", "LIVE_ORIGINAL_REPORT", "LIVE_MIGRATED_WS", "LIVE_MIGRATED_REPORT"]


@pytest.fixture(scope="module")
def live():
    missing = [k for k in REQUIRED if not os.getenv(k)]
    if missing:
        pytest.skip(f"live env not configured: {missing}")
    from authentication.msal_auth import MsalAuthenticator
    from config.settings import get_settings
    from powerbi.http_client import PowerBIHttpClient

    s = get_settings()
    auth = MsalAuthenticator(s)
    auth.acquire_token(device_code_callback=print)
    http = PowerBIHttpClient(s.powerbi_api_base_url, auth.access_token_value, refresh_token=auth.force_refresh)
    return s, auth, http


def test_live_discovery(live):
    from powerbi.report_client import ReportClient
    from powerbi.workspace_client import WorkspaceClient

    _, _, http = live
    assert WorkspaceClient(http).list_workspaces()
    for ws, rid in (("LIVE_ORIGINAL_WS", "LIVE_ORIGINAL_REPORT"), ("LIVE_MIGRATED_WS", "LIVE_MIGRATED_REPORT")):
        v = ReportClient(http).validate_access(os.environ[ws], os.environ[rid])
        assert v.ok, v.problems


def test_live_extraction_and_comparison(live, tmp_path):
    from core.contracts import ComparisonConfig, CountryContextConfig
    from powerbi.embed_manager import EmbedManager
    from powerbi.report_client import ReportClient
    from services.comparison_service import auto_map, extract_live
    from comparison.reconciliation import run_comparison

    s, auth, http = live
    rc = ReportClient(http)
    o = rc.get_report(os.environ["LIVE_ORIGINAL_WS"], os.environ["LIVE_ORIGINAL_REPORT"])
    m = rc.get_report(os.environ["LIVE_MIGRATED_WS"], os.environ["LIVE_MIGRATED_REPORT"])
    cfg = ComparisonConfig(country=CountryContextConfig(
        original_table=os.getenv("LIVE_COUNTRY_TABLE", ""), original_column=os.getenv("LIVE_COUNTRY_COLUMN", ""),
        migrated_table=os.getenv("LIVE_MIGRATED_COUNTRY_TABLE", ""), migrated_column=os.getenv("LIVE_MIGRATED_COUNTRY_COLUMN", ""),
        value=os.getenv("LIVE_COUNTRY_VALUE", "China")))
    oe, me = extract_live(s, EmbedManager(http, s.auth_mode, auth.access_token_value), o, m, cfg)
    print("original counts", oe.counts(), "context", oe.context.status, oe.fatal_error)
    print("migrated counts", me.counts(), "context", me.context.status, me.fatal_error)
    assert not oe.is_mock and not me.is_mock
    run = run_comparison(oe, me, auto_map(oe, me, cfg))
    print("overall", run.overall_status, run.overall_reasons)
