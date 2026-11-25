"""Browser tests: real Chromium (Playwright) + the REAL frontend/powerbi_extractor.js,
with a MOCK Power BI SDK (frontend/mock/mock_powerbi.js). No network, no Power BI.
Verifies the JS primitives and the Python<->JS contract. NOT a live test."""
from __future__ import annotations

import json

import pytest
from pydantic import SecretStr

from core.contracts import ContextStatus, ExtractionStatus
from powerbi.embed_host_server import EmbedHostServer
from powerbi.embed_manager import EmbedConfig
from powerbi.visual_extractor import VisualExtractor
from sample_data import mock_reports as mr

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def driver_factory():
    try:
        from powerbi.visual_extractor import PlaywrightDriver
    except ImportError:  # pragma: no cover
        pytest.skip("playwright not installed")
    server = EmbedHostServer()
    server.start()
    drivers = []

    def make(specs):
        init = "window.__MOCK_REPORTS__ = " + json.dumps({s["reportId"]: s for s in specs}) + ";"
        while drivers:  # only one sync Playwright runtime may run per thread
            drivers.pop().close()
        try:
            d = PlaywrightDriver(server.base_url, headless=True, init_script=init,
                                 html_page="mock/embed_host_mock.html", is_mock=True)
        except Exception as exc:  # browser binaries missing
            if "Executable doesn't exist" in str(exc):
                pytest.skip(f"Chromium unavailable: {exc}")
            raise
        drivers.append(d)
        return d

    yield make
    for d in drivers:
        d.close()
    server.stop()


def test_full_extraction_through_real_js(driver_factory, tmp_path):
    spec = mr.original_spec()
    d = driver_factory([spec])
    info = mr.mock_report_info("original")
    embed = EmbedConfig(info.id, info.embed_url, SecretStr("mock-token"), "Aad")
    ext = VisualExtractor(d, render_timeout_ms=5000).extract("original", info, embed, mr.demo_country_config(), True)
    assert ext.fatal_error is None, ext.log
    assert len(ext.visuals) == 11
    assert ext.context.status == ContextStatus.VALIDATED, ext.context.messages
    country = next(v for v in ext.visuals if v.visual_title == "Sales by Country")
    assert country.status == ExtractionStatus.SUCCESS
    assert country.dataframe()["CountryName"].tolist() == ["China"]
    bullet = next(v for v in ext.visuals if v.visual_title == "Target Bullet")
    assert bullet.status == ExtractionStatus.UNSUPPORTED and "not supported" in bullet.error_message
    # embed config forced read-only View mode with AAD token type
    cfg = d.page.evaluate("() => window.__lastEmbedConfig")
    assert cfg == {"tokenType": 0, "viewMode": 0, "permissions": 0, "hasToken": True}


def test_js_refuses_destructive_filter_operations(driver_factory):
    d = driver_factory([mr.original_spec()])
    info = mr.mock_report_info("original")
    d.load_report(EmbedConfig(info.id, info.embed_url, SecretStr("t"), "Aad"), 5000)
    for op in ("RemoveAll", "ReplaceAll"):
        r = d.update_report_filters(op, [])
        assert r["ok"] is False and "refused" in r["error"]["message"]
    assert len(d.capture_report_filters()["filters"]) == 1  # Year filter intact


def test_load_error_surfaces(driver_factory):
    spec = mr.migrated_spec()
    spec["loadError"] = {"message": "Not Authorized", "errorCode": "TokenExpired"}
    d = driver_factory([spec])
    info = mr.mock_report_info("migrated")
    r = d.load_report(EmbedConfig(info.id, info.embed_url, SecretStr("t"), "Aad"), 1500)
    assert r["ok"] is False
