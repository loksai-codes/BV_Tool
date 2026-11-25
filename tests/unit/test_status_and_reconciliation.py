"""Status classification & reconciliation edge cases (in-memory extraction objects)."""
from __future__ import annotations

from core.contracts import (
    ComparisonConfig,
    ComparisonStatus,
    Completeness,
    ContextStatus,
    CountryContextConfig,
    ExtractionStatus,
    FilterContextEvidence,
    PageInfo,
    ReportExtraction,
    SourceMethod,
    VisualExtraction,
    VisualMapping,
)
from comparison.reconciliation import run_comparison

CFG = ComparisonConfig(country=CountryContextConfig(original_table="Geo", original_column="Country",
                                                    migrated_table="Geo", migrated_column="Country"))


def V(name, csv, status=ExtractionStatus.SUCCESS, completeness=Completeness.COMPLETE, vtype="tableEx", **kw):
    return VisualExtraction(workspace_id="w", report_id="r", page_name="P", page_display_name="P", visual_name=name,
                            visual_type=vtype, visual_title=name, status=status, completeness=completeness, raw_csv=csv, **kw)


def R(role, visuals, ctx=ContextStatus.VALIDATED, fatal=None):
    return ReportExtraction(role=role, workspace_id="w", report_id="r", pages=[PageInfo(name="P", display_name="P")],
                            visuals=visuals, context=FilterContextEvidence(status=ctx), fatal_error=fatal)


def run(o_vis, m_vis, octx=ContextStatus.VALIDATED, mctx=ContextStatus.NOT_REQUIRED, approve=True, cfg=CFG, fatal=None):
    maps = [VisualMapping(original_page="P", original_visual=a.visual_name, migrated_page="P", migrated_visual=b.visual_name,
                          approved=approve) for a, b in zip(o_vis, m_vis)]
    c = cfg.model_copy(update={"visual_mappings": maps})
    return run_comparison(R("original", o_vis, octx, fatal), R("migrated", m_vis, mctx), c)


T1 = "Cat,Sales\r\nA,10\r\nB,20\r\n"


def test_pass_when_identical():
    r = run([V("o", T1)], [V("m", T1)])
    assert r.visual_results[0].status == ComparisonStatus.PASS and r.overall_status == ComparisonStatus.PASS


def test_fail_on_value_mismatch():
    r = run([V("o", T1)], [V("m", "Cat,Sales\r\nA,10\r\nB,21\r\n")])
    vr = r.visual_results[0]
    assert vr.status == ComparisonStatus.FAIL and vr.numeric_mismatches == 1
    assert r.overall_status == ComparisonStatus.FAIL


def test_context_not_validated_is_inconclusive_never_fail_or_pass():
    r = run([V("o", T1)], [V("m", "Cat,Sales\r\nA,10\r\nB,21\r\n")], octx=ContextStatus.UNVERIFIED)
    assert r.visual_results[0].status == ComparisonStatus.INCONCLUSIVE
    assert r.overall_status == ComparisonStatus.INCONCLUSIVE
    r = run([V("o", T1)], [V("m", T1)], octx=ContextStatus.CONFLICT)
    assert r.overall_status == ComparisonStatus.INCONCLUSIVE


def test_migrated_context_invalid_inconclusive():
    r = run([V("o", T1)], [V("m", T1)], mctx=ContextStatus.INVALID)
    assert r.overall_status == ComparisonStatus.INCONCLUSIVE


def test_truncated_export_partial_never_pass():
    r = run([V("o", T1, ExtractionStatus.POSSIBLY_TRUNCATED, Completeness.UNKNOWN, truncation_info="limit")], [V("m", T1)])
    assert r.visual_results[0].status == ComparisonStatus.PARTIAL
    assert r.overall_status == ComparisonStatus.PARTIAL


def test_truncated_missing_rows_unconfirmed_partial():
    r = run([V("o", T1, ExtractionStatus.POSSIBLY_TRUNCATED, Completeness.UNKNOWN)], [V("m", "Cat,Sales\r\nA,10\r\n")])
    assert r.visual_results[0].status == ComparisonStatus.PARTIAL


def test_failed_extraction_inconclusive():
    r = run([V("o", None, ExtractionStatus.FAILED, Completeness.INCOMPLETE, error_message="boom")], [V("m", T1)])
    assert r.visual_results[0].status == ComparisonStatus.INCONCLUSIVE
    assert r.overall_status == ComparisonStatus.INCONCLUSIVE


def test_unsupported_and_not_mapped():
    o = [V("o", T1), V("custom", None, ExtractionStatus.UNSUPPORTED, Completeness.INCOMPLETE, vtype="xyzVisual")]
    r = run_comparison(R("original", o), R("migrated", [V("m", T1)], ContextStatus.NOT_REQUIRED),
                       CFG.model_copy(update={"visual_mappings": [VisualMapping(original_page="P", original_visual="o",
                                                                                 migrated_page="P", migrated_visual="m", approved=True)]}))
    st = {x.original_visual: x.status for x in r.visual_results}
    assert st["custom"] == ComparisonStatus.UNSUPPORTED
    assert r.overall_status == ComparisonStatus.PARTIAL  # PASS impossible with unsupported mandatory visual


def test_unapproved_mapping_is_not_mapped():
    r = run([V("o", T1)], [V("m", T1)], approve=False)
    assert r.visual_results[0].status == ComparisonStatus.NOT_MAPPED
    assert r.overall_status == ComparisonStatus.INCONCLUSIVE  # nothing compared


def test_data_level_context_violation():
    o = V("o", "Country,Sales\r\nChina,1\r\nIndia,2\r\n")
    r = run([o], [V("m", "Country,Sales\r\nChina,1\r\n")])
    vr = r.visual_results[0]
    assert vr.status == ComparisonStatus.INCONCLUSIVE and "India" in vr.reasons[0]


def test_visual_filter_conflict():
    f = {"target": {"table": "Geo", "column": "Country"}, "operator": "In", "values": ["Japan"], "filterType": 1}
    r = run([V("o", T1, visual_filters=[f])], [V("m", T1)])
    assert r.visual_results[0].status == ComparisonStatus.INCONCLUSIVE


def test_integrity_failure_inconclusive():
    o = V("o", T1)
    o.raw_sha256 = "0" * 64
    r = run([o], [V("m", T1)])
    assert r.visual_results[0].status == ComparisonStatus.INCONCLUSIVE


def test_fallback_without_equivalence_partial():
    r = run([V("o", T1, source_method=SourceMethod.FALLBACK_QUERY)], [V("m", T1)])
    assert r.visual_results[0].status == ComparisonStatus.PARTIAL


def test_fatal_load_error_inconclusive():
    r = run([V("o", T1)], [V("m", T1)], fatal="Report load failed")
    assert r.overall_status == ComparisonStatus.INCONCLUSIVE


def test_originals_unchanged_after_reconciliation():
    o = V("o", " A ,1\r\n")
    raw = o.raw_csv
    run([o], [V("m", "A,2\r\n")])
    assert o.raw_csv == raw and o.integrity_ok()


def test_wide_matrix_unpivot():
    o = V("o", "Category,2024 Q1,2024 Q2,2024 Q3\r\nA,1,2,3\r\nB,4,5,6\r\n", vtype="pivotTable")
    m = V("m", "Category,Q1 2024,Q2 2024,Q3 2024\r\nA,1,2,3\r\nB,4,5,7\r\n", vtype="pivotTable")
    r = run([o], [m])
    vr = r.visual_results[0]
    assert vr.status == ComparisonStatus.FAIL and vr.numeric_mismatches == 1
    assert vr.rows_compared == 6
