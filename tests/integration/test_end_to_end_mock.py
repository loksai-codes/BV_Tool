"""MOCK end-to-end: mock extraction -> matching -> reconciliation -> persistence -> reload.
Asserts the exact injected differences D1-D3 (sample_data/mock_reports.py). NOT live."""
from __future__ import annotations

from decimal import Decimal

from core.contracts import ComparisonStatus, MismatchType
from services.comparison_service import run_demo


def _by_title(run):
    return {r.original_title: r for r in run.visual_results if r.original_title}


def test_demo_only_high_confidence_auto_approved(repo):
    run = run_demo(repo)
    assert run.is_mock
    approved = [m for m in run.config.visual_mappings if m.approved]
    assert approved and all(m.confidence >= 0.85 for m in approved)
    # unapproved suggestions are NOT MAPPED, never compared
    assert any(r.status == ComparisonStatus.NOT_MAPPED and "awaiting approval" in " ".join(r.reasons) for r in run.visual_results)


def test_demo_full_findings(repo):
    run = run_demo(repo, approve_all_suggestions=True)
    t = _by_title(run)
    assert run.overall_status == ComparisonStatus.FAIL
    assert t["Units Trend"].status == ComparisonStatus.PASS
    assert t["Target Bullet"].status == ComparisonStatus.UNSUPPORTED
    assert t["R Forecast"].status == ComparisonStatus.UNSUPPORTED

    table = t["Sales by Category and Month"]
    kinds = {(m.mismatch_type, tuple(sorted(m.key.items()))) for m in table.mismatches}
    assert (MismatchType.VALUE_MISMATCH, (("Category", "Electronics"), ("Month", "2024-03"))) in kinds   # D1
    assert (MismatchType.MISSING_RECORD, (("Category", "Home"), ("Month", "2024-07"))) in kinds          # D2
    assert (MismatchType.ADDITIONAL_RECORD, (("Category", "Accessories"), ("Month", "2024-12"))) in kinds  # D3
    d1 = next(m for m in table.mismatches if m.mismatch_type == MismatchType.VALUE_MISMATCH)
    assert d1.absolute_difference == Decimal("1500.00")
    # D4 (+0.004) hidden by configured 2-dp rounding -> no Apparel/May mismatch
    assert not any(m.key.get("Category") == "Apparel" for m in table.mismatches)

    card = t["Total Sales"]
    assert card.status == ComparisonStatus.FAIL and card.mismatches[0].absolute_difference == Decimal("-26990.26")
    assert t["Sales Share by Category"].additional_categories == {"Category": ["Accessories"]}
    margin = next(r for r in run.visual_results if r.migrated_title == "Margin %")
    assert margin.status == ComparisonStatus.NOT_MAPPED and not margin.mandatory


def test_persist_and_reload_roundtrip(repo):
    run = run_demo(repo, approve_all_suggestions=True)
    loaded = repo.load_run(run.run_id)
    assert loaded is not None and loaded.overall_status == run.overall_status and loaded.is_mock
    assert len(loaded.visual_results) == len(run.visual_results)
    assert all(v.integrity_ok() for v in loaded.original.visuals)
    o_card = next(v for v in loaded.original.visuals if v.visual_title == "Total Sales")
    assert o_card.raw_csv == next(v for v in run.original.visuals if v.visual_title == "Total Sales").raw_csv
    st = repo.stats()
    assert st["total_runs"] == 1 and st["last_status"] == "FAIL" and st["total_mismatches"] > 0
    assert repo.list_runs()[0]["id"] == run.run_id
    assert any(a["action"] == "comparison_saved" for a in repo.audit_entries())


def test_mapping_profile_reuse(repo):
    from services.comparison_service import apply_profile, demo_config

    run = run_demo(None, approve_all_suggestions=True)
    repo.save_mapping_profile("default", run.original.report_id, run.migrated.report_id, run.config.page_mappings,
                              run.config.visual_mappings)
    profiles = repo.load_mapping_profiles(run.original.report_id, run.migrated.report_id)
    assert len(profiles) == 1
    cfg = apply_profile(demo_config(), profiles[0])
    assert all(v.approved and v.provenance == "manual" for v in cfg.visual_mappings)


def test_retention_purge(repo):
    run_demo(repo)
    assert repo.purge_older_than(-1) == 1
    assert repo.stats()["total_runs"] == 0
