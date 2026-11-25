"""Page 1 — Home dashboard."""
from __future__ import annotations

import streamlit as st

from ui import components as c
from ui import nav, state


def render() -> None:
    state.init()
    st.title("Power BI Visual Data Comparator")
    st.caption("Read-only reconciliation of **exported visual data** between an original and a migrated Power BI report. "
               "DAX, schemas, relationships and model metadata are out of scope.")
    stats = state.repo().stats()
    last = stats["last_status"]
    c.kpis([
        ("Total comparison runs", stats["total_runs"]),
        ("Last comparison", stats["last_run_at"].strftime("%Y-%m-%d %H:%M") if stats["last_run_at"] else None),
        ("Last result", c.status_text(last) + (" (mock)" if stats["last_is_mock"] else "") if last else None),
        ("Visuals compared (all runs)", stats["total_visuals_compared"]),
        ("Mismatch records (all runs)", stats["total_mismatches"]),
    ], per_row=5)

    a, b, _ = st.columns([1, 1, 2])
    if a.button("Start new comparison", type="primary", use_container_width=True):
        state.reset_comparison()
        st.session_state["mode"] = "live"
        st.switch_page(nav.page("connection"))
    if b.button("Run demo with mock data", use_container_width=True,
                help="Runs the full pipeline on deterministic fixtures. Clearly labelled MOCK everywhere."):
        from services.comparison_service import demo_config, run_demo

        st.session_state["mode"] = "mock"
        st.session_state["config"] = demo_config()
        with st.spinner("Running mock pipeline…"):
            run = run_demo(state.repo(), approve_all_suggestions=True)
        st.session_state.update(run=run, original_ext=run.original, migrated_ext=run.migrated, config=run.config)
        st.switch_page(nav.page("comparison"))

    st.subheader("Recent comparison history")
    runs = state.repo().list_runs(limit=10)
    c.table([{"Run": r["id"], "Name": r["name"], "Status": c.status_text(r["overall_status"]),
              "Data": "MOCK" if r["is_mock"] else "LIVE", "Started (UTC)": r["started_at"],
              "Visuals": r.get("total_visuals"), "Failed": r.get("failed"), "Missing rows": r.get("missing_rows"),
              "Additional rows": r.get("additional_rows")} for r in runs])
