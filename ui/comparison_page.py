"""Page 5 — Comparison dashboard."""
from __future__ import annotations

import streamlit as st

from ui import charts
from ui import components as c
from ui import nav, state


def render() -> None:
    state.init()
    st.title("Comparison dashboard")
    run = st.session_state.get("run")
    if not c.require(run is not None, "No comparison yet. Run an extraction and comparison, or load a run from History.",
                     nav.page("extraction")):
        return
    c.mock_banner(run.is_mock)
    c.status_banner(run.overall_status.value, run.overall_reasons)
    s = run.summary()
    c.kpis([
        ("Total visuals", s["total_visuals"]), ("Matched visuals", s["matched_visuals"]), ("Passed", s["passed"]),
        ("Failed", s["failed"]), ("Partial", s["partial"]), ("Inconclusive", s["inconclusive"]),
        ("Unsupported", s["unsupported"]), ("Not mapped", s["not_mapped"]), ("Rows compared", s["rows_compared"]),
        ("Missing rows", s["missing_rows"]), ("Additional rows", s["additional_rows"]), ("Numeric mismatches", s["numeric_mismatches"]),
    ])
    left, right = st.columns(2)
    with left:
        st.markdown("##### Visuals by status")
        st.altair_chart(charts.status_bar({r: sum(1 for x in run.visual_results if x.status.value == r) for r in charts.STATUS_ORDER}),
                        use_container_width=True)
    diff_rows = [{"Visual": f"{r.original_title or r.migrated_title}", "Value mismatches": r.numeric_mismatches,
                  "Missing": r.missing_rows, "Additional": r.additional_rows,
                  "Differences": r.numeric_mismatches + r.missing_rows + r.additional_rows} for r in run.visual_results]
    with right:
        st.markdown("##### Differences by visual")
        ch = charts.differences_bar(diff_rows)
        if ch is None:
            st.caption("No differences recorded.")
        else:
            st.altair_chart(ch, use_container_width=True)

    st.markdown("##### Visual results")
    c.table([{"Status": c.status_text(r.status.value), "Mandatory": r.mandatory,
              "Original": f"{r.original_page_display or ''} › {r.original_title or r.original_visual or '—'}",
              "Migrated": f"{r.migrated_page_display or ''} › {r.migrated_title or r.migrated_visual or '—'}",
              "Type": r.visual_type, "Compared": r.rows_compared, "Missing": r.missing_rows, "Additional": r.additional_rows,
              "Value mismatches": r.numeric_mismatches, "Mapping": f"{r.mapping_provenance or ''} {r.mapping_confidence or ''}".strip(),
              "Reason": "; ".join(r.reasons)} for r in run.visual_results], height=420)
    st.page_link(nav.page("details"), label="Open visual details →")
