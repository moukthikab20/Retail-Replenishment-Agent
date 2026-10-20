"""Minimal Streamlit app for Approved for Purchase AppTests."""

from __future__ import annotations

import streamlit as st

from services import queue_service
from styles import inject_styles
from ui_components import compact_kpi_row, page_heading, panel_title

st.set_page_config(page_title="Approved UI Test", layout="wide")
st.markdown(f"<style>{inject_styles()}</style>", unsafe_allow_html=True)

payload = queue_service.get_approved_today()
run = payload.get("run")
summary = payload["summary"]
subtitle = summary.get("story") or (
    f"Run {run['run_id']}" if run else "No replenishment run is available yet"
)
page_heading("Approved for Purchase", subtitle)
compact_kpi_row(
    [
        {"label": "Approved today", "value": summary.get("approved_today", summary["total"])},
        {"label": "Handled automatically", "value": summary["auto_released"]},
        {"label": "Approved by people", "value": summary["human_approved"]},
        {"label": "Total value", "value": summary["order_value_display"]},
    ],
    columns=4,
)
panel_title("Approved decisions")
for row in payload["rows"]:
    st.write(
        f"{row['sku']} · {row.get('approval_source') or row['source']} · "
        f"{row['final_quantity']} · {row.get('next_step') or '—'}"
    )
