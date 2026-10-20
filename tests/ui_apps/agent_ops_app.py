"""Minimal Streamlit harness for Agent Operations AppTests."""

from __future__ import annotations

import streamlit as st

from styles import inject_styles
from ui_agent_ops import render_agent_operations

st.set_page_config(page_title="Agent Ops UI Test", layout="wide")
st.markdown(f"<style>{inject_styles()}</style>", unsafe_allow_html=True)

role = st.session_state.get("test_role", "administrator")
render_agent_operations(actor_role=role)
