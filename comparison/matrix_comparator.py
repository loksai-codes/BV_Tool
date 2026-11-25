"""Matrix / pivot handling.

The exact CSV layout of a summarized matrix export via the JS API is NOT
documented (the service's 'current layout' export is a UI feature). This module
therefore supports both shapes and lets reconciliation decide:

- long/flattened: one row per (row-category, column-category) with value columns -> compare as-is
- wide: column categories spread as columns (e.g. '2023', '2024', 'Q1 2024') -> unpivot to long

Total/subtotal rows (labels such as 'Total', 'Grand Total') are tagged so they are
compared as their own records and reported as subtotals.
"""
from __future__ import annotations

import re

import pandas as pd

from comparison.data_normalizer import DataNormalizer

TOTAL_LABEL = re.compile(r"^\s*(grand\s+)?(sub)?total\s*$", re.IGNORECASE)
COLUMN_CATEGORY_NAME = "__column_category__"
VALUE_NAME = "__value__"


def looks_wide(df: pd.DataFrame, normalizer: DataNormalizer, min_numeric_cols: int = 3) -> bool:
    """Heuristic: >= ``min_numeric_cols`` numeric columns whose *headers* parse as dates/periods."""
    numeric = normalizer.infer_numeric_columns(df)
    date_headers = [c for c in df.columns if normalizer.parse_date(c) is not None]
    nums_with_date_header = [c for c in date_headers if c in numeric or _all_numeric(df[c], normalizer)]
    return len(nums_with_date_header) >= min_numeric_cols


def _all_numeric(s: pd.Series, n: DataNormalizer) -> bool:
    try:
        vals = [x for x in s.tolist() if not n.is_null(x)]
        for x in vals:
            n.parse_number(x)
        return bool(vals)
    except ValueError:
        return False


def unpivot(df: pd.DataFrame, id_columns: list[str], value_columns: list[str]) -> pd.DataFrame:
    long = df.melt(id_vars=id_columns, value_vars=value_columns, var_name=COLUMN_CATEGORY_NAME, value_name=VALUE_NAME)
    return long.reset_index(drop=True)


def split_wide(df: pd.DataFrame, normalizer: DataNormalizer) -> tuple[list[str], list[str]]:
    value_cols = [c for c in df.columns if normalizer.parse_date(c) is not None]
    id_cols = [c for c in df.columns if c not in value_cols]
    return id_cols, value_cols


def total_row_mask(df: pd.DataFrame, key_columns: list[str]) -> pd.Series:
    if not key_columns or df.empty:
        return pd.Series([False] * len(df), index=df.index)
    mask = pd.Series(False, index=df.index)
    for c in key_columns:
        mask |= df[c].astype(str).str.match(TOTAL_LABEL)
    return mask
