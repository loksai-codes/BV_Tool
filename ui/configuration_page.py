"""Page 3 — Comparison configuration (context, tolerances, normalization, mappings)."""
from __future__ import annotations

from decimal import Decimal

import pandas as pd
import streamlit as st

from comparison.reconciliation import column_mappings_for
from comparison.visual_discovery import label
from core.contracts import ColumnMapping, ExtractionMode, ExtractionStatus, ToleranceConfig, VisualMapping
from services.comparison_service import apply_profile, auto_map
from ui import components as c
from ui import nav, state

NONE = "— not mapped —"


def _settings_tab() -> None:
    cfg = state.config()
    with st.form("cfg"):
        st.markdown("##### Country context")
        a, b, v = st.columns([2, 2, 1])
        cfg.country.original_table = a.text_input("Original country table", cfg.country.original_table)
        cfg.country.original_column = a.text_input("Original country column", cfg.country.original_column)
        cfg.country.original_export_column = a.text_input("Original export header (optional)", cfg.country.original_export_column or "") or None
        cfg.country.migrated_table = b.text_input("Migrated country table", cfg.country.migrated_table)
        cfg.country.migrated_column = b.text_input("Migrated country column", cfg.country.migrated_column)
        cfg.country.migrated_export_column = b.text_input("Migrated export header (optional)", cfg.country.migrated_export_column or "") or None
        cfg.country.value = v.text_input("Country value", cfg.country.value)
        cfg.country.apply_to_migrated = v.checkbox("Also apply to migrated", cfg.country.apply_to_migrated,
                                                   help="Migrated report is China-only by design; filters are always captured.")
        cfg.country.allow_replace_conflicting = v.checkbox("Allow replacing a conflicting country filter",
                                                           cfg.country.allow_replace_conflicting,
                                                           help="Off: a conflicting existing filter makes the context INCONCLUSIVE.")
        cfg.require_context_validation = st.checkbox("Require validated context (recommended)", cfg.require_context_validation)

        st.markdown("##### Extraction & tolerance")
        e1, e2, e3, e4 = st.columns(4)
        cfg.extraction_mode = ExtractionMode(e1.selectbox("Extraction mode", [m.value for m in ExtractionMode],
                                                           index=[m.value for m in ExtractionMode].index(cfg.extraction_mode.value),
                                                           help="Summarized is default; Underlying needs Build permission and is often restricted."))
        abs_tol = e2.number_input("Absolute tolerance", min_value=0.0, value=float(cfg.tolerance.absolute), format="%.6f")
        pct_tol = e3.number_input("Percentage tolerance (%)", min_value=0.0, value=float(cfg.tolerance.percentage), format="%.4f")
        cfg.auto_approve_threshold = e4.slider("Auto-approve mapping ≥", 0.5, 1.0, cfg.auto_approve_threshold, 0.01)
        cfg.tolerance = ToleranceConfig(absolute=Decimal(str(abs_tol)), percentage=Decimal(str(pct_tol)))

        st.markdown("##### Normalization (applied to derived copies only)")
        n = cfg.normalization
        n1, n2, n3, n4 = st.columns(4)
        dp = n1.number_input("Decimal places (blank = none)", min_value=-1, max_value=10,
                             value=n.decimal_places if n.decimal_places is not None else -1,
                             help="-1 disables rounding.")
        n.decimal_places = None if dp < 0 else int(dp)
        n.text_case = n2.selectbox("Text case", ["preserve", "lower", "upper"], index=["preserve", "lower", "upper"].index(n.text_case))
        n.percent_mode = n3.selectbox("Percent values", ["as_number", "as_fraction"], index=["as_number", "as_fraction"].index(n.percent_mode))
        n.decimal_separator = n4.selectbox("Decimal separator", [".", ","], index=[".", ","].index(n.decimal_separator))
        n.thousands_separator = n4.selectbox("Thousands separator", [",", ".", " ", ""], index=[",", ".", " ", ""].index(n.thousands_separator))
        n.trim_whitespace = n1.checkbox("Trim whitespace", n.trim_whitespace)
        n.treat_null_as_zero = n2.checkbox("Treat blanks as zero", n.treat_null_as_zero,
                                           help="Off by default: a blank vs a number is reported as a NULL mismatch.")
        n.date_dayfirst = n3.checkbox("Dates are day-first", n.date_dayfirst)
        n.auto_detect_dates = n3.checkbox("Auto-detect date columns", n.auto_detect_dates)
        tokens = st.text_input("Null/blank tokens (comma separated)", ", ".join(n.null_tokens))
        n.null_tokens = [t.strip() for t in tokens.split(",")] + ([""] if "" not in tokens.split(",") else [])
        if st.form_submit_button("Save configuration", type="primary"):
            st.success("Configuration saved for this session.")


def _mapping_tab() -> None:
    o, m = st.session_state.get("original_ext"), st.session_state.get("migrated_ext")
    if not c.require(o is not None and m is not None, "Run extraction first — visual discovery needs the extracted visuals.",
                     nav.page("extraction")):
        return
    cfg = state.config()
    c.mock_banner(o.is_mock)
    b1, b2, b3 = st.columns(3)
    if b1.button("Re-run automatic matching"):
        st.session_state["config"] = cfg = auto_map(o, m, cfg)
    profiles = state.repo().load_mapping_profiles(o.report_id, m.report_id)
    if profiles:
        names = {p["name"]: p for p in profiles}
        pick = b2.selectbox("Saved mapping profiles", list(names), index=None, placeholder="Apply a saved profile")
        if pick and b2.button("Apply profile"):
            st.session_state["config"] = cfg = apply_profile(cfg, names[pick])
            st.rerun()

    o_vis = [v for v in o.visuals if v.status != ExtractionStatus.SKIPPED_NON_DATA]
    m_vis = [v for v in m.visuals if v.status != ExtractionStatus.SKIPPED_NON_DATA]
    m_labels = {label(m, v.page_name, v.visual_name): (v.page_name, v.visual_name) for v in m_vis}
    current = {(vm.original_page, vm.original_visual): vm for vm in cfg.visual_mappings}
    rows = []
    for v in o_vis:
        vm = current.get((v.page_name, v.visual_name))
        rows.append({
            "Approve": bool(vm and vm.approved), "Mandatory": vm.mandatory if vm else True,
            "Original visual": label(o, v.page_name, v.visual_name),
            "Migrated visual": label(m, vm.migrated_page, vm.migrated_visual) if vm else NONE,
            "Confidence": round(vm.confidence, 3) if vm else None,
            "Provenance": vm.provenance if vm else "", "Why": vm.explanation if vm else "No candidate above minimum score.",
        })
    st.markdown("##### Visual mapping review")
    st.caption("Low-confidence or ambiguous suggestions are never auto-approved. Unapproved visuals are reported NOT MAPPED.")
    edited = st.data_editor(pd.DataFrame(rows), hide_index=True, use_container_width=True, key="map_editor",
                            column_config={
                                "Migrated visual": st.column_config.SelectboxColumn(options=[NONE] + list(m_labels)),
                                "Original visual": st.column_config.TextColumn(disabled=True),
                                "Confidence": st.column_config.NumberColumn(disabled=True),
                                "Provenance": st.column_config.TextColumn(disabled=True),
                                "Why": st.column_config.TextColumn(disabled=True, width="large"),
                            })
    if st.button("Save mapping review", type="primary"):
        new: list[VisualMapping] = []
        for v, (_, row) in zip(o_vis, edited.iterrows()):
            if row["Migrated visual"] == NONE:
                continue
            mp, mv = m_labels[row["Migrated visual"]]
            old = current.get((v.page_name, v.visual_name))
            changed = not old or (old.migrated_page, old.migrated_visual) != (mp, mv)
            new.append(VisualMapping(
                original_page=v.page_name, original_visual=v.visual_name, migrated_page=mp, migrated_visual=mv,
                confidence=1.0 if changed else old.confidence, provenance="manual" if changed or row["Approve"] != (old and old.approved) else old.provenance,
                approved=bool(row["Approve"]), mandatory=bool(row["Mandatory"]),
                signals={} if changed else old.signals, explanation="user mapping" if changed else old.explanation,
                column_mappings=[] if changed else old.column_mappings, key_columns=[] if changed else old.key_columns,
                tolerance=None if changed else old.tolerance,
            ))
        cfg.visual_mappings = new
        st.success(f"Saved {sum(1 for x in new if x.approved)} approved mapping(s).")
    pname = b3.text_input("Profile name", "default")
    if b3.button("Save approved mappings as profile"):
        state.repo().save_mapping_profile(pname, o.report_id, m.report_id, cfg.page_mappings, cfg.visual_mappings)
        st.success("Profile saved for reuse.")

    st.markdown("##### Column mapping & keys (per visual)")
    approved = [vm for vm in cfg.visual_mappings if vm.approved]
    if not approved:
        st.caption("Approve at least one visual mapping first.")
        return
    labels = {label(o, vm.original_page, vm.original_visual): vm for vm in approved}
    sel = st.selectbox("Visual", list(labels))
    vm = labels[sel]
    ov, mv = o.find(vm.original_page, vm.original_visual), m.find(vm.migrated_page, vm.migrated_visual)
    if not (ov and mv and ov.has_data and mv.has_data):
        st.info("Column mapping needs data on both sides (one side failed or is unsupported).")
        return
    cms = vm.column_mappings or column_mappings_for(ov, mv, cfg.normalization)
    m_cols = list(mv.dataframe().columns)
    o_cols = list(ov.dataframe().columns)
    cur = {cm.original: cm for cm in cms}
    df = pd.DataFrame([{"Original column": oc, "Migrated column": cur[oc].migrated if oc in cur else NONE,
                        "Role": cur[oc].role if oc in cur else "auto",
                        "Confidence": cur[oc].confidence if oc in cur else None,
                        "Provenance": cur[oc].provenance if oc in cur else ""} for oc in o_cols])
    ed = st.data_editor(df, hide_index=True, use_container_width=True, key=f"cols_{sel}", column_config={
        "Original column": st.column_config.TextColumn(disabled=True),
        "Migrated column": st.column_config.SelectboxColumn(options=[NONE] + m_cols),
        "Role": st.column_config.SelectboxColumn(options=["auto", "key", "value"]),
        "Confidence": st.column_config.NumberColumn(disabled=True), "Provenance": st.column_config.TextColumn(disabled=True)})
    keys = st.multiselect("Key columns (business keys / dimensions; row order is never used)", o_cols, default=vm.key_columns)
    t1, t2 = st.columns(2)
    vt_abs = t1.number_input("Per-visual absolute tolerance (blank = global)", min_value=0.0, value=float(vm.tolerance.absolute) if vm.tolerance else 0.0)
    vt_pct = t2.number_input("Per-visual percentage tolerance", min_value=0.0, value=float(vm.tolerance.percentage) if vm.tolerance else 0.0)
    use_vt = st.checkbox("Use per-visual tolerance", value=vm.tolerance is not None)
    if st.button("Approve column mapping for this visual"):
        vm.column_mappings = [ColumnMapping(original=r["Original column"], migrated=r["Migrated column"], role=r["Role"],
                                            provenance="manual") for _, r in ed.iterrows() if r["Migrated column"] != NONE]
        vm.key_columns = keys
        vm.tolerance = ToleranceConfig(absolute=Decimal(str(vt_abs)), percentage=Decimal(str(vt_pct))) if use_vt else None
        st.success("Column mapping approved.")


def render() -> None:
    state.init()
    st.title("Comparison configuration")
    t1, t2 = st.tabs(["Context, tolerance & normalization", "Visual & column mapping"])
    with t1:
        _settings_tab()
    with t2:
        _mapping_tab()
