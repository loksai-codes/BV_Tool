"""Stakeholder Excel workbook (XlsxWriter) with the 11 required sheets and status colouring."""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import xlsxwriter

from core.contracts import ComparisonRunResult, MismatchType
from reporting import common as c

SHEETS = [
    "Executive Summary", "Comparison Configuration", "Visual Mapping", "Visual Summary", "Matching Records",
    "Mismatching Records", "Missing Records", "Additional Records", "Extraction Errors", "Unsupported Visuals",
    "Detailed Evidence",
]
COLORS = {  # green match, red mismatch, yellow partial/inconclusive, grey unsupported
    "PASS": "#C6EFCE", "MATCH": "#C6EFCE",
    "FAIL": "#FFC7CE", "VALUE_MISMATCH": "#FFC7CE", "NULL_MISMATCH": "#FFC7CE", "MISSING_RECORD": "#FFC7CE",
    "ADDITIONAL_RECORD": "#FFC7CE", "FAILED": "#FFC7CE", "FATAL": "#FFC7CE",
    "PARTIAL": "#FFEB9C", "INCONCLUSIVE": "#FFEB9C", "POSSIBLY_TRUNCATED": "#FFEB9C", "DUPLICATE_KEY": "#FFEB9C",
    "UNSUPPORTED": "#D9D9D9", "NOT_MAPPED": "#D9D9D9",
}
_MAX_CELL = 32_000  # Excel cell limit is 32,767 chars


def _cell(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, (int, float, bool)):
        return v
    s = str(v)
    return s if len(s) <= _MAX_CELL else s[:_MAX_CELL] + "…[truncated in Excel; see JSON evidence]"


def build_workbook(run: ComparisonRunResult) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "strings_to_numbers": False, "strings_to_formulas": False,
                                   "strings_to_urls": False})
    hdr = wb.add_format({"bold": True, "bg_color": "#1F3864", "font_color": "#FFFFFF", "text_wrap": True, "valign": "top", "border": 1})
    wrap = wb.add_format({"text_wrap": True, "valign": "top"})
    banner = wb.add_format({"bold": True, "font_color": "#9C0006", "bg_color": "#FFC7CE"})
    fmts = {k: wb.add_format({"bg_color": v}) for k, v in COLORS.items()}

    tables = {
        "Executive Summary": c.executive_summary(run),
        "Comparison Configuration": c.configuration_rows(run),
        "Visual Mapping": c.mapping_rows(run),
        "Visual Summary": c.visual_summary_rows(run),
        "Matching Records": c.matching_rows(run),
        "Mismatching Records": c.mismatch_rows(run, {MismatchType.VALUE_MISMATCH, MismatchType.NULL_MISMATCH,
                                                     MismatchType.DUPLICATE_KEY, MismatchType.CONTEXT_VIOLATION}),
        "Missing Records": c.mismatch_rows(run, {MismatchType.MISSING_RECORD}),
        "Additional Records": c.mismatch_rows(run, {MismatchType.ADDITIONAL_RECORD}),
        "Extraction Errors": c.extraction_error_rows(run),
        "Unsupported Visuals": c.unsupported_rows(run),
        "Detailed Evidence": c.evidence_rows(run),
    }
    for name in SHEETS:
        rows = tables[name]
        ws = wb.add_worksheet(name[:31])
        start = 0
        if run.is_mock:
            ws.write(0, 0, c.MOCK_BANNER, banner)
            start = 1
        if not rows:
            ws.write(start, 0, "No records.")
            continue
        cols = list(rows[0].keys())
        for j, col in enumerate(cols):
            ws.write(start, j, col, hdr)
        for i, row in enumerate(rows, start=start + 1):
            for j, col in enumerate(cols):
                ws.write(i, j, _cell(row.get(col)), wrap)
        last = start + len(rows)
        ws.freeze_panes(start + 1, 0)
        ws.autofilter(start, 0, last, len(cols) - 1)
        for j, col in enumerate(cols):
            width = max(len(str(col)), *(min(len(str(r.get(col) or "")), 60) for r in rows[:200]))
            ws.set_column(j, j, min(max(width + 2, 10), 60))
            if col in ("Status", "Visual status", "Mismatch type", "Value") or (name == "Executive Summary" and col == "Value"):
                for key, f in fmts.items():
                    ws.conditional_format(start + 1, j, last, j, {"type": "cell", "criteria": "==", "value": f'"{key}"', "format": f})
    wb.close()
    return buf.getvalue()


def write_workbook(run: ComparisonRunResult, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_workbook(run))
    return path
