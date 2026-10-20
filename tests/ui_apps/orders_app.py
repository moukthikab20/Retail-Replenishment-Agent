"""Minimal Streamlit app for Orders / purchasing AppTests."""

from __future__ import annotations

import streamlit as st

from config import ERP_AUTO_TRANSMIT
from services import purchase_order_service
from styles import inject_styles
from ui_components import compact_kpi_row, page_heading, panel_title
from ui_orders import manual_send_visibility

st.set_page_config(page_title="Orders UI Test", layout="wide")
st.markdown(f"<style>{inject_styles()}</style>", unsafe_allow_html=True)

workbench = purchase_order_service.get_orders_workbench()
summary = workbench["summary"]
page_heading("Purchase Orders", workbench.get("subtitle") or "")
compact_kpi_row(
    [
        {"label": "Ready to send", "value": summary.get("ready_to_send", 0)},
        {"label": "Sending", "value": summary.get("sending", 0)},
        {"label": "Accepted", "value": summary.get("accepted", 0)},
        {"label": "Attention needed", "value": summary.get("attention_needed", 0)},
    ],
    columns=4,
)
visibility = manual_send_visibility(
    can_send=True,
    auto_transmit=bool(summary.get("auto_transmit", ERP_AUTO_TRANSMIT)),
    ready_count=int(summary.get("ready_to_send") or 0),
    attention_count=int(summary.get("attention_needed") or 0),
)
if visibility["show"]:
    panel_title(visibility["section"])
    st.button(visibility["label"], type="primary" if visibility["primary"] else "secondary")
panel_title("Orders")
for po in workbench["orders"]:
    st.write(
        f"{po['purchase_order_id']} · {po.get('sku')} · "
        f"{po.get('order_status_label') or po.get('transmission_status')} · "
        f"{po.get('erp_reference') or '—'}"
    )
