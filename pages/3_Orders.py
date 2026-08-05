"""Orders — view the current session purchase order confirmation."""

from __future__ import annotations

import streamlit as st

from ui_common import bootstrap_app
from ui_components import page_heading, panel_title


def main() -> None:
    bootstrap_app("Orders | Retail Replenishment Agent", active_nav="orders")
    page_heading("Orders", "Mock purchase orders created in this session")

    order_flow = st.session_state.get("order_flow") or {}
    po = order_flow.get("purchase_order")

    with st.container(border=True):
        panel_title("Current Order")
        if not po:
            st.markdown(
                '<p class="secondary-text">No purchase order in this session yet. '
                "Complete Analysis → Review → Formal Approval to create one.</p>",
                unsafe_allow_html=True,
            )
            if st.button("Go to Analysis", type="primary"):
                st.switch_page("pages/1_Analysis.py")
        else:
            st.markdown(
                f"""
                <div class="il-success-card">
                    <div class="title">Order created successfully</div>
                    <div class="row">Purchase Order ID: <b>{po.get('purchase_order_id')}</b></div>
                    <div class="row">Store: <b>{po.get('store_id')}</b></div>
                    <div class="row">SKU: <b>{po.get('sku')}</b></div>
                    <div class="row">Final Quantity: <b>{po.get('approved_final_quantity')}</b></div>
                    <div class="row">Status: <b>{po.get('status')}</b></div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.expander("View technical details", expanded=False):
                st.json(order_flow)


main()
