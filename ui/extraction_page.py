"""Page 4 — Extraction progress and evidence."""
from __future__ import annotations

import threading
import time

import streamlit as st

from comparison.visual_discovery import inventory
from powerbi import filter_manager as fm
from services.comparison_service import auto_map, compare_and_save, extract_live, extract_mock
from ui import components as c
from ui import nav, state

STAGES = [("report_loading", "Report loading"), ("page_discovery", "Page discovery"), ("visual_discovery", "Visual discovery"),
          ("filter_application", "Filter application"), ("visual_extraction", "Visual data extraction")]


def _run_extraction(mode: str) -> None:
    cfg = state.config()
    events: list[tuple[str, str]] = []
    result: dict = {}

    def progress(stage, msg, data):
        events.append((stage, msg))

    def work():
        try:
            if mode == "mock":
                result["exts"] = extract_mock(cfg, progress=progress)
            else:
                o, m = st.session_state["orig_report"], st.session_state["mig_report"]
                # run outside Streamlit's script thread: Playwright sync API must not share an asyncio loop
                result["exts"] = extract_live(state.settings(), embed_mgr, o, m, cfg, progress=progress)
        except Exception as exc:  # surfaced to the user, never swallowed
            result["error"] = exc

    embed_mgr = state.embed_manager() if mode == "live" else None
    t = threading.Thread(target=work, daemon=True)
    with st.status("Extracting visual data…", expanded=True) as box:
        t.start()
        shown = 0
        while t.is_alive() or shown < len(events):
            while shown < len(events):
                stage, msg = events[shown]
                box.write(f"**{dict(STAGES).get(stage, stage)}** — {msg}")
                shown += 1
            time.sleep(0.2)
        t.join()
        if "error" in result:
            box.update(label="Extraction failed", state="error")
            st.error(f"Extraction failed: {result['error']}")
            return
        box.update(label="Extraction finished", state="complete")
    o, m = result["exts"]
    st.session_state.update(original_ext=o, migrated_ext=m, run=None, progress=events)
    st.session_state["config"] = auto_map(o, m, cfg)


def _evidence(ext) -> None:
    counts = ext.counts()
    c.kpis([("Success", counts["SUCCESS"]), ("Failed", counts["FAILED"]), ("Unsupported", counts["UNSUPPORTED"]),
            ("Possibly truncated", counts["POSSIBLY_TRUNCATED"]), ("Non-data (skipped)", counts["SKIPPED_NON_DATA"]),
            ("Pages", len(ext.pages))])
    if ext.fatal_error:
        st.error(ext.fatal_error)
    ctx = ext.context
    st.markdown(f"**Context:** {c.status_text(ctx.status.value)} · action: `{ctx.action_taken or 'none'}` · "
                f"field `{ctx.target_table}[{ctx.target_column}]` = `{ctx.value}`")
    with st.expander("Context evidence (filters before/after, page filters, slicers)"):
        for msg in ctx.messages:
            st.write("•", msg)
        st.json({"report_filters_before": ctx.report_filters_before, "report_filters_after": ctx.report_filters_after,
                 "page_filters": ctx.page_filters, "slicer_states": ctx.slicer_states,
                 "bookmark_state_captured": ctx.bookmark_state_captured}, expanded=False)
    rows = inventory(ext)
    for r in rows:
        r["status"] = c.status_text(r["status"])
    c.table(rows, height=360)
    with st.expander("Extraction log"):
        st.code("\n".join(ext.log) or "(empty)")


def render() -> None:
    state.init()
    st.title("Extraction")
    mode = st.session_state["mode"]
    cfg = state.config()
    st.markdown(f"**Data source:** {'🧪 MOCK fixtures' if mode == 'mock' else '🔗 Live Power BI (Playwright + Power BI JavaScript SDK)'}")
    problems = fm.config_problems(cfg.country)
    if mode == "live":
        if not state.authenticator().is_signed_in() or not (st.session_state.get("orig_report") and st.session_state.get("mig_report")):
            c.require(False, "Sign in and select both reports first.", nav.page("connection"))
            return
    for p in problems:
        st.error(p)
    if st.button("Run extraction", type="primary", disabled=bool(problems)):
        _run_extraction(mode)

    o, m = st.session_state.get("original_ext"), st.session_state.get("migrated_ext")
    if o is None or m is None:
        return
    c.mock_banner(o.is_mock)
    t1, t2 = st.tabs([f"Original — {o.report_name}", f"Migrated — {m.report_name}"])
    with t1:
        _evidence(o)
    with t2:
        _evidence(m)
    st.divider()
    approved = sum(1 for vm in cfg.visual_mappings if vm.approved)
    pending = sum(1 for vm in cfg.visual_mappings if not vm.approved)
    st.markdown(f"**Mappings:** {approved} approved · {pending} awaiting review")
    a, b = st.columns(2)
    a.page_link(nav.page("configuration"), label="Review mappings →")
    if b.button("Run comparison", type="primary", disabled=approved == 0):
        run = compare_and_save(o, m, cfg, state.repo())
        st.session_state["run"] = run
        st.switch_page(nav.page("comparison"))
