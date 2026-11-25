"""Column mapping between original and migrated exports.

Suggestions use column names and data (value overlap / kind); they are labelled
``provenance='auto'`` with a confidence and must be reviewed. User mappings are
``provenance='manual'`` and always win. No field names are hardcoded in logic;
the optional synonym hints are configurable data.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

import pandas as pd

from comparison.data_normalizer import DataNormalizer
from core.contracts import ColumnMapping

DEFAULT_SYNONYM_HINTS: list[set[str]] = [
    {"sales", "revenue", "salesamount", "amount", "totalsales", "totalrevenue", "netsales"},
    {"month", "period", "monthname", "date", "monthyear", "yearmonth"},
    {"country", "countryname", "nation", "market"},
    {"category", "productcategory", "segment", "group"},
    {"quantity", "units", "qty", "unitssold"},
]


def _canon(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def name_similarity(a: str, b: str, synonyms: list[set[str]] | None = None) -> float:
    ca, cb = _canon(a), _canon(b)
    if ca == cb:
        return 1.0
    for group in synonyms if synonyms is not None else DEFAULT_SYNONYM_HINTS:
        if ca in group and cb in group:
            return 0.8
    return SequenceMatcher(None, ca, cb).ratio() * 0.75


def value_overlap(a: pd.Series, b: pd.Series, normalizer: DataNormalizer) -> float | None:
    sa = {normalizer.normalize_text(x) for x in a.tolist()} - {None}
    sb = {normalizer.normalize_text(x) for x in b.tolist()} - {None}
    if not sa or not sb:
        return None
    return len(sa & sb) / len(sa | sb)


def suggest_column_mappings(
    orig: pd.DataFrame,
    mig: pd.DataFrame,
    normalizer: DataNormalizer | None = None,
    synonyms: list[set[str]] | None = None,
    min_confidence: float = 0.45,
) -> list[ColumnMapping]:
    normalizer = normalizer or DataNormalizer()
    o_num = set(normalizer.infer_numeric_columns(orig))
    m_num = set(normalizer.infer_numeric_columns(mig))
    o_cols, m_cols = list(orig.columns), list(mig.columns)
    scored: list[tuple[float, str, str]] = []
    for i, oc in enumerate(o_cols):
        for j, mc in enumerate(m_cols):
            if (oc in o_num) != (mc in m_num):
                continue  # kinds must agree (numeric vs dimension)
            score = name_similarity(oc, mc, synonyms)
            if oc not in o_num:
                ov = value_overlap(orig[oc], mig[mc], normalizer)
                if ov is not None:
                    score = max(score, 0.5 + 0.5 * ov if ov >= 0.3 else score)
            if score < 1.0 and i == j and len(o_cols) == len(m_cols):
                score = max(score, 0.5)  # same position and kind, weak structural hint
            scored.append((score, oc, mc))
    scored.sort(key=lambda t: -t[0])
    used_o, used_m, out = set(), set(), []
    for score, oc, mc in scored:
        if score < min_confidence or oc in used_o or mc in used_m:
            continue
        used_o.add(oc)
        used_m.add(mc)
        out.append(ColumnMapping(original=oc, migrated=mc, role="value" if oc in o_num else "key",
                                 provenance="auto", confidence=round(score, 3)))
    order = {c: i for i, c in enumerate(o_cols)}
    return sorted(out, key=lambda m: order[m.original])


def apply_column_mappings(
    orig: pd.DataFrame, mig: pd.DataFrame, mappings: list[ColumnMapping]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, list[str]]]:
    """Return derived frames restricted to mapped columns, migrated renamed to original names."""
    o_cols = [m.original for m in mappings if m.original in orig.columns and m.migrated in mig.columns]
    rename = {m.migrated: m.original for m in mappings if m.original in orig.columns and m.migrated in mig.columns}
    o = orig[o_cols].copy()
    m = mig[list(rename.keys())].rename(columns=rename).copy()[o_cols]
    unmapped = {
        "original": [c for c in orig.columns if c not in o_cols],
        "migrated": [c for c in mig.columns if c not in rename],
    }
    return o, m, unmapped
