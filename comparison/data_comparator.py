"""Key-based record and value comparison of two normalized frames.

Difference definitions (documented in README):
  Absolute Difference   = Migrated - Original
  Percentage Difference = (Absolute Difference / Original) * 100   (literal formula; sign follows it)
  - both values null/blank      -> match, no difference computed
  - exactly one value null      -> NULL_MISMATCH (unless treat_null_as_zero), no % computed
  - original == 0 and migrated == 0 -> 0 / 0%
  - original == 0, migrated != 0 -> percentage UNDEFINED (None) with note; never inf / misleading
Tolerance: match if |abs| <= absolute tolerance, OR (percentage tolerance > 0 and % defined and
|%| <= percentage tolerance). Defaults (0, 0) mean exact equality on Decimal values.
Row order is never meaningful: rows are matched on key columns only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pandas as pd

from comparison.data_normalizer import NormalizedFrame
from core.contracts import MismatchRecord, MismatchType, ToleranceConfig

PCT_Q = Decimal("0.000001")


@dataclass
class ValueComparison:
    match: bool
    absolute: Decimal | None = None
    percentage: Decimal | None = None
    note: str | None = None
    mismatch_type: MismatchType | None = None


def _is_invalid(v: Any) -> bool:
    return isinstance(v, tuple) and len(v) == 2 and v[0] == "__INVALID__"


def compare_numbers(o: Any, m: Any, tol: ToleranceConfig) -> ValueComparison:
    if _is_invalid(o) or _is_invalid(m):
        ov = o[1] if _is_invalid(o) else o
        mv = m[1] if _is_invalid(m) else m
        same = str(ov) == str(mv)
        return ValueComparison(same, note=None if same else "non-numeric value present",
                               mismatch_type=None if same else MismatchType.VALUE_MISMATCH)
    if o is None and m is None:
        return ValueComparison(True, note="both null")
    if o is None or m is None:
        return ValueComparison(False, note="null on one side", mismatch_type=MismatchType.NULL_MISMATCH)
    o, m = Decimal(o), Decimal(m)
    diff = m - o
    if o == 0:
        pct = Decimal(0) if m == 0 else None
        note = None if m == 0 else "percentage undefined: original value is zero"
    else:
        pct = (diff / o * 100).quantize(PCT_Q)
        note = None
    within = abs(diff) <= tol.absolute
    if not within and tol.percentage > 0 and pct is not None:
        within = abs(pct) <= tol.percentage
    return ValueComparison(within, diff, pct, note, None if within else MismatchType.VALUE_MISMATCH)


def compare_text(o: Any, m: Any) -> ValueComparison:
    if o is None and m is None:
        return ValueComparison(True, note="both null")
    if o is None or m is None:
        return ValueComparison(False, note="null on one side", mismatch_type=MismatchType.NULL_MISMATCH)
    same = str(o) == str(m)
    return ValueComparison(same, mismatch_type=None if same else MismatchType.VALUE_MISMATCH)


def _display(v: Any) -> Any:
    if _is_invalid(v):
        return v[1]
    if isinstance(v, Decimal):
        return format(v, "f")
    return v


@dataclass
class FrameComparison:
    keys_established: bool
    key_columns: list[str]
    value_columns: list[str]
    rows_original: int
    rows_migrated: int
    rows_compared: int = 0
    rows_matched: int = 0
    matching: list[dict[str, Any]] = field(default_factory=list)
    mismatches: list[MismatchRecord] = field(default_factory=list)
    missing_categories: dict[str, list[str]] = field(default_factory=dict)
    additional_categories: dict[str, list[str]] = field(default_factory=dict)
    derived_totals: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def count(self, t: MismatchType, confirmed_only: bool = False) -> int:
        return sum(1 for m in self.mismatches if m.mismatch_type == t and (m.confirmed or not confirmed_only))


def _key_tuple(row: pd.Series, keys: list[str]) -> tuple:
    return tuple(row[k] for k in keys)


def compare_frames(
    o: NormalizedFrame,
    m: NormalizedFrame,
    key_columns: list[str],
    value_columns: list[str],
    tolerance: ToleranceConfig,
    rows_confirmable: bool = True,
    max_matching_records: int = 5000,
) -> FrameComparison:
    """``rows_confirmable``: False when either export may be incomplete — then missing/additional
    records are reported but not *confirmed* (they may lie beyond the export limit)."""
    od, md = o.df, m.df
    res = FrameComparison(True, list(key_columns), list(value_columns), len(od), len(md))
    numeric = set(o.numeric_columns) | set(m.numeric_columns)

    def cmp(col, ov, mv):
        return compare_numbers(ov, mv, tolerance) if col in numeric else compare_text(ov, mv)

    # ---- keyless (cards / single-row visuals)
    if not key_columns:
        if len(od) <= 1 and len(md) <= 1:
            if len(od) == 0 or len(md) == 0:
                if len(od) != len(md):
                    t = MismatchType.MISSING_RECORD if len(md) == 0 else MismatchType.ADDITIONAL_RECORD
                    res.mismatches.append(MismatchRecord(mismatch_type=t, confirmed=rows_confirmable,
                                                         detail="single-row visual has no row on one side"))
                return res
            res.rows_compared = 1
            row_ok = True
            for c in value_columns:
                ov, mv = od.iloc[0][c], md.iloc[0][c]
                vc = cmp(c, ov, mv)
                if not vc.match:
                    row_ok = False
                    res.mismatches.append(MismatchRecord(
                        mismatch_type=vc.mismatch_type, column=c, original_value=_display(ov), migrated_value=_display(mv),
                        absolute_difference=vc.absolute, percentage_difference=vc.percentage, percentage_note=vc.note,
                        detail="displayed value differs"))
            if row_ok:
                res.rows_matched = 1
                res.matching.append({c: _display(od.iloc[0][c]) for c in value_columns})
            return res
        res.keys_established = False
        res.notes.append("No key/dimension columns identified for a multi-row visual; configure key columns.")
        return res

    # ---- duplicates
    dup_keys: set[tuple] = set()
    for side, df, t in (("original", od, "original"), ("migrated", md, "migrated")):
        counts = df.groupby(key_columns, dropna=False, sort=False).size()
        for k, n in counts[counts > 1].items():
            k = k if isinstance(k, tuple) else (k,)
            dup_keys.add(k)
            res.mismatches.append(MismatchRecord(
                mismatch_type=MismatchType.DUPLICATE_KEY, key=dict(zip(key_columns, k)), confirmed=False,
                detail=f"key occurs {n} times in {side} export; excluded from value comparison"))
    if dup_keys:
        res.notes.append(f"{len(dup_keys)} duplicate key(s) found; those rows were not value-compared.")

    o_idx = {_key_tuple(r, key_columns): r for _, r in od.iterrows()}
    m_idx = {_key_tuple(r, key_columns): r for _, r in md.iterrows()}
    o_keys = [k for k in o_idx if k not in dup_keys]
    m_keys = [k for k in m_idx if k not in dup_keys]
    m_set, o_set = set(m_keys), set(o_keys)

    for k in o_keys:
        orow = o_idx[k]
        key = dict(zip(key_columns, (_display(x) for x in k)))
        if k not in m_set:
            res.mismatches.append(MismatchRecord(
                mismatch_type=MismatchType.MISSING_RECORD, key=key, confirmed=rows_confirmable,
                original_value={c: _display(orow[c]) for c in value_columns},
                detail="record present in original, absent in migrated" + ("" if rows_confirmable else " (export completeness not established)")))
            continue
        mrow = m_idx[k]
        res.rows_compared += 1
        row_ok = True
        for c in value_columns:
            vc = cmp(c, orow[c], mrow[c])
            if not vc.match:
                row_ok = False
                res.mismatches.append(MismatchRecord(
                    mismatch_type=vc.mismatch_type, key=key, column=c, original_value=_display(orow[c]),
                    migrated_value=_display(mrow[c]), absolute_difference=vc.absolute,
                    percentage_difference=vc.percentage, percentage_note=vc.note))
        if row_ok:
            res.rows_matched += 1
            if len(res.matching) < max_matching_records:
                res.matching.append({**key, **{c: _display(orow[c]) for c in value_columns}})
    for k in m_keys:
        if k not in o_set:
            mrow = m_idx[k]
            res.mismatches.append(MismatchRecord(
                mismatch_type=MismatchType.ADDITIONAL_RECORD, key=dict(zip(key_columns, (_display(x) for x in k))),
                confirmed=rows_confirmable, migrated_value={c: _display(mrow[c]) for c in value_columns},
                detail="record present in migrated, absent in original" + ("" if rows_confirmable else " (export completeness not established)")))
    if len(res.matching) >= max_matching_records:
        res.notes.append(f"Matching records list capped at {max_matching_records} for storage.")

    # ---- categories (per key column)
    for c in key_columns:
        ov = {_display(x) for x in od[c].tolist()} - {None}
        mv = {_display(x) for x in md[c].tolist()} - {None}
        if ov - mv:
            res.missing_categories[c] = sorted(map(str, ov - mv))
        if mv - ov:
            res.additional_categories[c] = sorted(map(str, mv - ov))

    # ---- derived totals (evidence only: CSV exports omit total rows)
    for c in value_columns:
        if c not in numeric:
            continue
        ot = _sum(od[c])
        mt = _sum(md[c])
        if ot is None or mt is None:
            continue
        vc = compare_numbers(ot, mt, tolerance)
        res.derived_totals.append({"column": c, "original_total": format(ot, "f"), "migrated_total": format(mt, "f"),
                                   "absolute_difference": format(vc.absolute, "f") if vc.absolute is not None else None,
                                   "percentage_difference": format(vc.percentage, "f") if vc.percentage is not None else None,
                                   "within_tolerance": vc.match,
                                   "note": "derived by summing exported rows (not an exported total)"})
    return res


def _sum(s: pd.Series) -> Decimal | None:
    vals = [v for v in s.tolist() if isinstance(v, Decimal)]
    if any(_is_invalid(v) for v in s.tolist()):
        return None
    return sum(vals, Decimal(0)) if vals else None
