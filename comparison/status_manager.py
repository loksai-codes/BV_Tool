"""Comparison status classification with explicit precedence.

VISUAL precedence (first rule that applies wins):
  1. UNSUPPORTED  - either side's extraction is UNSUPPORTED (visual type / method unsupported)
  2. NOT_MAPPED   - no approved visual mapping
  3. INCONCLUSIVE - extraction failed / no data / integrity check failed; report context not
                    validated; data-level or visual-filter context violation; keys not established
  4. FAIL         - confirmed mismatches (values on matched keys; missing/additional
                    records only when both exports are complete)
  5. PARTIAL      - compared, but completeness unknown/truncated, unconfirmed missing/additional
                    rows, duplicate keys, unmapped columns, or fallback data without confirmed equivalence
  6. PASS         - everything extracted, validated, mapped and within tolerance

OVERALL precedence:
  1. INCONCLUSIVE - any report load failure, or required context not validated
  2. INCONCLUSIVE - no mandatory visual could be compared
  3. FAIL         - any mandatory visual FAIL
  4. INCONCLUSIVE - any mandatory visual INCONCLUSIVE
  5. PARTIAL      - any mandatory visual PARTIAL / UNSUPPORTED / NOT_MAPPED
  6. PASS
PASS is therefore impossible while any mandatory extraction, context or mapping is incomplete.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.contracts import (
    ComparisonStatus,
    Completeness,
    ContextStatus,
    ExtractionStatus,
    MismatchType,
    ReportExtraction,
    SourceMethod,
    VisualComparisonResult,
    VisualExtraction,
)

ORIGINAL_CONTEXT_OK = {ContextStatus.VALIDATED}
MIGRATED_CONTEXT_OK = {ContextStatus.VALIDATED, ContextStatus.NOT_REQUIRED}


def context_ok(ext: ReportExtraction, require_validation: bool) -> tuple[bool, str | None]:
    st = ext.context.status
    if ext.role == "original":
        if not require_validation and st != ContextStatus.INVALID:
            return True, None
        if st in ORIGINAL_CONTEXT_OK:
            return True, None
        return False, f"Original report context is {st.value}: China context not validated."
    if st in MIGRATED_CONTEXT_OK:
        return True, None
    if not require_validation and st == ContextStatus.UNVERIFIED:
        return True, None
    return False, f"Migrated report context is {st.value}."


@dataclass
class PreCheck:
    status: ComparisonStatus | None
    reasons: list[str] = field(default_factory=list)


def precheck(
    orig: VisualExtraction | None,
    mig: VisualExtraction | None,
    mapped: bool,
    context_reasons: list[str],
) -> PreCheck:
    reasons: list[str] = []
    for side, v in (("original", orig), ("migrated", mig)):
        if v is not None and v.status == ExtractionStatus.UNSUPPORTED:
            reasons.append(f"{side} visual '{v.visual_title or v.visual_name}' ({v.visual_type}) unsupported: {v.error_message}")
    if reasons:
        if not mapped:
            reasons.append("Visual is also not mapped to a counterpart.")
        return PreCheck(ComparisonStatus.UNSUPPORTED, reasons)
    if not mapped or orig is None or mig is None:
        return PreCheck(ComparisonStatus.NOT_MAPPED, ["No approved mapping to a visual in the other report."])
    for side, v in (("original", orig), ("migrated", mig)):
        if v.status in (ExtractionStatus.FAILED, ExtractionStatus.NOT_ATTEMPTED):
            reasons.append(f"{side} extraction {v.status.value}: {v.error_message or 'no detail'}")
        elif not v.has_data:
            reasons.append(f"{side} extraction produced no data ({v.status.value}).")
        elif not v.integrity_ok():
            reasons.append(f"{side} raw data failed SHA-256 integrity check.")
    reasons.extend(context_reasons)
    if reasons:
        return PreCheck(ComparisonStatus.INCONCLUSIVE, reasons)
    return PreCheck(None)


def classify_compared(
    result: VisualComparisonResult,
    orig: VisualExtraction,
    mig: VisualExtraction,
    keys_established: bool,
    rows_confirmable: bool,
) -> tuple[ComparisonStatus, list[str]]:
    reasons: list[str] = []
    if not keys_established:
        return ComparisonStatus.INCONCLUSIVE, ["Reliable key columns could not be established; configure key columns."]
    confirmed = [m for m in result.mismatches if m.confirmed and m.mismatch_type != MismatchType.MISSING_COLUMN]
    dups = [m for m in result.mismatches if m.mismatch_type == MismatchType.DUPLICATE_KEY]
    unconfirmed = [m for m in result.mismatches if not m.confirmed and m.mismatch_type != MismatchType.DUPLICATE_KEY]
    partial_reasons: list[str] = []
    for side, v in (("original", orig), ("migrated", mig)):
        if v.status == ExtractionStatus.POSSIBLY_TRUNCATED:
            partial_reasons.append(f"{side} export possibly truncated: {v.truncation_info}")
        elif v.completeness != Completeness.COMPLETE:
            partial_reasons.append(f"{side} export completeness {v.completeness.value}: {v.truncation_info or ''}".strip())
        if v.source_method == SourceMethod.FALLBACK_QUERY and not v.fallback_equivalence_confirmed:
            partial_reasons.append(f"{side} data is FALLBACK query data without confirmed visual equivalence.")
    if dups:
        partial_reasons.append(f"{len(dups)} duplicate key group(s): rows with non-unique keys were not value-compared (refine key columns).")
    if unconfirmed:
        partial_reasons.append(f"{len(unconfirmed)} missing/additional record(s) not confirmed (completeness not established).")
    unm = result.unmapped_columns
    if unm.get("original") or unm.get("migrated"):
        partial_reasons.append(f"Unmapped columns not compared: original={unm.get('original', [])}, migrated={unm.get('migrated', [])}")
    if not result.value_columns:
        partial_reasons.append("No value columns compared.")

    if confirmed:
        by_type: dict[str, int] = {}
        for m in confirmed:
            by_type[m.mismatch_type.value] = by_type.get(m.mismatch_type.value, 0) + 1
        reasons.append("Confirmed differences: " + ", ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
        reasons.extend(partial_reasons)
        return ComparisonStatus.FAIL, reasons
    if partial_reasons:
        return ComparisonStatus.PARTIAL, partial_reasons
    return ComparisonStatus.PASS, [f"All {result.rows_compared} compared record(s) within tolerance; extraction complete; context validated."]


def overall_status(
    results: list[VisualComparisonResult],
    original: ReportExtraction,
    migrated: ReportExtraction,
    require_context: bool,
) -> tuple[ComparisonStatus, list[str]]:
    reasons: list[str] = []
    for ext in (original, migrated):
        if ext.fatal_error:
            reasons.append(f"{ext.role} report: {ext.fatal_error}")
    for ext in (original, migrated):
        ok, why = context_ok(ext, require_context)
        if not ok:
            reasons.append(why)  # type: ignore[arg-type]
    if reasons:
        return ComparisonStatus.INCONCLUSIVE, reasons
    mandatory = [r for r in results if r.mandatory]
    compared = [r for r in mandatory if r.status in (ComparisonStatus.PASS, ComparisonStatus.FAIL, ComparisonStatus.PARTIAL)]
    if not compared:
        return ComparisonStatus.INCONCLUSIVE, ["No mandatory visual could be compared."]
    counts = {s: sum(1 for r in mandatory if r.status == s) for s in ComparisonStatus}
    summary = ", ".join(f"{s.value}={n}" for s, n in counts.items() if n)
    if counts[ComparisonStatus.FAIL]:
        return ComparisonStatus.FAIL, [f"{counts[ComparisonStatus.FAIL]} mandatory visual(s) have confirmed differences ({summary})."]
    if counts[ComparisonStatus.INCONCLUSIVE]:
        return ComparisonStatus.INCONCLUSIVE, [f"{counts[ComparisonStatus.INCONCLUSIVE]} mandatory visual(s) inconclusive ({summary})."]
    incomplete = counts[ComparisonStatus.PARTIAL] + counts[ComparisonStatus.UNSUPPORTED] + counts[ComparisonStatus.NOT_MAPPED]
    if incomplete:
        return ComparisonStatus.PARTIAL, [f"{incomplete} mandatory visual(s) partial, unsupported or not mapped ({summary})."]
    return ComparisonStatus.PASS, [f"All {len(mandatory)} mandatory visual(s) passed."]
