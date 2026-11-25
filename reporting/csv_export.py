"""CSV export: one CSV per report table, bundled as a ZIP (UTF-8 with BOM for Excel)."""
from __future__ import annotations

import csv
import io
import zipfile

from core.contracts import ComparisonRunResult, MismatchType
from reporting import common as c

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe(v) -> str:
    """Neutralise CSV/formula injection for values opened in spreadsheet tools."""
    s = "" if v is None else str(v)
    if s.startswith(_FORMULA_PREFIXES) and not _is_number(s):
        return "'" + s
    return s


def _is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def table_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    if not rows:
        return ""
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: _safe(v) for k, v in r.items()})
    return buf.getvalue()


def build_zip(run: ComparisonRunResult) -> bytes:
    tables = {
        "visual_summary.csv": c.visual_summary_rows(run),
        "mismatching_records.csv": c.mismatch_rows(run, {MismatchType.VALUE_MISMATCH, MismatchType.NULL_MISMATCH,
                                                         MismatchType.DUPLICATE_KEY, MismatchType.CONTEXT_VIOLATION}),
        "missing_records.csv": c.mismatch_rows(run, {MismatchType.MISSING_RECORD}),
        "additional_records.csv": c.mismatch_rows(run, {MismatchType.ADDITIONAL_RECORD}),
        "matching_records.csv": c.matching_rows(run),
        "extraction_errors.csv": c.extraction_error_rows(run),
        "unsupported_visuals.csv": c.unsupported_rows(run),
        "visual_mapping.csv": c.mapping_rows(run),
        "evidence.csv": c.evidence_rows(run),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if run.is_mock:
            z.writestr("README_MOCK_DATA.txt", c.MOCK_BANNER + "\n")
        for name, rows in tables.items():
            z.writestr(name, "﻿" + table_csv(rows))
    return buf.getvalue()
