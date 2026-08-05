"""Page 1 — Analysis: store/SKU selection, forecast, agent recommendation."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from config import AS_OF_DATE
from repositories import csv_repository
from services import auth_service, forecast_service, product_service, recommendation_service
from services.errors import user_facing_error
from ui_common import bootstrap_app
from ui_components import kpi_row, page_heading, panel_title, risk_pill
from ui_follow_up import render_follow_up_section

_NEXT_ACTION_LABELS = {
    "review_recommendation": "Review Recommendation",
    "await_human_review": "Review Recommendation",  # legacy values
    "no_order_required": "No Order Required",
    "manual_data_review": "Manual Data Review",
    "blocked": "Blocked",
}


def _format_next_action(value: object) -> str:
    if value is None:
        return ""
    key = str(value)
    return _NEXT_ACTION_LABELS.get(key, key.replace("_", " ").title())


def main() -> None:
    user = bootstrap_app(
        "Analysis | Retail Replenishment Agent",
        active_nav="analysis",
    )
    actor = user["user_id"]
    role = user["role"]
    session_id = user["session_id"]

    page_heading("Analysis", "Seven-day forecast and replenishment recommendation")

    stores = product_service.list_stores()
    store_options = {s["store_name"]: s["store_id"] for s in stores}

    t1, t2 = st.columns(2)
    with t1:
        selected_store_name = st.selectbox("Store", options=list(store_options.keys()))
    store_id = store_options[selected_store_name]
    skus = product_service.list_store_skus(store_id)
    products = {sku: product_service.get_product_details(sku) for sku in skus}
    with t2:
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

    context_key = (store_id, selected_sku)
    if st.session_state.get("_analysis_context") != context_key:
        st.session_state["_analysis_context"] = context_key
        st.session_state.pop("analysis_decision", None)
        st.session_state.pop("recommendation_id", None)
        st.session_state.pop("follow_up_answer", None)
        st.session_state.pop("follow_up_question", None)

    can_run = auth_service.can_run_analysis(role)
    if not can_run:
        st.info("Your role can view forecast metrics but cannot generate a recommendation.")

    if st.button("Generate Recommendation", type="primary", disabled=not can_run):
        with st.spinner("Generating recommendation…"):
            from agent.runner import analyze_replenishment

            try:
                decision = analyze_replenishment(
                    store_id,
                    selected_sku,
                    user_id=actor,
                    session_id=session_id,
                    actor=actor,
                    actor_role=role,
                )
                st.session_state["analysis_decision"] = decision
                if decision.get("recommendation_id"):
                    st.session_state["recommendation_id"] = decision["recommendation_id"]
                st.session_state.pop("follow_up_answer", None)
                st.session_state.pop("follow_up_question", None)
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(user_facing_error(exc))

    dos = replenishment.days_of_supply
    dos_display = f"{dos}" if dos is not None else "N/A"
    kpi_row(
        [
            {"label": "7-Day Forecast", "value": forecast.forecast_units},
            {"label": "On Hand", "value": inventory.on_hand},
            {"label": "In Transit", "value": inventory.in_transit},
            {"label": "Days of Supply", "value": dos_display},
            {
                "label": "Risk",
                "value": str(risk["risk_level"]).replace("_", " ").title(),
            },
        ]
    )
    st.markdown(risk_pill(risk["risk_level"]), unsafe_allow_html=True)

    left, right = st.columns([1.55, 1])
    with left:
        with st.container(border=True):
            panel_title("Sales Trend", "Last 14 days")
            sales_df = csv_repository.get_sales_frame()
            trend = forecast_service.build_sales_trend(
                sales_df, store_id, selected_sku, pd.Timestamp(AS_OF_DATE), days=14
            )
            if trend.empty:
                st.markdown(
                    '<p class="secondary-text">No sales history available.</p>',
                    unsafe_allow_html=True,
                )
            else:
                fig = px.bar(
                    trend,
                    x="date",
                    y="units_sold",
                    labels={"date": "Date", "units_sold": "Units Sold"},
                )
                fig.update_layout(
                    plot_bgcolor="#FFFFFF",
                    paper_bgcolor="#FFFFFF",
                    font=dict(family="Segoe UI, sans-serif", color="#1C2B3A"),
                    margin=dict(l=20, r=20, t=20, b=20),
                    height=280,
                    xaxis=dict(showgrid=False),
                    yaxis=dict(gridcolor="#E6EAEF"),
                )
                fig.update_traces(marker_color="#C0392B")
                st.plotly_chart(
                    fig, use_container_width=True, config={"displayModeBar": False}
                )

    with right:
        with st.container(border=True):
            panel_title("Inventory Position")
            kpi_row(
                [
                    {"label": "On Hand", "value": inventory.on_hand},
                    {"label": "In Transit", "value": inventory.in_transit},
                    {"label": "Safety Stock", "value": inventory.safety_stock},
                    {"label": "Usable On Hand", "value": inventory.usable_on_hand},
                ],
                columns=2,
            )
            st.markdown(
                f'<p class="il-meta-line">Product: <strong>{product.product_name}</strong></p>',
                unsafe_allow_html=True,
            )

    with st.container(border=True):
        panel_title("Agent Recommendation")
        decision = st.session_state.get("analysis_decision")
        if decision:
            qty = decision.get(
                "agent_recommended_quantity", replenishment.recommended_quantity
            )
            kpi_row(
                [
                    {
                        "label": "Recommended Quantity",
                        "value": f"{qty} units",
                        "accent": True,
                        "sub": _format_next_action(decision.get("next_action")),
                    }
                ],
                columns=1,
            )
            st.markdown(
                f'<p class="agent-explanation">{decision.get("explanation", "")}</p>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f"""
                <p class="il-meta-line">
                Recommendation ID: <strong>{decision.get('recommendation_id')}</strong>
                · Risk: <strong>{decision.get('risk')}</strong>
                · Next: <strong>{_format_next_action(decision.get('next_action'))}</strong>
                </p>
                """,
                unsafe_allow_html=True,
            )
        else:
            kpi_row(
                [
                    {
                        "label": "Preview Quantity",
                        "value": f"{replenishment.recommended_quantity} units",
                        "accent": True,
                        "sub": "Generate a recommendation to continue",
                    }
                ],
                columns=1,
            )

        with st.expander("View technical details", expanded=False):
            # Prefer structured decision fields when a run has completed.
            d = decision or {}
            st.write(
                {
                    "forecast_days": d.get("forecast_days", 7),
                    "forecast_units": d.get(
                        "forecast_units", float(forecast.forecast_units)
                    ),
                    "average_daily_sales": d.get(
                        "average_daily_sales", float(forecast.average_daily_sales)
                    ),
                    "usable_on_hand": d.get(
                        "usable_on_hand", inventory.usable_on_hand
                    ),
                    "in_transit": d.get("in_transit", inventory.in_transit),
                    "open_order_quantity": d.get("open_order_quantity"),
                    "safety_stock": d.get("safety_stock", inventory.safety_stock),
                    "days_of_supply": d.get(
                        "days_of_supply", replenishment.days_of_supply
                    ),
                    "raw_quantity": d.get(
                        "raw_quantity", float(replenishment.raw_quantity)
                    ),
                    "case_pack": d.get("case_pack", replenishment.case_pack),
                    "confidence": d.get("confidence"),
                    "confidence_basis": d.get("confidence_basis"),
                    "warnings": d.get("warnings"),
                    "rounding_adjustment": replenishment.rounding_adjustment,
                    "constraints_applied": d.get(
                        "constraints_applied", replenishment.constraints_applied
                    ),
                    "risk_reasons": risk.get("reasons"),
                    "tools_used": d.get("tools_used"),
                    "mode": d.get("mode"),
                    "product": d.get("product_name", product.product_name),
                }
            )

    recommendation_id = st.session_state.get("recommendation_id")
    if recommendation_id:
        decision = st.session_state.get("analysis_decision") or {}
        render_follow_up_section(
            recommendation_id=recommendation_id,
            user_id=actor,
            session_id=session_id,
            actor=actor,
            actor_role=role,
            agent_recommended_quantity=decision.get("agent_recommended_quantity"),
        )

    can_continue = bool(recommendation_id)
    if st.button(
        "Review Recommendation",
        type="primary",
        disabled=not can_continue,
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
                user_id=actor,
                session_id=session_id,
            )
        st.switch_page("pages/2_Review.py")

    if not can_continue:
        st.caption("Generate a recommendation before continuing to Review.")


main()
