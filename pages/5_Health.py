"""Health page for Render probes and operators."""

from __future__ import annotations

import json

import streamlit as st

from health import check_health
from ui_common import bootstrap_app
from ui_components import page_heading, panel_title, status_pill


bootstrap_app(
    "Health | Retail Replenishment Agent",
    require_auth=False,
    active_nav="health",
)
page_heading("Health", "Application and database status")

payload = check_health()
ok = payload["status"] == "ok"

with st.container(border=True):
    panel_title("Status")
    st.markdown(
        status_pill("ok" if ok else "danger", "Healthy" if ok else "Degraded"),
        unsafe_allow_html=True,
    )
    if ok:
        st.success("Application and database are healthy.")
    else:
        st.error("Service is degraded — database check failed.")

    with st.expander("View technical details", expanded=False):
        st.code(json.dumps(payload, indent=2), language="json")
