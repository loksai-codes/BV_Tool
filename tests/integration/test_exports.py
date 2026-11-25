"""Export validation on the MOCK demo run: files are opened and their contents asserted."""
from __future__ import annotations

import io
import json
import zipfile

import openpyxl
import pytest

from reporting.csv_export import build_zip, table_csv
from reporting.excel_export import SHEETS, build_workbook
from reporting.html_report import build_html
from reporting.json_export import build_json
from services.comparison_service import run_demo


@pytest.fixture(scope="module")
def run():
    return run_demo(None, approve_all_suggestions=True)


def test_excel_has_all_sheets_and_content(run, tmp_path):
    data = build_workbook(run)
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert wb.sheetnames == SHEETS
    es = wb["Executive Summary"]
    assert "MOCK DATA" in es["A1"].value
    items = {es.cell(r, 1).value: es.cell(r, 2).value for r in range(2, es.max_row + 1)}
    assert items["Overall status"] == "FAIL"
    missing = wb["Missing Records"]
    header = [c.value for c in missing[2]]
    assert {"Original value", "Migrated value", "Absolute difference", "Percentage difference", "Visual status"} <= set(header)
    values = [[c.value for c in row] for row in missing.iter_rows(min_row=3)]
    assert any("Home" in str(r) and "2024-07" in str(r) for r in values)
    mism = wb["Mismatching Records"]
    hdr = [c.value for c in mism[2]]
    abs_col = hdr.index("Absolute difference")
    assert "1500.00" in [row[abs_col].value for row in mism.iter_rows(min_row=3)]
    unsup = wb["Unsupported Visuals"]
    assert unsup.max_row - 2 == 2  # Target Bullet + R Forecast
    # conditional formatting configured on status columns
    assert len(wb["Visual Summary"].conditional_formatting) > 0


def test_csv_zip(run):
    z = zipfile.ZipFile(io.BytesIO(build_zip(run)))
    names = set(z.namelist())
    assert {"visual_summary.csv", "missing_records.csv", "additional_records.csv", "README_MOCK_DATA.txt"} <= names
    text = z.read("additional_records.csv").decode("utf-8-sig")
    assert "Accessories" in text


def test_csv_formula_injection_neutralised():
    out = table_csv([{"a": "=HYPERLINK(\"x\")", "b": "-12.5", "c": "@cmd"}])
    assert "'=HYPERLINK" in out and ",-12.5," in out and "'@cmd" in out


def test_json_evidence(run):
    data = json.loads(build_json(run))
    assert data["_meta"]["data_source"] == "MOCK_FIXTURE"
    v = data["original"]["visuals"][0]
    assert v["raw_csv"] and len(v["raw_sha256"]) == 64
    assert data["overall_status"] == "FAIL"
    assert json.loads(build_json(run, include_raw=False))["original"]["visuals"][0]["raw_csv"] is None


def test_html_escapes_untrusted_text(run):
    evil = run.model_copy(deep=True)
    evil.visual_results[0].original_title = "<script>alert(1)</script>"
    html = build_html(evil)
    assert "<script>alert(1)</script>" not in html and "&lt;script&gt;" in html
    assert "MOCK DATA" in html and "FAIL" in html
