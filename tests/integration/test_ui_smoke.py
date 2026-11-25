"""UI smoke tests with streamlit.testing (headless). Uses MOCK data only."""
from __future__ import annotations

import pytest
from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[2] / "app.py")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'ui.db').as_posix()}")
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("CLIENT_ID", "")
    from config.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _app():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def _texts(at):
    return " ".join([m.value for m in at.markdown] + [str(x.value) for x in at.warning] + [str(x.value) for x in at.error]
                    + [str(x.value) for x in at.info] + [str(x.value) for x in at.success])


def test_home_renders():
    at = _app()
    assert at.title[0].value == "Power BI Visual Data Comparator"
    labels = [b.label for b in at.button]
    assert "Start new comparison" in labels and "Run demo with mock data" in labels


def test_demo_flow_reaches_dashboard():
    at = _app()
    next(b for b in at.button if b.label == "Run demo with mock data").click().run()
    assert not at.exception, at.exception
    assert at.title[0].value == "Comparison dashboard"
    text = _texts(at)
    assert "MOCK DATA" in text and "FAIL" in text
    assert any(m.label == "Missing rows" for m in at.metric)


PAGES = ["connection_page", "configuration_page", "extraction_page", "comparison_page", "details_page", "history_page"]


@pytest.mark.parametrize("page", PAGES)
def test_pages_render_without_run(page):
    at = _app()
    at.switch_page(f"views/{page}.py").run()
    assert not at.exception, at.exception


@pytest.mark.parametrize("page", PAGES)
def test_pages_render_after_demo_run(page):
    at = _app()
    next(b for b in at.button if b.label == "Run demo with mock data").click().run()
    at.switch_page(f"views/{page}.py").run()
    assert not at.exception, at.exception


def test_connection_page_reports_missing_config():
    at = _app()
    at.switch_page("views/connection_page.py").run()
    assert "Configuration incomplete" in _texts(at)
