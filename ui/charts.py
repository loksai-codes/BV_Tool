"""Charts (Altair). Status colours come from the reserved status palette and are always
paired with the status label on the axis; single-series charts use one hue, no legend."""
from __future__ import annotations

import altair as alt
import pandas as pd

STATUS_ORDER = ["PASS", "FAIL", "PARTIAL", "INCONCLUSIVE", "UNSUPPORTED", "NOT_MAPPED"]
STATUS_COLOR = {  # good / critical / warning / warning / neutral / neutral
    "PASS": "#0ca30c", "FAIL": "#d03b3b", "PARTIAL": "#fab219", "INCONCLUSIVE": "#fab219",
    "UNSUPPORTED": "#898781", "NOT_MAPPED": "#c3c2b7",
}
SERIES_BLUE = "#2a78d6"


def _axis(**kw):
    return alt.Axis(gridColor="#e1e0d9", domainColor="#c3c2b7", tickColor="#c3c2b7", labelColor="#898781",
                    titleColor="#52514e", **kw)


def status_bar(counts: dict[str, int]) -> alt.Chart:
    df = pd.DataFrame([{"Status": s, "Visuals": counts.get(s, 0)} for s in STATUS_ORDER])
    base = alt.Chart(df).encode(
        y=alt.Y("Status:N", sort=STATUS_ORDER, axis=_axis(title=None, grid=False, labelOverlap=False)),
        x=alt.X("Visuals:Q", axis=_axis(title="Visuals", tickMinStep=1)),
    )
    bars = base.mark_bar(cornerRadiusEnd=4, height={"band": 0.6}).encode(
        color=alt.Color("Status:N", scale=alt.Scale(domain=list(STATUS_COLOR), range=list(STATUS_COLOR.values())),
                        legend=None),
        tooltip=["Status", "Visuals"],
    )
    labels = base.mark_text(align="left", dx=4, color="#52514e").encode(text="Visuals:Q")
    return (bars + labels).properties(height=220)


def differences_bar(rows: list[dict]) -> alt.Chart | None:
    """Total differences per visual (single series)."""
    df = pd.DataFrame(rows)
    if df.empty or df["Differences"].sum() == 0:
        return None
    df = df[df["Differences"] > 0].sort_values("Differences", ascending=False).head(15)
    base = alt.Chart(df).encode(
        y=alt.Y("Visual:N", sort="-x", axis=_axis(title=None, grid=False, labelLimit=260, labelOverlap=False)),
        x=alt.X("Differences:Q", axis=_axis(title="Differences (value + missing + additional)", tickMinStep=1)),
    )
    bars = base.mark_bar(cornerRadiusEnd=4, height={"band": 0.6}, color=SERIES_BLUE).encode(
        tooltip=["Visual", "Value mismatches", "Missing", "Additional", "Differences"])
    labels = base.mark_text(align="left", dx=4, color="#52514e").encode(text="Differences:Q")
    return (bars + labels).properties(height=max(140, 40 * len(df)))
