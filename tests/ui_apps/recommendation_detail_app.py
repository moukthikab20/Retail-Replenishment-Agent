"""Minimal Streamlit app for Decision Detail evidence AppTests."""

from __future__ import annotations

import streamlit as st

from services import evidence_service
from styles import inject_styles
from ui_components import page_heading
from ui_evidence import render_decision_detail, render_secondary_explanation

st.set_page_config(page_title="Decision Detail UI Test", layout="wide")
st.markdown(f"<style>{inject_styles()}</style>", unsafe_allow_html=True)

page_heading("Decision Detail", "Persisted evidence story")
rec_id = st.session_state.get("recommendation_id")
if not rec_id:
    st.warning("No recommendation_id in session")
else:
    payload = evidence_service.get_recommendation_evidence(rec_id)
    render_decision_detail(payload)
    render_secondary_explanation(payload.get("explanation") or {})
