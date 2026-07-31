"""Retail replenishment Agentic AI POC — Streamlit application."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from agent import build_agent_context, generate_explanation
from forecast import build_sales_trend, compute_average_daily_sales, forecast_demand
from replenishment import assess_inventory_risk, calculate_replenishment
from styles import inject_styles

DATA_DIR = Path(__file__).parent / "data"
AS_OF_DATE = pd.Timestamp("2026-07-27")


@st.cache_data
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    products = pd.read_csv(DATA_DIR / "products.csv")
    inventory = pd.read_csv(DATA_DIR / "inventory.csv")
    sales = pd.read_csv(DATA_DIR / "sales.csv")
    sales["date"] = pd.to_datetime(sales["date"])
    return products, inventory, sales


def render_card_header(title: str) -> None:
    st.markdown(f'<div class="card-header">{title}</div>', unsafe_allow_html=True)


def render_footer() -> None:
    st.markdown(
        """
        <div class="footer-bar">
            <span>© 2026 Infolob Solutions · Confidential</span>
            <span class="footer-brand">INFOLOB</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def create_mock_po(
    store_id: str,
    store_name: str,
    sku: str,
    product_name: str,
    qty: int,
) -> dict:
    return {
        "po_number": f"PO-MOCK-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "status": "Draft — Mock ERP",
        "store_id": store_id,
        "store_name": store_name,
        "sku": sku,
        "product_name": product_name,
        "order_qty": qty,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def main() -> None:
    st.set_page_config(
        page_title="Retail Replenishment Agent | Infolob",
        page_icon="📦",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    st.markdown(f"<style>{inject_styles()}</style>", unsafe_allow_html=True)

    products_df, inventory_df, sales_df = load_data()

    st.markdown(
        """
        <div class="page-title-wrap">
            <div class="title-stripe"></div>
            <h1 class="page-title">Retail Replenishment Agent</h1>
        </div>
        <p class="page-subtitle">Agentic AI POC · Seven-day forecast · Human-in-the-loop approval</p>
        """,
        unsafe_allow_html=True,
    )

    stores = inventory_df[["store_id", "store_name"]].drop_duplicates().sort_values("store_id")
    store_options = {row.store_name: row.store_id for row in stores.itertuples(index=False)}

    col_left, col_right = st.columns([1, 1], gap="large")

    with col_left:
        st.markdown('<div class="card"><div class="card-body">', unsafe_allow_html=True)

        selected_store_name = st.selectbox(
            "Store",
            options=list(store_options.keys()),
            label_visibility="visible",
        )
        store_id = store_options[selected_store_name]

        store_skus = inventory_df.loc[inventory_df["store_id"] == store_id, "sku"].tolist()
        sku_rows = products_df[products_df["sku"].isin(store_skus)].sort_values("sku")

        selected_sku = st.selectbox(
            "SKU",
            options=sku_rows["sku"].tolist(),
            format_func=lambda s: f"{s} — {sku_rows.loc[sku_rows['sku'] == s, 'product_name'].iloc[0]}",
        )

        product = products_df.loc[products_df["sku"] == selected_sku].iloc[0]
        inv = inventory_df.loc[
            (inventory_df["store_id"] == store_id) & (inventory_df["sku"] == selected_sku)
        ].iloc[0]

        avg_daily = compute_average_daily_sales(sales_df, store_id, selected_sku, AS_OF_DATE)
        forecast = forecast_demand(avg_daily)
        replen = calculate_replenishment(
            total_forecast=forecast["total_forecast"],
            safety_stock=float(product["safety_stock_units"]),
            on_hand=float(inv["on_hand"]),
            in_transit=float(inv["in_transit"]),
            case_pack_size=int(product["case_pack_size"]),
        )
        risk = assess_inventory_risk(
            replen["days_of_supply"],
            replen["recommended_order_qty"],
            forecast["total_forecast"],
            float(inv["on_hand"]),
        )

        st.markdown(
            '<div class="chip-row">'
            '<span class="chip chip-forecast">Forecasting</span>'
            '<span class="chip chip-agent">Analytics Layer</span>'
            "</div>",
            unsafe_allow_html=True,
        )

        st.markdown("</div></div>", unsafe_allow_html=True)

        st.markdown('<div class="card">', unsafe_allow_html=True)
        render_card_header("Sales Trend · Last 14 Days")
        st.markdown('<div class="card-body">', unsafe_allow_html=True)

        trend = build_sales_trend(sales_df, store_id, selected_sku, AS_OF_DATE, days=14)
        if trend.empty:
            st.markdown('<p class="secondary-text">No sales history available.</p>', unsafe_allow_html=True)
        else:
            fig = px.bar(
                trend,
                x="date",
                y="units_sold",
                labels={"date": "Date", "units_sold": "Units Sold"},
            )
            fig.update_layout(
                plot_bgcolor="#FAFBFC",
                paper_bgcolor="#FFFFFF",
                font=dict(family="Aptos, Segoe UI, sans-serif", color="#2C3E50"),
                margin=dict(l=20, r=20, t=30, b=20),
                height=260,
                xaxis=dict(showgrid=False),
                yaxis=dict(gridcolor="#E2E8F0"),
            )
            fig.update_traces(marker_color="#0D9488")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        st.markdown("</div></div>", unsafe_allow_html=True)

        st.markdown('<div class="card">', unsafe_allow_html=True)
        render_card_header("Inventory & Forecast Statistics")
        st.markdown('<div class="card-body">', unsafe_allow_html=True)

        risk_class = {"stockout": "risk-stockout", "overstock": "risk-overstock", "balanced": "risk-balanced"}[risk]
        risk_label = risk.replace("stockout", "Stockout Risk").replace("overstock", "Overstock Risk").replace("balanced", "Balanced")

        st.markdown(
            f'<div class="chip-row"><span class="risk-badge {risk_class}">{risk_label}</span></div>',
            unsafe_allow_html=True,
        )

        dos = replen["days_of_supply"]
        dos_display = f"{dos}" if dos is not None else "N/A"

        st.markdown(
            f"""
            <div class="stat-grid">
                <div class="stat-callout">
                    <div class="stat-label">Avg Daily Sales (7d)</div>
                    <div class="stat-value">{forecast['avg_daily_sales']}</div>
                </div>
                <div class="stat-callout">
                    <div class="stat-label">7-Day Forecast</div>
                    <div class="stat-value">{forecast['total_forecast']}</div>
                </div>
                <div class="stat-callout">
                    <div class="stat-label">On Hand</div>
                    <div class="stat-value">{int(replen['on_hand'])}</div>
                </div>
                <div class="stat-callout">
                    <div class="stat-label">In Transit</div>
                    <div class="stat-value">{int(replen['in_transit'])}</div>
                </div>
                <div class="stat-callout">
                    <div class="stat-label">Safety Stock</div>
                    <div class="stat-value">{int(replen['safety_stock'])}</div>
                </div>
                <div class="stat-callout">
                    <div class="stat-label">Days of Supply</div>
                    <div class="stat-value">{dos_display}</div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div></div>", unsafe_allow_html=True)

    with col_right:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        render_card_header("Agentic AI Recommendation")
        st.markdown('<div class="card-body">', unsafe_allow_html=True)

        st.markdown(
            '<div class="chip-row">'
            '<span class="chip chip-agent">Agentic AI</span>'
            '<span class="chip chip-erp">Mock ERP</span>'
            "</div>",
            unsafe_allow_html=True,
        )

        agent_context = build_agent_context(
            store_name=selected_store_name,
            product_name=product["product_name"],
            sku=selected_sku,
            forecast=forecast,
            replenishment=replen,
            risk_level=risk,
        )

        context_key = (store_id, selected_sku)
        if st.session_state.get("_context_key") != context_key:
            st.session_state["_context_key"] = context_key
            st.session_state.pop("po_record", None)
            st.session_state.pop("approval_status", None)
            st.session_state.pop("agent_explanation", None)

        if "agent_explanation" not in st.session_state:
            with st.spinner("Agent analyzing inventory position…"):
                st.session_state["agent_explanation"] = generate_explanation(agent_context)

        if st.button("Refresh Agent Analysis", type="secondary"):
            with st.spinner("Agent analyzing inventory position…"):
                st.session_state["agent_explanation"] = generate_explanation(agent_context)
                st.session_state["_context_key"] = (store_id, selected_sku)
                st.session_state.pop("po_record", None)
                st.session_state.pop("approval_status", None)
            st.rerun()

        explanation = st.session_state.get("agent_explanation", "")
        st.markdown(
            f'<p class="agent-explanation">{explanation}</p>',
            unsafe_allow_html=True,
        )

        st.markdown(
            f"""
            <div class="navy-band">
                <div class="band-label">Recommended Order Quantity</div>
                <div class="band-value">{replen['recommended_order_qty']} units</div>
            </div>
            <p class="secondary-text">
                Case pack: {replen['case_pack_size']} · Raw calc: {replen['raw_reorder']} → rounded
            </p>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("</div></div>", unsafe_allow_html=True)

    st.markdown(
        f"""
        <div class="recommendation-callout">
            <h4>Replenishment Summary — {product['product_name']}</h4>
            <p class="secondary-text">
                Store <strong>{selected_store_name}</strong> · SKU <strong>{selected_sku}</strong><br>
                Formula: 7-day forecast ({forecast['total_forecast']}) + safety stock ({int(replen['safety_stock'])})
                − on hand ({int(replen['on_hand'])}) − in transit ({int(replen['in_transit'])})
                = <strong>{replen['raw_reorder']}</strong> → order <strong>{replen['recommended_order_qty']}</strong> units
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    btn_col_spacer, btn_col_approve, btn_col_reject = st.columns([3, 1, 1])
    with btn_col_approve:
        approve = st.button("Approve", type="primary", use_container_width=True)
    with btn_col_reject:
        reject = st.button("Reject", type="secondary", use_container_width=True)

    if approve:
        if replen["recommended_order_qty"] > 0:
            st.session_state["po_record"] = create_mock_po(
                store_id,
                selected_store_name,
                selected_sku,
                product["product_name"],
                replen["recommended_order_qty"],
            )
            st.session_state["approval_status"] = "approved"
        else:
            st.session_state["approval_status"] = "approved_no_order"
            st.session_state.pop("po_record", None)

    if reject:
        st.session_state["approval_status"] = "rejected"
        st.session_state.pop("po_record", None)

    status = st.session_state.get("approval_status")
    if status == "approved" and "po_record" in st.session_state:
        po = st.session_state["po_record"]
        st.markdown(
            f"""
            <div class="po-record">
                <strong>Mock Purchase Order Created</strong><br>
                PO #: {po['po_number']} · Status: {po['status']}<br>
                {po['store_name']} · {po['sku']} ({po['product_name']}) · Qty: {po['order_qty']}<br>
                Created: {po['created_at']}
            </div>
            """,
            unsafe_allow_html=True,
        )
    elif status == "approved_no_order":
        st.markdown(
            '<div class="po-record">Approval recorded — no purchase order required (zero reorder quantity).</div>',
            unsafe_allow_html=True,
        )
    elif status == "rejected":
        st.markdown(
            '<div class="po-record" style="border-left-color:#64748B;">Recommendation rejected — no purchase order created.</div>',
            unsafe_allow_html=True,
        )

    render_footer()


if __name__ == "__main__":
    main()
