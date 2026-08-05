"""Minimal Streamlit app for follow-up section AppTests."""

from __future__ import annotations

import streamlit as st

from ui_follow_up import render_follow_up_section

st.set_page_config(page_title="Follow-up UI Test", layout="wide")

recommendation_id = st.session_state.get("recommendation_id")
if recommendation_id:
    render_follow_up_section(
        recommendation_id=recommendation_id,
        user_id=st.session_state.get("user_id") or "alex.store",
        session_id=st.session_state.get("session_id") or "sess-ui",
        actor=st.session_state.get("user_id") or "alex.store",
        actor_role=st.session_state.get("actor_role") or "store_manager",
        agent_recommended_quantity=st.session_state.get("agent_recommended_quantity"),
    )
else:
    st.write("No recommendation yet.")
