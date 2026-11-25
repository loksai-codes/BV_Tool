"""Page 6 — Visual comparison details & evidence."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.contracts import MismatchType
from reporting.common import _j
from ui import components as c
from ui import nav, state


def _mm_rows(r, types):
    return [{"Type": m.mismatch_type.value, "Confirmed": m.confirmed, **{f"key:{k}": v for k, v in m.key.items()},
             "Column": m.column, "Original": _j(m.original_value), "Migrated": _j(m.migrated_value),
             "Absolute diff": None if m.absolute_difference is None else format(m.absolute_difference, "f"),
             "% diff": None if m.percentage_difference is None else format(m.percentage_difference, "f"),
             "Note": m.percentage_note or m.detail} for m in r.mismatches if m.mismatch_type in types]


def render() -> None:
    state.init()
    st.title("Visual comparison details")
    run = st.session_state.get("run")
    if not c.require(run is not None, "No comparison loaded.", nav.page("history")):
        return
    c.mock_banner(run.is_mock)

    f1, f2, f3, f4 = st.columns(4)
    statuses = f1.multiselect("Status", sorted({r.status.value for r in run.visual_results}))
    pages = f2.multiselect("Original page", sorted({r.original_page_display for r in run.visual_results if r.original_page_display}))
    mtypes = f3.multiselect("Has mismatch type", [t.value for t in MismatchType])
    text = f4.text_input("Visual title contains")
    results = [r for r in run.visual_results
               if (not statuses or r.status.value in statuses)
               and (not pages or r.original_page_display in pages)
               and (not mtypes or any(m.mismatch_type.value in mtypes for m in r.mismatches))
               and (not text or text.lower() in f"{r.original_title} {r.migrated_title}".lower())]
    if not results:
        st.info("No visuals match the filters.")
        return
    labels = [f"{c.status_text(r.status.value)} · {r.original_title or r.original_visual or '—'} ⇄ {r.migrated_title or r.migrated_visual or '—'}"
              for r in results]
    idx = st.selectbox("Visual", range(len(results)), format_func=lambda i: labels[i])
    r = results[idx]

    a, b = st.columns(2)
    a.markdown(f"**Original:** {r.original_page_display or '—'} › {r.original_title or r.original_visual or '—'}")
    b.markdown(f"**Migrated:** {r.migrated_page_display or '—'} › {r.migrated_title or r.migrated_visual or '—'}")
    c.status_banner(r.status.value, r.reasons, label="Visual status")
    for n in r.notes:
        st.caption(f"ℹ️ {n}")
    c.kpis([("Rows original", r.rows_original), ("Rows migrated", r.rows_migrated), ("Compared", r.rows_compared),
            ("Matched", r.rows_matched), ("Missing", r.missing_rows), ("Additional", r.additional_rows)])

    ov = run.original.find(r.original_page, r.original_visual) if r.original_visual else None
    mv = run.migrated.find(r.migrated_page, r.migrated_visual) if r.migrated_visual else None
    tabs = st.tabs(["Mismatches", "Missing", "Additional", "Matching", "Original (raw)", "Migrated (raw)",
                    "Normalized", "Totals & categories", "Evidence"])
    with tabs[0]:
        c.table(_mm_rows(r, {MismatchType.VALUE_MISMATCH, MismatchType.NULL_MISMATCH, MismatchType.DUPLICATE_KEY,
                             MismatchType.CONTEXT_VIOLATION}))
    with tabs[1]:
        c.table(_mm_rows(r, {MismatchType.MISSING_RECORD}))
    with tabs[2]:
        c.table(_mm_rows(r, {MismatchType.ADDITIONAL_RECORD}))
    with tabs[3]:
        c.table(r.matching_records)
    with tabs[4]:
        if ov is not None and ov.has_data:
            st.caption(f"Unmodified export · SHA-256 {ov.raw_sha256} · integrity {'OK' if ov.integrity_ok() else 'FAILED'}")
            c.table(ov.dataframe())
        else:
            st.caption("No original data.")
    with tabs[5]:
        if mv is not None and mv.has_data:
            st.caption(f"Unmodified export · SHA-256 {mv.raw_sha256} · integrity {'OK' if mv.integrity_ok() else 'FAILED'}")
            c.table(mv.dataframe())
        else:
            st.caption("No migrated data.")
    with tabs[6]:
        st.markdown("**Rules applied:** " + "; ".join(r.normalization_applied) if r.normalization_applied else "No normalization (not compared).")
        if r.column_mappings_used:
            st.markdown("**Column mappings used**")
            c.table(r.column_mappings_used)
        x, y = st.columns(2)
        with x:
            st.caption("Original (normalized)")
            c.table(r.normalized_original)
        with y:
            st.caption("Migrated (normalized, renamed to original columns)")
            c.table(r.normalized_migrated)
    with tabs[7]:
        st.caption("Totals are derived by summing exported rows; CSV exports do not contain total rows.")
        c.table(r.derived_totals)
        st.write("Missing categories:", r.missing_categories or "none")
        st.write("Additional categories:", r.additional_categories or "none")
    with tabs[8]:
        for side, v in (("Original", ov), ("Migrated", mv)):
            if v is None:
                continue
            st.markdown(f"**{side}** · `{v.visual_type}` · id `{v.visual_name}` · {c.status_text(v.status.value)} · "
                        f"{v.completeness.value} · source {v.source_method.value} · {v.extracted_at:%Y-%m-%d %H:%M:%S} UTC")
            st.json({"rows": v.row_count, "rows_requested": v.rows_requested, "error_code": v.error_code,
                     "error_message": v.error_message, "truncation_info": v.truncation_info,
                     "visual_filters": v.visual_filters, "screenshot": v.screenshot_path}, expanded=False)
        st.json({"mapping_confidence": r.mapping_confidence, "mapping_provenance": r.mapping_provenance,
                 "key_columns": r.key_columns, "value_columns": r.value_columns, "unmapped_columns": r.unmapped_columns},
                expanded=False)
    if st.toggle("Show all mismatch records for this run"):
        c.table(pd.DataFrame([{"Visual": x.original_title or x.migrated_title, **row} for x in run.visual_results
                              for row in _mm_rows(x, set(MismatchType))]))
