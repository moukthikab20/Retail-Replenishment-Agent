"""Unauthenticated health page for Render probes and operators."""

from __future__ import annotations

import json

import streamlit as st

from health import check_health
from ui_common import bootstrap_app, render_footer, render_header

bootstrap_app("Health | Retail Replenishment Agent", require_auth=False)
render_header("Health check")

payload = check_health()
ok = payload["status"] == "ok"

if ok:
    st.success("Application and database are healthy.")
else:
    st.error("Service is degraded — database check failed.")

st.code(json.dumps(payload, indent=2), language="json")
st.caption("This page does not expose API keys, access codes, or database passwords.")
render_footer()
