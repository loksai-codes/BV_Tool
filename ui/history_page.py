"""Page 7 — Export & history."""
from __future__ import annotations

import streamlit as st

from core.security import safe_filename
from reporting.csv_export import build_zip
from reporting.excel_export import build_workbook
from reporting.html_report import build_html
from reporting.json_export import build_json
from services.comparison_service import compare_and_save, extract_mock
from ui import components as c
from ui import nav, state


def _downloads(run) -> None:
    base = safe_filename(f"comparison_{run.run_id or 'current'}_{run.overall_status.value}{'_MOCK' if run.is_mock else ''}")
    a, b, d, e = st.columns(4)
    a.download_button("Download Excel", build_workbook(run), f"{base}.xlsx",
                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    b.download_button("Download CSV (zip)", build_zip(run), f"{base}_csv.zip", "application/zip", use_container_width=True)
    d.download_button("Download JSON evidence", build_json(run).encode("utf-8"), f"{base}.json", "application/json",
                      use_container_width=True)
    e.download_button("Download HTML report", build_html(run).encode("utf-8"), f"{base}.html", "text/html",
                      use_container_width=True)


def render() -> None:
    state.init()
    st.title("Export & history")
    run = st.session_state.get("run")
    if run is not None:
        st.subheader(f"Current comparison — {c.status_text(run.overall_status.value)}")
        c.mock_banner(run.is_mock)
        _downloads(run)

    st.subheader("Previous runs")
    repo = state.repo()
    runs = repo.list_runs(limit=200)
    if not runs:
        st.caption("No runs yet.")
        return
    c.table([{"Run": r["id"], "Name": r["name"], "Status": c.status_text(r["overall_status"]),
              "Data": "MOCK" if r["is_mock"] else "LIVE", "Started (UTC)": r["started_at"], "Visuals": r.get("total_visuals"),
              "Passed": r.get("passed"), "Failed": r.get("failed"), "Partial": r.get("partial"),
              "Missing rows": r.get("missing_rows"), "Additional rows": r.get("additional_rows"),
              "Numeric mismatches": r.get("numeric_mismatches")} for r in runs], height=300)
    ids = [r["id"] for r in runs]
    sel = st.selectbox("Select a run", ids, format_func=lambda i: f"Run {i}")
    a, b, d = st.columns(3)
    if a.button("Open run", use_container_width=True):
        loaded = repo.load_run(sel)
        st.session_state.update(run=loaded, original_ext=loaded.original, migrated_ext=loaded.migrated, config=loaded.config,
                                mode="mock" if loaded.is_mock else "live")
        st.switch_page(nav.page("comparison"))
    if b.button("Rerun this configuration", use_container_width=True,
                help="Mock runs re-execute immediately. Live runs load the configuration; re-extract on the Extraction page."):
        loaded = repo.load_run(sel)
        if loaded.is_mock:
            o, m = extract_mock(loaded.config)
            new = compare_and_save(o, m, loaded.config, repo)
            st.session_state.update(run=new, original_ext=o, migrated_ext=m, config=loaded.config, mode="mock")
            st.switch_page(nav.page("comparison"))
        else:
            st.session_state.update(config=loaded.config, mode="live", run=None, original_ext=None, migrated_ext=None)
            st.info("Configuration loaded. Select the same reports on the Connection page, then run extraction.")
    if d.button("Delete run", use_container_width=True):
        repo.delete_run(sel)
        st.rerun()

    st.subheader("Compare historical results")
    x, y = st.columns(2)
    r1 = x.selectbox("Baseline run", ids, index=min(1, len(ids) - 1), key="h1")
    r2 = y.selectbox("Later run", ids, index=0, key="h2")
    if st.button("Compare runs") and r1 != r2:
        a_run, b_run = repo.load_run(r1), repo.load_run(r2)
        key = lambda r: (r.original_title or r.original_visual, r.migrated_title or r.migrated_visual)  # noqa: E731
        sa = {key(r): r for r in a_run.visual_results}
        sb = {key(r): r for r in b_run.visual_results}
        rows = []
        for k in sorted(set(sa) | set(sb), key=str):
            ra, rb = sa.get(k), sb.get(k)
            rows.append({"Original": k[0], "Migrated": k[1],
                         f"Run {r1}": ra.status.value if ra else "—", f"Run {r2}": rb.status.value if rb else "—",
                         "Changed": (ra.status if ra else None) != (rb.status if rb else None),
                         f"Diffs run {r1}": (ra.numeric_mismatches + ra.missing_rows + ra.additional_rows) if ra else None,
                         f"Diffs run {r2}": (rb.numeric_mismatches + rb.missing_rows + rb.additional_rows) if rb else None})
        st.markdown(f"Overall: **{a_run.overall_status.value}** → **{b_run.overall_status.value}**")
        c.table(rows)

    st.subheader("Retention")
    days = st.number_input("Delete runs older than (days)", min_value=1, value=state.settings().data_retention_days)
    if st.button("Apply retention now"):
        st.success(f"Removed {repo.purge_older_than(int(days))} run(s).")
