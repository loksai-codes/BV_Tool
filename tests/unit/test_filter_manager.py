import pandas as pd

from core.contracts import ContextStatus
from powerbi import filter_manager as fm

T, C, V = "Geography", "CountryName", "China"
YEAR = {"$schema": fm.BASIC_SCHEMA, "target": {"table": "Calendar", "column": "Year"}, "operator": "In", "values": [2024], "filterType": 1}


def china(values=("China",), op="In"):
    return {"$schema": fm.BASIC_SCHEMA, "target": {"table": T, "column": C}, "operator": op, "values": list(values), "filterType": 1}


def test_build_filter_requires_field():
    f = fm.build_basic_filter(T, C, V)
    assert f["filterType"] == 1 and f["operator"] == "In" and f["values"] == ["China"]
    import pytest
    with pytest.raises(ValueError):
        fm.build_basic_filter("", C, V)


def test_filter_effect():
    assert fm.filter_effect(china(), V) == "restricts_to_value"
    assert fm.filter_effect(china(("China", "India")), V) == "allows_value"
    assert fm.filter_effect(china(("India",)), V) == "excludes_value"
    assert fm.filter_effect(china(("China",), "NotIn"), V) == "excludes_value"
    assert fm.filter_effect({"filterType": 0, "target": {"table": T, "column": C}}, V) == "unknown"
    assert fm.filter_effect(china((), "All"), V) == "no_effect"


def test_plan_add_none_conflict_replace():
    assert fm.plan_context([YEAR], T, C, V, False).action == "add"
    assert fm.plan_context([YEAR, china()], T, C, V, False).action == "none"
    assert fm.plan_context([china(("India",))], T, C, V, False).action == "conflict"
    assert fm.plan_context([china(("India",))], T, C, V, True).action == "replace"


def _ci(**kw):
    base = dict(required=True, table=T, column=C, value=V, before=[YEAR], after=[YEAR, china()])
    base.update(kw)
    return fm.ContextInputs(**base)


def test_validate_success_preserves_unrelated():
    ev = fm.validate_context(_ci(plan=fm.ContextPlan("add", china())))
    assert ev.status == ContextStatus.VALIDATED


def test_validate_unrelated_filter_lost_is_invalid():
    ev = fm.validate_context(_ci(after=[china()]))
    assert ev.status == ContextStatus.INVALID
    assert any("Unrelated" in m for m in ev.messages)


def test_validate_filter_not_applied_is_invalid():
    ev = fm.validate_context(_ci(after=[YEAR]))
    assert ev.status == ContextStatus.INVALID


def test_validate_conflict():
    ev = fm.validate_context(_ci(plan=fm.ContextPlan("conflict", None, "x"), after=[YEAR, china(("India",))]))
    assert ev.status == ContextStatus.CONFLICT


def test_page_filter_excluding_china_invalid():
    ev = fm.validate_context(_ci(page_filters={"P1": [china(("Japan",))]}))
    assert ev.status == ContextStatus.INVALID


def test_slicer_unknown_state_unverified():
    s = [{"page": "P1", "visual": "s1", "state": {"filters": [{"filterType": 0, "target": {"table": T, "column": C}}]}}]
    ev = fm.validate_context(_ci(slicer_states=s))
    assert ev.status == ContextStatus.UNVERIFIED


def test_capture_error_makes_unverified():
    ev = fm.validate_context(_ci(capture_errors=["getFilters failed"]))
    assert ev.status == ContextStatus.UNVERIFIED


def test_apply_failed_invalid():
    ev = fm.validate_context(_ci(after=[YEAR], apply_failed="boom"))
    assert ev.status == ContextStatus.INVALID


def test_not_required_migrated():
    ev = fm.validate_context(_ci(required=False, before=[], after=[]))
    assert ev.status == ContextStatus.NOT_REQUIRED
    ev = fm.validate_context(_ci(required=False, before=[china(("India",))], after=[china(("India",))]))
    assert ev.status == ContextStatus.INVALID


def test_data_context_violations():
    df = pd.DataFrame({"CountryName": ["China", "India", ""], "Sales": ["1", "2", "3"]})
    assert fm.data_context_violations(df, "countryname", "China") == ["India"]
    assert fm.data_context_violations(df, "Missing", "China") == []


def test_visual_filter_conflict():
    assert fm.visual_filter_conflict([china(("Japan",))], T, C, V)
    assert fm.visual_filter_conflict([china()], T, C, V) is None
