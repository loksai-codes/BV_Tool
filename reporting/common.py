"""Flattening of a ComparisonRunResult into report tables (shared by all exporters)."""
from __future__ import annotations

import json
from typing import Any

from comparison.visual_discovery import inventory
from core.contracts import ComparisonRunResult, ExtractionStatus, MismatchType

MOCK_BANNER = "MOCK DATA — generated from test fixtures, NOT from Power BI"


def _j(v: Any) -> Any:
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str, ensure_ascii=False)
    return v


def _title(r, side):
    return getattr(r, f"{side}_title") or getattr(r, f"{side}_visual") or ""


def executive_summary(run: ComparisonRunResult) -> list[dict[str, Any]]:
    s = run.summary()
    rows = [
        ("Data source", MOCK_BANNER if run.is_mock else "Live Power BI visual exports"),
        ("Comparison", run.name),
        ("Run ID", run.run_id),
        ("Overall status", run.overall_status.value),
        ("Overall reasons", " | ".join(run.overall_reasons)),
        ("Started (UTC)", run.started_at.isoformat()),
        ("Finished (UTC)", run.finished_at.isoformat() if run.finished_at else ""),
        ("Original report", f"{run.original.report_name} ({run.original.report_id})"),
        ("Migrated report", f"{run.migrated.report_name} ({run.migrated.report_id})"),
        ("Country context", run.config.country.value),
        ("Original context status", run.original.context.status.value),
        ("Migrated context status", run.migrated.context.status.value),
    ] + [(k.replace("_", " ").title(), v) for k, v in s.items()]
    return [{"Item": k, "Value": v} for k, v in rows]


def configuration_rows(run: ComparisonRunResult) -> list[dict[str, Any]]:
    c = run.config
    rows = [
        ("Country value", c.country.value),
        ("Original country field", f"{c.country.original_table}[{c.country.original_column}]"),
        ("Migrated country field", f"{c.country.migrated_table}[{c.country.migrated_column}]"),
        ("Apply context to migrated", c.country.apply_to_migrated),
        ("Allow replacing conflicting filter", c.country.allow_replace_conflicting),
        ("Extraction mode", c.extraction_mode.value),
        ("Absolute tolerance", str(c.tolerance.absolute)),
        ("Percentage tolerance", str(c.tolerance.percentage)),
        ("Require context validation", c.require_context_validation),
        ("Auto-approve threshold", c.auto_approve_threshold),
    ] + [(f"Normalization: {k}", _j(v)) for k, v in c.normalization.model_dump().items()]
    return [{"Setting": k, "Value": v} for k, v in rows]


def mapping_rows(run: ComparisonRunResult) -> list[dict[str, Any]]:
    o, m = run.original, run.migrated
    out = []
    for vm in run.config.visual_mappings:
        ov, mv = o.find(vm.original_page, vm.original_visual), m.find(vm.migrated_page, vm.migrated_visual)
        out.append({
            "Original page": ov.page_display_name if ov else vm.original_page,
            "Original visual": (ov.visual_title or ov.visual_name) if ov else vm.original_visual,
            "Migrated page": mv.page_display_name if mv else vm.migrated_page,
            "Migrated visual": (mv.visual_title or mv.visual_name) if mv else vm.migrated_visual,
            "Confidence": vm.confidence, "Provenance": vm.provenance, "Approved": vm.approved,
            "Mandatory": vm.mandatory, "Signals": _j(vm.signals), "Explanation": vm.explanation,
            "Column mappings": _j([cm.model_dump() for cm in vm.column_mappings]),
        })
    return out


def visual_summary_rows(run: ComparisonRunResult) -> list[dict[str, Any]]:
    return [{
        "Status": r.status.value, "Mandatory": r.mandatory,
        "Original page": r.original_page_display or "", "Original visual": _title(r, "original"),
        "Migrated page": r.migrated_page_display or "", "Migrated visual": _title(r, "migrated"),
        "Visual type": r.visual_type, "Rows original": r.rows_original, "Rows migrated": r.rows_migrated,
        "Rows compared": r.rows_compared, "Rows matched": r.rows_matched, "Missing rows": r.missing_rows,
        "Additional rows": r.additional_rows, "Numeric mismatches": r.numeric_mismatches,
        "Duplicate keys": r.duplicate_keys, "Key columns": ", ".join(r.key_columns),
        "Mapping confidence": r.mapping_confidence, "Mapping provenance": r.mapping_provenance,
        "Source": ", ".join(r.source_methods), "Reasons": " | ".join(r.reasons), "Notes": " | ".join(r.notes),
    } for r in run.visual_results]


def matching_rows(run: ComparisonRunResult) -> list[dict[str, Any]]:
    out = []
    for r in run.visual_results:
        for rec in r.matching_records:
            out.append({"Original page": r.original_page_display, "Original visual": _title(r, "original"),
                        "Migrated visual": _title(r, "migrated"), "Status": "MATCH", "Record": _j(rec)})
    return out


def mismatch_rows(run: ComparisonRunResult, types: set[MismatchType]) -> list[dict[str, Any]]:
    o_ts = {v.key: v.extracted_at for v in run.original.visuals}
    out = []
    for r in run.visual_results:
        for mm in r.mismatches:
            if mm.mismatch_type not in types:
                continue
            out.append({
                "Original page": r.original_page_display, "Original visual": _title(r, "original"),
                "Migrated page": r.migrated_page_display, "Migrated visual": _title(r, "migrated"),
                "Visual status": r.status.value, "Mismatch type": mm.mismatch_type.value, "Confirmed": mm.confirmed,
                "Key": _j(mm.key), "Column": mm.column, "Original value": _j(mm.original_value),
                "Migrated value": _j(mm.migrated_value),
                "Absolute difference": None if mm.absolute_difference is None else format(mm.absolute_difference, "f"),
                "Percentage difference": None if mm.percentage_difference is None else format(mm.percentage_difference, "f"),
                "Percentage note": mm.percentage_note, "Detail": mm.detail,
                "Extracted at (original)": str(o_ts.get(f"{r.original_page}/{r.original_visual}", "")),
            })
    return out


def extraction_error_rows(run: ComparisonRunResult) -> list[dict[str, Any]]:
    rows = []
    for ext in (run.original, run.migrated):
        if ext.fatal_error:
            rows.append({"Role": ext.role, "Page": "", "Visual": "(report)", "Type": "", "Status": "FATAL", "Error": ext.fatal_error})
        for v in ext.visuals:
            if v.status in (ExtractionStatus.FAILED, ExtractionStatus.POSSIBLY_TRUNCATED, ExtractionStatus.NOT_ATTEMPTED):
                rows.append({"Role": ext.role, "Page": v.page_display_name, "Visual": v.visual_title or v.visual_name,
                             "Type": v.visual_type, "Status": v.status.value,
                             "Error": v.error_message or v.truncation_info or "", "Error code": v.error_code})
    return rows


def unsupported_rows(run: ComparisonRunResult) -> list[dict[str, Any]]:
    return [{"Role": ext.role, "Page": v.page_display_name, "Visual": v.visual_title or v.visual_name,
             "Visual ID": v.visual_name, "Type": v.visual_type, "Reason": v.error_message, "Fallback": "Manual review or "
             "Execute Queries fallback (labelled reconstructed data) — see docs"}
            for ext in (run.original, run.migrated) for v in ext.visuals if v.status == ExtractionStatus.UNSUPPORTED]


def evidence_rows(run: ComparisonRunResult) -> list[dict[str, Any]]:
    rows = []
    for ext in (run.original, run.migrated):
        ctx = ext.context
        for item in inventory(ext):
            rows.append({**{k.replace("_", " ").title(): v for k, v in item.items()},
                         "Workspace ID": ext.workspace_id, "Report ID": ext.report_id,
                         "Context status": ctx.status.value, "Context action": ctx.action_taken,
                         "Context messages": " | ".join(ctx.messages)})
    return rows
