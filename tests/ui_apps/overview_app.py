"""Minimal Streamlit harness for Replenishment Overview AppTests."""

from __future__ import annotations

import streamlit as st

from styles import inject_styles
from ui_overview import render_replenishment_overview

st.set_page_config(page_title="Overview UI Test", layout="wide")
st.markdown(f"<style>{inject_styles()}</style>", unsafe_allow_html=True)

role = st.session_state.get("actor_role") or "store_manager"
actor = st.session_state.get("user_id") or "alex.store"
display = st.session_state.get("actor_display") or actor

render_replenishment_overview(
    actor=str(actor),
    actor_role=str(role),
    session_id=st.session_state.get("session_id") or "sess-overview-ui",
    display_name=str(display),
)
