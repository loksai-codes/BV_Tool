"""MOCK extraction tests: VisualExtractor orchestration driven by the Python MockDriver.
These verify orchestration/decision logic only. NOT live Power BI tests."""
from __future__ import annotations

import copy

from pydantic import SecretStr

from core.contracts import Completeness, ContextStatus, ExtractionMode, ExtractionStatus, SourceMethod
from powerbi.embed_manager import EmbedConfig
from powerbi.mock_driver import MockDriver
from powerbi.visual_extractor import VisualExtractor, classify_visual
from sample_data import mock_reports as mr


def _embed(rid):
    return EmbedConfig(rid, "https://app.powerbi.com/reportEmbed", SecretStr("mock-token"), "Aad")


def extract(spec, role="original", apply=True, cfg=None, rows=30000):
    cfg = cfg or mr.demo_country_config()
    info = mr.mock_report_info(role)
    stages = []
    ex = VisualExtractor(MockDriver(spec), rows=rows, progress=lambda s, m, d: stages.append(s))
    return ex.extract(role, info, _embed(info.id), cfg, apply_context=apply), stages


def test_original_extraction_applies_china_and_records_every_visual():
    ext, stages = extract(mr.original_spec())
    assert ext.is_mock and ext.fatal_error is None
    assert [p.display_name for p in ext.pages] == ["Sales Overview", "Trends"]
    assert len(ext.visuals) == 11  # nothing silently dropped
    by_title = {v.visual_title: v for v in ext.visuals}
    assert by_title["Total Sales"].status == ExtractionStatus.SUCCESS
    assert by_title["Total Sales"].source_method == SourceMethod.MOCK_FIXTURE
    assert by_title["Target Bullet"].status == ExtractionStatus.UNSUPPORTED  # custom visual, export error captured
    assert "ExportDataNotSupported" == by_title["Target Bullet"].error_code
    assert by_title["R Forecast"].status == ExtractionStatus.UNSUPPORTED
    assert by_title["Country"].status == ExtractionStatus.SKIPPED_NON_DATA
    # China filter applied -> country table contains only China
    df = by_title["Sales by Country"].dataframe()
    assert df["CountryName"].tolist() == ["China"]
    assert ext.context.status == ContextStatus.VALIDATED
    assert ext.context.action_taken == "add"
    # unrelated Year filter preserved
    assert any(f["target"]["column"] == "Year" for f in ext.context.report_filters_after)
    assert {"report_loading", "page_discovery", "filter_application", "visual_discovery", "visual_extraction"} <= set(stages)
    assert all(v.integrity_ok() for v in ext.visuals)


def test_without_context_original_returns_all_countries():
    ext, _ = extract(mr.original_spec(), apply=False)
    df = next(v for v in ext.visuals if v.visual_title == "Sales by Country").dataframe()
    assert len(df) == 13
    assert ext.context.status == ContextStatus.NOT_REQUIRED


def test_migrated_not_filtered_by_default():
    ext, _ = extract(mr.migrated_spec(), role="migrated", apply=False)
    assert ext.context.status == ContextStatus.NOT_REQUIRED
    assert ext.context.report_filters_after == []


def test_conflicting_existing_filter_not_overwritten():
    spec = mr.original_spec()
    spec["initialReportFilters"].append({"$schema": "x#basic", "target": {"table": "Geography", "column": "CountryName"},
                                         "operator": "In", "values": ["Germany"], "filterType": 1})
    ext, _ = extract(spec)
    assert ext.context.status == ContextStatus.CONFLICT
    df = next(v for v in ext.visuals if v.visual_title == "Sales by Country").dataframe()
    assert df["CountryName"].tolist() == ["Germany"]  # untouched


def test_conflicting_filter_replaced_when_allowed():
    spec = mr.original_spec()
    spec["initialReportFilters"].append({"$schema": "x#basic", "target": {"table": "Geography", "column": "CountryName"},
                                         "operator": "In", "values": ["Germany"], "filterType": 1})
    cfg = mr.demo_country_config()
    cfg.allow_replace_conflicting = True
    ext, _ = extract(spec, cfg=cfg)
    assert ext.context.status == ContextStatus.VALIDATED
    assert ext.context.action_taken == "replace"


def test_update_filters_failure_invalid_context():
    spec = mr.original_spec()
    spec["updateFiltersError"] = "Filter target not found"
    ext, _ = extract(spec)
    assert ext.context.status == ContextStatus.INVALID


def test_page_filter_excluding_china_invalidates():
    spec = mr.original_spec()
    spec["pages"][1]["filters"] = [{"$schema": "x#basic", "target": {"table": "Geography", "column": "CountryName"},
                                    "operator": "NotIn", "values": ["China"], "filterType": 1}]
    ext, _ = extract(spec)
    assert ext.context.status == ContextStatus.INVALID


def test_load_failure_recorded():
    spec = mr.original_spec()
    spec["loadError"] = {"message": "TokenExpired", "detailedMessage": "Access token has expired"}
    ext, _ = extract(spec)
    assert ext.fatal_error and "TokenExpired" in ext.fatal_error
    assert ext.visuals == []
    assert ext.context.status != ContextStatus.VALIDATED


def test_truncation_detected():
    spec = mr.original_spec()
    spec["visuals"]["ReportSection1a2b"][2]["rowsOverride"] = 50
    ext, _ = extract(spec, rows=50)
    v = next(v for v in ext.visuals if v.visual_title == "Sales by Category and Month")
    assert v.status == ExtractionStatus.POSSIBLY_TRUNCATED
    assert v.completeness == Completeness.UNKNOWN and "30,000" in v.truncation_info


def test_page_render_failure_marks_completeness_unknown():
    spec = mr.original_spec()
    spec["pageActivationErrors"] = ["ReportSection3c4d"]
    ext, _ = extract(spec)
    v = next(v for v in ext.visuals if v.visual_title == "Units Trend")
    assert v.completeness == Completeness.UNKNOWN


def test_rows_never_exceed_documented_limit():
    d = MockDriver(mr.original_spec())
    ex = VisualExtractor(d, rows=100000)
    assert ex.rows == 30000


def test_underlying_mode_error_recorded():
    spec = mr.original_spec()
    spec["visuals"]["ReportSection1a2b"][0]["underlyingError"] = {"message": "Underlying data export not allowed"}
    info = mr.mock_report_info("original")
    ext = VisualExtractor(MockDriver(spec)).extract("original", info, _embed(info.id), mr.demo_country_config(),
                                                    True, ExtractionMode.UNDERLYING)
    v = next(v for v in ext.visuals if v.visual_title == "Total Sales")
    assert v.status == ExtractionStatus.FAILED and "not allowed" in v.error_message


def test_classification():
    assert classify_visual("tableEx")[0] == "data"
    assert classify_visual("slicer")[0] == "slicer"
    assert classify_visual("scriptVisual")[0] == "unsupported"
    assert classify_visual("someNewVisual")[0] == "unknown"
    assert classify_visual("textbox")[0] == "non_data"
