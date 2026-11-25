"""Streamlit entry point:  streamlit run app.py"""
from __future__ import annotations

import streamlit as st

from ui import nav, state

st.set_page_config(page_title="Power BI Visual Data Comparator", page_icon="📊", layout="wide")

nav.PAGES.update({
    "home": st.Page("views/home.py", title="Home", icon="🏠", url_path="home", default=True),
    "connection": st.Page("views/connection_page.py", title="Power BI connection", icon="🔐", url_path="connection"),
    "configuration": st.Page("views/configuration_page.py", title="Configuration", icon="⚙️", url_path="configuration"),
    "extraction": st.Page("views/extraction_page.py", title="Extraction", icon="⏬", url_path="extraction"),
    "comparison": st.Page("views/comparison_page.py", title="Comparison dashboard", icon="📊", url_path="comparison"),
    "details": st.Page("views/details_page.py", title="Visual details", icon="🔎", url_path="details"),
    "history": st.Page("views/history_page.py", title="Export & history", icon="🗂️", url_path="history"),
})

state.init()
with st.sidebar:
    mode = st.session_state["mode"]
    st.markdown(f"**Data source:** {'🧪 MOCK' if mode == 'mock' else '🔗 LIVE'}")
    st.caption("Read-only: reports, semantic models and data are never modified.")

st.navigation(list(nav.PAGES.values())).run()
