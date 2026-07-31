"""Page 1 — Analysis: store/SKU selection, forecast, agent recommendation."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from config import AS_OF_DATE
from repositories import csv_repository
from services import forecast_service, product_service, recommendation_service
from ui_common import (
    bootstrap_app,
    render_card_header,
    render_dev_identity,
    render_footer,
    render_header,
    risk_badge_html,
)


def main() -> None:
    bootstrap_app("Analysis | Retail Replenishment Agent")
    render_header("Analysis · Seven-day forecast · Agent recommendation")
    actor, display_name, role = render_dev_identity()
    st.sidebar.caption(f"Signed in as {display_name} ({role})")

    stores = product_service.list_stores()
    store_options = {s["store_name"]: s["store_id"] for s in stores}

    selected_store_name = st.selectbox("Store", options=list(store_options.keys()))
    store_id = store_options[selected_store_name]
    skus = product_service.list_store_skus(store_id)
    products = {sku: product_service.get_product_details(sku) for sku in skus}
    selected_sku = st.selectbox(
        "SKU",
        options=skus,
        format_func=lambda s: f"{s} — {products[s].product_name}",
    )

    analysis = recommendation_service.build_analysis(store_id, selected_sku)
    product = analysis["product"]
    inventory = analysis["inventory"]
    forecast = analysis["forecast"]
    replenishment = analysis["replenishment"]
    risk = analysis["risk"]

    st.markdown(
        '<div class="chip-row">'
        '<span class="chip chip-forecast">Forecasting</span>'
        '<span class="chip chip-agent">Single Agent</span>'
        "</div>",
        unsafe_allow_html=True,
    )

    # Primary metrics
    st.markdown('<div class="card">', unsafe_allow_html=True)
    render_card_header("Inventory and Forecast Overview")
    st.markdown('<div class="card-body">', unsafe_allow_html=True)
    st.markdown(
        f'<div class="chip-row">{risk_badge_html(risk["risk_level"])}</div>',
        unsafe_allow_html=True,
    )
    dos = replenishment.days_of_supply
    dos_display = f"{dos}" if dos is not None else "N/A"
    st.markdown(
        f"""
        <div class="stat-grid">
            <div class="stat-callout">
                <div class="stat-label">7-Day Forecast</div>
                <div class="stat-value">{forecast.forecast_units}</div>
            </div>
            <div class="stat-callout">
                <div class="stat-label">On Hand</div>
                <div class="stat-value">{inventory.on_hand}</div>
            </div>
            <div class="stat-callout">
                <div class="stat-label">In Transit</div>
                <div class="stat-value">{inventory.in_transit}</div>
            </div>
            <div class="stat-callout">
                <div class="stat-label">Days of Supply</div>
                <div class="stat-value">{dos_display}</div>
            </div>
            <div class="stat-callout">
                <div class="stat-label">Risk</div>
                <div class="stat-value">{risk["risk_level"]}</div>
            </div>
            <div class="stat-callout">
                <div class="stat-label">Recommended Qty</div>
                <div class="stat-value">{replenishment.recommended_quantity}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div></div>", unsafe_allow_html=True)

    # Sales trend
    st.markdown('<div class="card">', unsafe_allow_html=True)
    render_card_header("Sales Trend · Last 14 Days")
    st.markdown('<div class="card-body">', unsafe_allow_html=True)
    sales_df = csv_repository.get_sales_frame()
    trend = forecast_service.build_sales_trend(
        sales_df, store_id, selected_sku, pd.Timestamp(AS_OF_DATE), days=14
    )
    if trend.empty:
        st.markdown('<p class="secondary-text">No sales history available.</p>', unsafe_allow_html=True)
    else:
        fig = px.bar(trend, x="date", y="units_sold", labels={"date": "Date", "units_sold": "Units Sold"})
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

    # Compact agent recommendation
    st.markdown('<div class="card">', unsafe_allow_html=True)
    render_card_header("Agent Recommendation")
    st.markdown('<div class="card-body">', unsafe_allow_html=True)

    decision = st.session_state.get("analysis_decision")
    context_key = (store_id, selected_sku)
    if st.session_state.get("_analysis_context") != context_key:
        st.session_state["_analysis_context"] = context_key
        st.session_state.pop("analysis_decision", None)
        st.session_state.pop("recommendation_id", None)

    if st.button("Run Agent Analysis", type="primary"):
        with st.spinner("Retail Replenishment Agent analyzing…"):
            from agent.runner import run_analysis

            decision = run_analysis(store_id, selected_sku)
            st.session_state["analysis_decision"] = decision
            if decision.get("recommendation_id"):
                st.session_state["recommendation_id"] = decision["recommendation_id"]
        st.rerun()

    decision = st.session_state.get("analysis_decision")
    if decision:
        st.markdown(
            f"""
            <div class="navy-band">
                <div class="band-label">Agent Recommended Quantity</div>
                <div class="band-value">{decision.get('agent_recommended_quantity', replenishment.recommended_quantity)} units</div>
            </div>
            <p class="agent-explanation">{decision.get('explanation', '')}</p>
            <p class="secondary-text">
                Recommendation ID: <strong>{decision.get('recommendation_id')}</strong>
                · Risk: <strong>{decision.get('risk')}</strong>
                · Next: <strong>{decision.get('next_action')}</strong>
            </p>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f"""
            <div class="navy-band">
                <div class="band-label">Deterministic Preview Quantity</div>
                <div class="band-value">{replenishment.recommended_quantity} units</div>
            </div>
            <p class="secondary-text">Run the agent to persist a recommendation and continue to human review.</p>
            """,
            unsafe_allow_html=True,
        )

    with st.expander("Secondary details"):
        st.write(
            {
                "average_daily_sales": float(forecast.average_daily_sales),
                "safety_stock": inventory.safety_stock,
                "usable_on_hand": inventory.usable_on_hand,
                "raw_quantity": float(replenishment.raw_quantity),
                "case_pack": replenishment.case_pack,
                "rounding_adjustment": replenishment.rounding_adjustment,
                "constraints_applied": replenishment.constraints_applied,
                "risk_reasons": risk.get("reasons"),
                "tools_used": (decision or {}).get("tools_used"),
                "mode": (decision or {}).get("mode"),
                "product": product.product_name,
            }
        )

    st.markdown("</div></div>", unsafe_allow_html=True)

    can_continue = bool(st.session_state.get("recommendation_id"))
    if st.button(
        "Continue to Human Review",
        type="primary",
        disabled=not can_continue,
        use_container_width=False,
    ):
        st.session_state["nav_recommendation_id"] = st.session_state["recommendation_id"]
        st.session_state["nav_store_id"] = store_id
        st.session_state["nav_sku"] = selected_sku
        from database.connection import get_session
        from repositories import audit_repository

        with get_session() as session:
            audit_repository.write_audit_event(
                session,
                "human_review_opened",
                actor=actor,
                actor_role=role,
                recommendation_id=st.session_state["recommendation_id"],
            )
        st.switch_page("pages/2_Human_Review.py")

    if not can_continue:
        st.caption("Run agent analysis first so a recommendation_id is saved.")

    render_footer()


main()
