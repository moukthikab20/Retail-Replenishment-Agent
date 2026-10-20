"""Minimal Streamlit app for Today's Queue AppTests."""

from __future__ import annotations

import streamlit as st

from styles import inject_styles
from ui_queue import render_todays_queue

st.set_page_config(page_title="Queue UI Test", layout="wide")
st.markdown(f"<style>{inject_styles()}</style>", unsafe_allow_html=True)


def _open_detail(rec_id: str) -> None:
    st.session_state["nav_recommendation_id"] = rec_id
    st.session_state["recommendation_id"] = rec_id


render_todays_queue(
    show_heading=True,
    on_open_detail=_open_detail,
    actor="alex.store",
    actor_role="store_manager",
    session_id="sess-queue-ui",
)
