"""Reconciliation of matched visuals and whole comparison runs.

Workflow per visual pair: load raw -> apply approved column mapping -> (matrix
unpivot) -> normalize derived copies -> establish keys -> compare -> classify.
Raw extracted data is never modified (``VisualExtraction.dataframe()`` returns a
new frame each call; integrity is verified via SHA-256 before comparison).
"""
from __future__ import annotations

from typing import Any

from comparison import matrix_comparator as mx
from comparison import status_manager as sm
from comparison.column_mapper import apply_column_mappings, suggest_column_mappings
from comparison.data_comparator import compare_frames
from comparison.data_normalizer import DataNormalizer, coarsest
from core.contracts import (
    ColumnMapping,
    ComparisonConfig,
    ComparisonRunResult,
    ComparisonStatus,
    ExtractionStatus,
    MismatchRecord,
    MismatchType,
    ReportExtraction,
    VisualComparisonResult,
    VisualExtraction,
    VisualMapping,
    utcnow,
)
from powerbi import filter_manager as fm

MAX_NORMALIZED_ROWS_STORED = 5000


def _base_result(o: VisualExtraction | None, m: VisualExtraction | None, mapping: VisualMapping | None,
                 mandatory: bool) -> VisualComparisonResult:
    return VisualComparisonResult(
        original_page=o.page_name if o else None, original_visual=o.visual_name if o else None,
        original_title=o.visual_title if o else None, original_page_display=o.page_display_name if o else None,
        migrated_page=m.page_name if m else None, migrated_visual=m.visual_name if m else None,
        migrated_title=m.visual_title if m else None, migrated_page_display=m.page_display_name if m else None,
        visual_type=(o or m).visual_type if (o or m) else None, mandatory=mandatory,
        status=ComparisonStatus.INCONCLUSIVE,
        mapping_confidence=mapping.confidence if mapping else None,
        mapping_provenance=mapping.provenance if mapping else None,
        source_methods=sorted({v.source_method.value for v in (o, m) if v is not None}),
    )


def _records(df) -> list[dict[str, Any]]:
    def conv(x):
        if isinstance(x, tuple) and len(x) == 2 and x[0] == "__INVALID__":
            return x[1]
        try:
            from decimal import Decimal

            if isinstance(x, Decimal):
                return format(x, "f")
        except Exception:  # pragma: no cover
            pass
        return x

    return [{k: conv(v) for k, v in row.items()} for row in df.head(MAX_NORMALIZED_ROWS_STORED).to_dict("records")]


def reconcile_pair(
    o: VisualExtraction,
    m: VisualExtraction,
    mapping: VisualMapping,
    config: ComparisonConfig,
    context_reasons: list[str],
) -> VisualComparisonResult:
    res = _base_result(o, m, mapping, mapping.mandatory)
    pre = sm.precheck(o, m, True, context_reasons)
    if pre.status is not None:
        res.status, res.reasons = pre.status, pre.reasons
        return res

    rules = config.normalization
    normalizer = DataNormalizer(rules)
    o_raw, m_raw = o.dataframe(), m.dataframe()   # fresh derived copies
    if rules.trim_whitespace:
        o_raw.columns = [str(c).strip() for c in o_raw.columns]
        m_raw.columns = [str(c).strip() for c in m_raw.columns]
        res.normalization_applied.append("trim whitespace (column headers)")
    res.rows_original, res.rows_migrated = len(o_raw), len(m_raw)

    # ---- data-level & visual-filter context validation
    ctx_problems: list[str] = []
    for side, df, header in (("original", o_raw, config.country.original_header),
                             ("migrated", m_raw, config.country.migrated_header)):
        bad = fm.data_context_violations(df, header, config.country.value)
        if bad:
            ctx_problems.append(f"{side} export contains country values other than '{config.country.value}': {bad[:10]}")
            res.mismatches.append(MismatchRecord(mismatch_type=MismatchType.CONTEXT_VIOLATION, column=header,
                                                 original_value=bad[:10] if side == "original" else None,
                                                 migrated_value=bad[:10] if side == "migrated" else None,
                                                 detail=f"{side} data not restricted to configured country"))
    for side, v, table, column in (("original", o, config.country.original_table, config.country.original_column),
                                   ("migrated", m, config.country.migrated_table, config.country.migrated_column)):
        if table and column:
            c = fm.visual_filter_conflict(v.visual_filters, table, column, config.country.value)
            if c:
                ctx_problems.append(f"{side}: {c}")
    if ctx_problems:
        res.status, res.reasons = ComparisonStatus.INCONCLUSIVE, ctx_problems
        return res

    # ---- column mapping
    mappings = list(mapping.column_mappings)
    if not mappings:
        mappings = suggest_column_mappings(o_raw, m_raw, normalizer)
        res.notes.append("Column mapping auto-suggested (no approved column mapping provided).")
    res.column_mappings_used = [cm.model_dump() for cm in mappings]
    o_df, m_df, unmapped = apply_column_mappings(o_raw, m_raw, mappings)
    res.unmapped_columns = {k: v for k, v in unmapped.items() if v}
    if o_df.empty and not len(o_df.columns):
        res.status, res.reasons = ComparisonStatus.INCONCLUSIVE, ["No columns could be mapped between the two exports."]
        return res

    # ---- column roles
    explicit_keys = [k for k in mapping.key_columns if k in o_df.columns]
    key_roles = [cm.original for cm in mappings if cm.role == "key" and cm.provenance == "manual" and cm.original in o_df.columns]
    value_roles = {cm.original for cm in mappings if cm.role == "value" and cm.original in o_df.columns}
    numeric = sorted(set(normalizer.infer_numeric_columns(o_df)) & set(normalizer.infer_numeric_columns(m_df)) | value_roles,
                     key=list(o_df.columns).index)
    keys = explicit_keys or key_roles or [c for c in o_df.columns if c not in numeric]
    numeric = [c for c in numeric if c not in keys]
    values = [c for c in o_df.columns if c not in keys]

    # ---- matrix wide layout -> long
    unpivot = mapping.unpivot
    if unpivot is None and "pivotTable" in (o.visual_type, m.visual_type):
        unpivot = mx.looks_wide(o_df, normalizer) and mx.looks_wide(m_df, normalizer)
    if unpivot:
        id_o, val_o = mx.split_wide(o_df, normalizer)
        id_m, val_m = mx.split_wide(m_df, normalizer)
        o_df = mx.unpivot(o_df, id_o, val_o)
        m_df = mx.unpivot(m_df, id_m, val_m)
        keys = id_o + [mx.COLUMN_CATEGORY_NAME]
        numeric = values = [mx.VALUE_NAME]
        res.notes.append("Matrix exported in wide layout; unpivoted column categories to long format before comparison.")

    # ---- date normalization (explicit config, else auto-detected on key columns)
    date_cols: dict[str, str] = {}
    for c in keys:
        if c in rules.date_columns:
            date_cols[c] = rules.date_columns[c]
        elif rules.auto_detect_dates:
            go = normalizer.infer_date_granularity(o_df[c])
            gm = normalizer.infer_date_granularity(m_df[c])
            if go and gm:
                date_cols[c] = coarsest(go, gm)  # type: ignore[assignment]
                if go != gm:
                    res.notes.append(f"Date column '{c}': original granularity {go}, migrated {gm}; compared at {date_cols[c]}.")

    o_n = normalizer.normalize(o_df, numeric, date_cols)
    m_n = normalizer.normalize(m_df, numeric, date_cols)
    res.normalization_applied = list(dict.fromkeys(res.normalization_applied + o_n.applied + m_n.applied))
    for side, nf in (("original", o_n), ("migrated", m_n)):
        for c, n in nf.invalid_numbers.items():
            res.notes.append(f"{side}: {n} non-numeric value(s) in numeric column '{c}' compared as text.")
        for c, n in nf.unparsed_dates.items():
            res.notes.append(f"{side}: {n} unparsed date value(s) in '{c}' kept as text.")
    res.normalized_original = _records(o_n.df)
    res.normalized_migrated = _records(m_n.df)

    # ---- compare
    rows_confirmable = all(v.status == ExtractionStatus.SUCCESS and v.completeness.value == "COMPLETE" for v in (o, m))
    tol = mapping.tolerance or config.tolerance
    fc = compare_frames(o_n, m_n, keys, values, tol, rows_confirmable=rows_confirmable)
    res.key_columns, res.value_columns = fc.key_columns, fc.value_columns
    res.rows_compared, res.rows_matched = fc.rows_compared, fc.rows_matched
    res.matching_records = fc.matching
    res.mismatches.extend(fc.mismatches)
    res.missing_rows = fc.count(MismatchType.MISSING_RECORD)
    res.additional_rows = fc.count(MismatchType.ADDITIONAL_RECORD)
    res.numeric_mismatches = fc.count(MismatchType.VALUE_MISMATCH) + fc.count(MismatchType.NULL_MISMATCH)
    res.duplicate_keys = fc.count(MismatchType.DUPLICATE_KEY)
    res.missing_categories, res.additional_categories = fc.missing_categories, fc.additional_categories
    res.derived_totals = fc.derived_totals
    res.notes.extend(fc.notes)
    res.status, res.reasons = sm.classify_compared(res, o, m, fc.keys_established, rows_confirmable)
    if tol.absolute or tol.percentage:
        res.notes.append(f"Tolerance applied: absolute={tol.absolute}, percentage={tol.percentage}%.")
    return res


def run_comparison(
    original: ReportExtraction,
    migrated: ReportExtraction,
    config: ComparisonConfig,
    name: str | None = None,
) -> ComparisonRunResult:
    started = utcnow()
    context_reasons: list[str] = []
    for ext in (original, migrated):
        ok, why = sm.context_ok(ext, config.require_context_validation)
        if not ok:
            context_reasons.append(why)  # type: ignore[arg-type]

    approved = [vm for vm in config.visual_mappings if vm.approved]
    results: list[VisualComparisonResult] = []
    used_o: set[tuple[str, str]] = set()
    used_m: set[tuple[str, str]] = set()
    for vm in approved:
        o = original.find(vm.original_page, vm.original_visual)
        m = migrated.find(vm.migrated_page, vm.migrated_visual)
        if o is None or m is None:
            r = _base_result(o, m, vm, vm.mandatory)
            r.status = ComparisonStatus.NOT_MAPPED
            r.reasons = ["Approved mapping refers to a visual that was not found in this extraction."]
            results.append(r)
            continue
        used_o.add((o.page_name, o.visual_name))
        used_m.add((m.page_name, m.visual_name))
        results.append(reconcile_pair(o, m, vm, config, context_reasons))

    # suggested-but-unapproved mappings: one NOT_MAPPED row naming the candidate
    for vm in config.visual_mappings:
        if vm.approved:
            continue
        o = original.find(vm.original_page, vm.original_visual)
        m = migrated.find(vm.migrated_page, vm.migrated_visual)
        if o is None or m is None or (o.page_name, o.visual_name) in used_o or (m.page_name, m.visual_name) in used_m:
            continue
        r = _base_result(o, m, vm, vm.mandatory)
        pre = sm.precheck(o, m, False, [])
        r.status = pre.status if pre.status == ComparisonStatus.UNSUPPORTED else ComparisonStatus.NOT_MAPPED
        r.reasons = (pre.reasons if r.status == ComparisonStatus.UNSUPPORTED else []) + [
            f"Suggested match (confidence {vm.confidence:.2f}, {vm.provenance}) awaiting approval: {vm.explanation}"]
        used_o.add((o.page_name, o.visual_name))
        used_m.add((m.page_name, m.visual_name))
        results.append(r)

    # unmatched visuals are reported, never silently dropped
    for v in original.visuals:
        if v.status == ExtractionStatus.SKIPPED_NON_DATA or (v.page_name, v.visual_name) in used_o:
            continue
        r = _base_result(v, None, None, True)
        pre = sm.precheck(v, None, False, [])
        r.status, r.reasons = pre.status or ComparisonStatus.NOT_MAPPED, pre.reasons
        results.append(r)
    for v in migrated.visuals:
        if v.status == ExtractionStatus.SKIPPED_NON_DATA or (v.page_name, v.visual_name) in used_m:
            continue
        r = _base_result(None, v, None, False)
        pre = sm.precheck(None, v, False, [])
        r.status, r.reasons = pre.status or ComparisonStatus.NOT_MAPPED, pre.reasons + [
            "Visual exists only in the migrated report (informational, not mandatory)."]
        results.append(r)

    overall, reasons = sm.overall_status(results, original, migrated, config.require_context_validation)
    return ComparisonRunResult(
        name=name or config.name, overall_status=overall, overall_reasons=reasons, started_at=started,
        finished_at=utcnow(), is_mock=original.is_mock or migrated.is_mock, config=config,
        original=original, migrated=migrated, visual_results=results,
    )


def column_mappings_for(o: VisualExtraction, m: VisualExtraction, rules=None) -> list[ColumnMapping]:
    """Helper for the UI: suggested column mappings for a visual pair."""
    if not (o.has_data and m.has_data):
        return []
    return suggest_column_mappings(o.dataframe(), m.dataframe(), DataNormalizer(rules))
