"""Page 2 — Power BI connection (sign-in, workspace & report selection, validation)."""
from __future__ import annotations

import streamlit as st

from authentication.msal_auth import AuthError
from config.settings import AuthMode
from powerbi.http_client import PowerBIApiError
from ui import components as c
from ui import state


def _report_picker(role: str, label: str) -> None:
    st.markdown(f"#### {label}")
    workspaces = st.session_state.get("workspaces") or []
    names = {w.id: w.name for w in workspaces}
    ws_id = st.selectbox(f"{label} workspace", options=[w.id for w in workspaces], format_func=lambda i: names[i],
                         key=f"{role}_ws", index=None, placeholder="Select a workspace")
    if not ws_id:
        return
    cache_key = f"reports_{ws_id}"
    if cache_key not in st.session_state:
        try:
            st.session_state[cache_key] = state.report_client().list_reports(ws_id)
        except (PowerBIApiError, AuthError) as exc:
            st.error(str(exc))
            return
    reports = st.session_state[cache_key]
    if not reports:
        st.warning("No Power BI reports visible in this workspace.")
        return
    rnames = {r.id: r.name for r in reports}
    rid = st.selectbox(f"{label} report", options=list(rnames), format_func=lambda i: rnames[i], key=f"{role}_rpt",
                       index=None, placeholder="Select a report")
    if rid:
        st.session_state["orig_report" if role == "original" else "mig_report"] = next(r for r in reports if r.id == rid)


def render() -> None:
    state.init()
    st.title("Power BI connection")
    s = state.settings()
    auth = state.authenticator()
    problems = auth.validate_configuration()

    st.markdown(f"**Authentication mode:** `{s.auth_mode.value}` · **Tenant:** `{s.tenant_id or 'organizations'}`")
    if problems:
        st.error("Configuration incomplete: " + " ".join(problems) + " Copy `.env.example` to `.env` and fill in your Entra app registration.")
        st.info("You can still explore the application with **mock data** from the Home page.")
        return

    col1, col2 = st.columns([1, 3])
    if auth.is_signed_in():
        tok = auth.tokens.get()
        col1.success(f"Signed in{(' as ' + tok.account) if tok and tok.account else ''}")
        if col2.button("Sign out"):
            auth.sign_out()
            for k in list(st.session_state.keys()):
                if k.startswith("reports_") or k in ("workspaces", "orig_report", "mig_report"):
                    del st.session_state[k]
            st.rerun()
    else:
        if col1.button("Sign in with Microsoft", type="primary"):
            try:
                if s.auth_mode == AuthMode.DEVICE_CODE:
                    box = st.empty()
                    auth.acquire_token(device_code_callback=lambda m: box.info(m))
                else:
                    with st.spinner("Complete sign-in in the browser window…"):
                        auth.acquire_token()
                st.rerun()
            except AuthError as exc:
                st.error(f"Sign-in failed: {exc}")
        return

    st.session_state["mode"] = "live"
    if st.button("Load / refresh workspaces") or "workspaces" not in st.session_state:
        try:
            st.session_state["workspaces"] = state.workspace_client().list_workspaces()
        except (PowerBIApiError, AuthError) as exc:
            st.error(str(exc))
            return
    left, right = st.columns(2)
    with left:
        _report_picker("original", "Original")
    with right:
        _report_picker("migrated", "Migrated")

    o, m = st.session_state.get("orig_report"), st.session_state.get("mig_report")
    if o and m:
        st.divider()
        if o.id == m.id:
            st.warning("Original and migrated reports are the same report.")
        if st.button("Validate both connections", type="primary"):
            rc = state.report_client()
            for role, r in (("Original", o), ("Migrated", m)):
                v = rc.validate_access(r.workspace_id, r.id)
                if v.ok:
                    st.success(f"{role}: '{v.report.name}' accessible · {len(v.pages)} page(s) · dataset {v.report.dataset_id or '—'}")
                else:
                    st.error(f"{role}: " + " ".join(v.problems))
                for w in v.warnings:
                    st.warning(f"{role}: {w}")
                st.session_state[f"{role.lower()}_validation"] = v
        st.markdown("##### Selected reports")
        c.table([{"Role": role, "Report": r.name, "Report ID": r.id, "Workspace ID": r.workspace_id,
                  "Dataset (semantic model) ID": r.dataset_id or "—", "Type": r.report_type, "Format": r.format}
                 for role, r in (("Original", o), ("Migrated", m))])
