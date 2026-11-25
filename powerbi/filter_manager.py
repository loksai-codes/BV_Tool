"""Country (China) context planning and validation.

Verified basis (docs/TECHNICAL_VALIDATION.md §4): report/page/visual
``getFilters`` / ``updateFilters(FiltersOperations, filters)``; Basic filter
shape; FilterType.Basic == 1; filter levels are independent.

Known limitation (documented): the JS API may not expose every effective
filter (hidden Desktop filters, cross-highlighting, RLS). VALIDATED therefore
means "validated against everything the API exposes", never "proven equal".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from core.contracts import ContextStatus, CountryContextConfig, FilterContextEvidence

BASIC_SCHEMA = "http://powerbi.com/product/schema#basic"
FILTER_TYPE_BASIC = 1


def build_basic_filter(table: str, column: str, value: str) -> dict[str, Any]:
    if not table or not column:
        raise ValueError("Country filter requires both table and column names (configure them; nothing is hardcoded)")
    return {
        "$schema": BASIC_SCHEMA,
        "target": {"table": table, "column": column},
        "operator": "In",
        "values": [value],
        "filterType": FILTER_TYPE_BASIC,
    }


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def targets_field(f: dict[str, Any], table: str, column: str) -> bool:
    t = f.get("target") or {}
    if isinstance(t, list):  # tuple targets — not supported by API docs; treat as matching if any element matches
        return any(_norm(x.get("table")) == _norm(table) and _norm(x.get("column")) == _norm(column) for x in t)
    col = t.get("column") or t.get("hierarchyLevel")
    return _norm(t.get("table")) == _norm(table) and _norm(col) == _norm(column)


def is_basic(f: dict[str, Any]) -> bool:
    ft = f.get("filterType")
    return ft == FILTER_TYPE_BASIC or str(f.get("$schema", "")).endswith("#basic")


def filter_effect(f: dict[str, Any], value: str) -> Literal["restricts_to_value", "allows_value", "excludes_value", "no_effect", "unknown"]:
    """How a filter on the country field relates to the configured value."""
    if not is_basic(f):
        return "unknown"
    op = str(f.get("operator", "")).lower()
    vals = [_norm(v) for v in (f.get("values") or [])]
    v = _norm(value)
    if op == "all" or (op == "in" and not vals):
        return "no_effect"
    if op == "in":
        if vals == [v]:
            return "restricts_to_value"
        return "allows_value" if v in vals else "excludes_value"
    if op == "notin":
        return "excludes_value" if v in vals else "allows_value"
    return "unknown"


def _fkey(f: dict[str, Any]) -> str:
    import json

    return json.dumps(f, sort_keys=True, default=str)


@dataclass
class ContextPlan:
    action: Literal["none", "add", "replace", "conflict"]
    filter: dict[str, Any] | None = None
    reason: str = ""


def plan_context(existing: list[dict[str, Any]], table: str, column: str, value: str, allow_replace: bool) -> ContextPlan:
    desired = build_basic_filter(table, column, value)
    on_target = [f for f in existing if targets_field(f, table, column)]
    if not on_target:
        return ContextPlan("add", desired, "No existing report filter on the country field; adding Basic In filter.")
    if len(on_target) == 1 and filter_effect(on_target[0], value) == "restricts_to_value":
        return ContextPlan("none", None, "Existing report filter already restricts the country field to the configured value.")
    if allow_replace:
        return ContextPlan("replace", desired, "Existing filter on the country field differs; replacing it (explicitly allowed). Other fields untouched.")
    return ContextPlan(
        "conflict", None,
        "An existing report filter on the country field has a different/complex value. Not overwritten "
        "(enable 'allow replace conflicting filter' to replace it). Context cannot be validated.",
    )


@dataclass
class ContextInputs:
    required: bool
    table: str
    column: str
    value: str
    before: list[dict[str, Any]]
    after: list[dict[str, Any]]
    page_filters: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    slicer_states: list[dict[str, Any]] = field(default_factory=list)
    plan: ContextPlan | None = None
    apply_failed: str | None = None
    capture_errors: list[str] = field(default_factory=list)
    bookmark_captured: bool = False


def validate_context(ci: ContextInputs) -> FilterContextEvidence:
    ev = FilterContextEvidence(
        required=ci.required, target_table=ci.table, target_column=ci.column, value=ci.value,
        report_filters_before=ci.before, report_filters_after=ci.after, page_filters=ci.page_filters,
        slicer_states=ci.slicer_states, bookmark_state_captured=ci.bookmark_captured,
        action_taken=ci.plan.action if ci.plan else None,
    )
    msgs = ev.messages
    if ci.plan:
        msgs.append(ci.plan.reason)
    msgs.extend(f"Capture error: {e}" for e in ci.capture_errors)
    msgs.append("Note: the Power BI JS API may not expose every effective filter (hidden filters, cross-highlighting, RLS).")

    invalid = False
    unverifiable = False

    if ci.apply_failed:
        msgs.append(f"Applying the context filter failed: {ci.apply_failed}")
        invalid = True
    if ci.plan and ci.plan.action == "conflict":
        ev.status = ContextStatus.CONFLICT
        return ev
    if ci.capture_errors and ci.required:
        unverifiable = True

    # 1) unrelated filters must be preserved
    before_other = {_fkey(f) for f in ci.before if not targets_field(f, ci.table, ci.column)}
    after_other = {_fkey(f) for f in ci.after if not targets_field(f, ci.table, ci.column)}
    if before_other - after_other:
        msgs.append("Unrelated report filters changed after applying context.")
        invalid = True

    # 2) report-level filter on the country field
    on_target = [f for f in ci.after if targets_field(f, ci.table, ci.column)]
    if ci.required:
        if len(on_target) != 1 or filter_effect(on_target[0], ci.value) != "restricts_to_value":
            msgs.append(f"Report-level filter restricting {ci.table}[{ci.column}] to '{ci.value}' not confirmed after application.")
            invalid = True
        else:
            msgs.append(f"Report-level filter {ci.table}[{ci.column}] In ['{ci.value}'] confirmed.")
    else:
        for f in on_target:
            eff = filter_effect(f, ci.value)
            if eff == "excludes_value":
                msgs.append(f"Report filter on {ci.table}[{ci.column}] excludes '{ci.value}'.")
                invalid = True
            elif eff == "unknown":
                msgs.append("Report filter on the country field could not be interpreted.")
                unverifiable = True

    # 3) page-level filters and slicers must not contradict
    for page, filters in ci.page_filters.items():
        for f in filters:
            if not targets_field(f, ci.table, ci.column):
                continue
            eff = filter_effect(f, ci.value)
            if eff == "excludes_value":
                msgs.append(f"Page '{page}' has a filter excluding '{ci.value}'.")
                invalid = True
            elif eff == "allows_value" and ci.required:
                msgs.append(f"Page '{page}' filter allows other values too; report filter still restricts (OK).")
            elif eff == "unknown":
                msgs.append(f"Page '{page}' has a non-basic filter on the country field; cannot verify.")
                unverifiable = True
    for s in ci.slicer_states:
        for f in (s.get("state") or {}).get("filters", []) or []:
            if not targets_field(f, ci.table, ci.column):
                continue
            eff = filter_effect(f, ci.value)
            if eff == "excludes_value":
                msgs.append(f"Slicer {s.get('visual')} on page {s.get('page')} excludes '{ci.value}'.")
                invalid = True
            elif eff == "unknown":
                msgs.append(f"Slicer {s.get('visual')} state on the country field cannot be interpreted.")
                unverifiable = True

    if invalid:
        ev.status = ContextStatus.INVALID
    elif unverifiable:
        ev.status = ContextStatus.UNVERIFIED
    elif ci.required:
        ev.status = ContextStatus.VALIDATED
    else:
        ev.status = ContextStatus.NOT_REQUIRED
        msgs.append("Context not applied (report expected to be single-country by design); no contradicting filters found. Data-level checks still apply.")
    return ev


def visual_filter_conflict(visual_filters: list[dict[str, Any]], table: str, column: str, value: str) -> str | None:
    for f in visual_filters or []:
        if targets_field(f, table, column):
            eff = filter_effect(f, value)
            if eff == "excludes_value":
                return f"Visual-level filter on {table}[{column}] excludes '{value}'."
            if eff == "unknown":
                return f"Visual-level filter on {table}[{column}] cannot be interpreted."
    return None


def data_context_violations(df: pd.DataFrame, header: str, value: str) -> list[str]:
    """If the exported data contains the country column, every non-blank value must equal ``value``."""
    if not header or df.empty:
        return []
    match = [c for c in df.columns if _norm(c) == _norm(header)]
    if not match:
        return []
    vals = {str(x).strip() for x in df[match[0]].tolist() if str(x).strip() != ""}
    return sorted(v for v in vals if _norm(v) != _norm(value))


def config_problems(cfg: CountryContextConfig) -> list[str]:
    p = []
    if not cfg.original_table or not cfg.original_column:
        p.append("Original country field (table and column) must be configured.")
    if not cfg.value.strip():
        p.append("Country value must not be empty.")
    if cfg.apply_to_migrated and (not cfg.migrated_table or not cfg.migrated_column):
        p.append("Migrated country field (table and column) must be configured when applying context to migrated report.")
    return p
