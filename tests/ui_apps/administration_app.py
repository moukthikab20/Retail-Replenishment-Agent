"""Minimal Streamlit app for Administration Run-now AppTests."""

from __future__ import annotations

import streamlit as st

from services import scheduler_service
from styles import inject_styles
from ui_components import kpi_row, page_heading, panel_title

st.set_page_config(page_title="Admin UI Test", layout="wide")
st.markdown(f"<style>{inject_styles()}</style>", unsafe_allow_html=True)

status = scheduler_service.get_run_trigger_status()
latest = status.get("latest_run") or {}
page_heading("Administration", "Batch runs")
kpi_row(
    [
        {"label": "Catalog size", "value": status.get("eligible_pair_count", 0)},
        {"label": "Interval", "value": f"{(status.get('schedule') or {}).get('interval_hours', 6)}h"},
        {"label": "Next run", "value": status.get("next_run_display") or "—"},
        {"label": "Latest status", "value": latest.get("status") or status.get("current_status") or "none"},
    ],
    columns=4,
)
panel_title("Replenishment batch")
if st.button("Run now", type="primary", disabled=not status.get("can_start_new_run", True)):
    outcome = scheduler_service.run_now(
        actor="admin.demo",
        actor_role="administrator",
        session_id="sess-admin-ui",
    )
    st.session_state["admin_run_outcome"] = outcome
if "admin_run_outcome" in st.session_state:
    st.write(st.session_state["admin_run_outcome"].get("run"))
