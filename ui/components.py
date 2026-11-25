"""Reusable UI components."""
from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

STATUS_ICON = {
    "PASS": "✅", "FAIL": "❌", "PARTIAL": "🟡", "INCONCLUSIVE": "⚠️", "UNSUPPORTED": "⛔", "NOT_MAPPED": "➖",
    "VALIDATED": "✅", "NOT_REQUIRED": "✅", "CONFLICT": "⚠️", "INVALID": "❌", "UNVERIFIED": "⚠️",
    "SUCCESS": "✅", "FAILED": "❌", "POSSIBLY_TRUNCATED": "🟡", "SKIPPED_NON_DATA": "➖", "NOT_ATTEMPTED": "➖",
}
STATUS_HELP = {
    "PASS": "All mandatory data extracted, context & mappings validated, values within tolerance.",
    "FAIL": "Confirmed numeric, category or record mismatches.",
    "INCONCLUSIVE": "Context, extraction completeness, keys or other validation could not be established.",
    "UNSUPPORTED": "Visual or extraction method unsupported.",
    "NOT_MAPPED": "No approved matching visual/page/column mapping.",
    "PARTIAL": "Some records/fields compared, validation incomplete.",
}


def status_text(status: str) -> str:
    """Status shown as icon + label (never colour alone)."""
    return f"{STATUS_ICON.get(status, '•')} {status}"


def status_banner(status: str, reasons: list[str], label: str = "Overall status") -> None:
    body = f"**{label}: {status_text(status)}** — {STATUS_HELP.get(status, '')}"
    if reasons:
        body += "\n\n" + "\n".join(f"- {r}" for r in reasons)
    {"PASS": st.success, "FAIL": st.error}.get(status, st.warning)(body)


def mock_banner(is_mock: bool) -> None:
    if is_mock:
        st.warning("**MOCK DATA** — generated from test fixtures, not from Power BI. Use the Connection page for live reports.",
                   icon="🧪")


def kpis(items: list[tuple[str, Any]], per_row: int = 6) -> None:
    for i in range(0, len(items), per_row):
        cols = st.columns(per_row)
        for col, (label, value) in zip(cols, items[i:i + per_row]):
            col.metric(label, value if value is not None else "—", border=True)


def table(rows: list[dict] | pd.DataFrame, height: int | None = None, key: str | None = None) -> None:
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if df.empty:
        st.caption("No records.")
        return
    kwargs: dict[str, Any] = {"use_container_width": True, "hide_index": True}
    if height:
        kwargs["height"] = height
    if key:
        kwargs["key"] = key
    st.dataframe(df, **kwargs)


def require(condition: bool, message: str, page: str | None = None) -> bool:
    if not condition:
        st.info(message)
        if page:
            st.page_link(page, label="Go there →")
    return condition
