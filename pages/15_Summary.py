"""Summary — historical replenishment intelligence analytics."""

from __future__ import annotations

from datetime import date

import streamlit as st

from services import product_service
from services.summary_analytics_service import (
    SummaryFilters,
    build_summary_dashboard,
    filter_options,
    resolve_preset,
)
from ui_common import bootstrap_app
from ui_components import page_heading, panel_title
from ui_summary import (
    render_agent_human_trend,
    render_decision_ownership,
    render_excess_inventory,
    render_historical_decisions,
    render_inventory_efficiency,
    render_period_summary,
    render_product_performance,
    render_recommendation_performance,
    render_replenishment_efficiency,
    render_sales_trend,
    render_sales_vs_replenishment,
    render_stockout_analysis,
    render_stockout_horizon,
    render_top_overrides,
    render_vendor_performance,
    section_heading,
)


def main() -> None:
    bootstrap_app("Summary | Retail Replenishment Agent", active_nav="summary")
    page_heading(
        "Summary",
        "Analyze replenishment history, sales performance, decision outcomes, and inventory trends.",
    )

    options = filter_options()
    preset_labels = [label for _, label in options["date_presets"]]
    preset_keys = {label: key for key, label in options["date_presets"]}

    with st.container(border=True):
        panel_title("Filters")
        r1c1, r1c2, r1c3, r1c4 = st.columns(4)
        with r1c1:
            preset_label = st.selectbox(
                "Date range",
                options=preset_labels,
                index=preset_labels.index("Last 30 Days")
                if "Last 30 Days" in preset_labels
                else 0,
                key="summary_date_preset",
            )
        preset = preset_keys[preset_label]
        with r1c2:
            store_labels = ["All stores"] + [s["store_name"] for s in options["stores"]]
            store_pick = st.selectbox("Store", options=store_labels, key="summary_store")
        with r1c3:
            sku_labels = ["All products"] + [s["label"] for s in options["skus"]]
            sku_pick = st.selectbox("Product / SKU", options=sku_labels, key="summary_sku")
        with r1c4:
            cat_options = ["All categories"] + (options.get("categories") or [])
            st.selectbox(
                "Category",
                options=cat_options,
                key="summary_category",
                help="Product master has no category field — filter is inactive.",
                disabled=len(cat_options) <= 1,
            )

        r2c1, r2c2, r2c3, r2c4 = st.columns(4)
        with r2c1:
            vendor_labels = ["All vendors"] + list(options["vendors"])
            vendor_pick = st.selectbox("Vendor", options=vendor_labels, key="summary_vendor")
        with r2c2:
            decision_labels = [label for _, label in options["decision_types"]]
            decision_keys = {label: key for key, label in options["decision_types"]}
            decision_pick = st.selectbox(
                "Decision type", options=decision_labels, key="summary_decision"
            )
        with r2c3:
            risk_labels = [label for _, label in options["risk_levels"]]
            risk_keys = {label: key for key, label in options["risk_levels"]}
            risk_pick = st.selectbox("Risk level", options=risk_labels, key="summary_risk")
        with r2c4:
            sales_window = st.selectbox(
                "Sales trend window",
                options=[1, 7, 10, 30, 90],
                index=3,
                format_func=lambda d: f"{d}D",
                key="summary_sales_window",
            )

        custom_from: date | None = None
        custom_to: date | None = None
        if preset == "custom":
            c1, c2 = st.columns(2)
            with c1:
                custom_from = st.date_input("From", key="summary_custom_from")
            with c2:
                custom_to = st.date_input("To", key="summary_custom_to")

    date_from, date_to = resolve_preset(
        preset, custom_from=custom_from, custom_to=custom_to
    )
    store_id = (
        None
        if store_pick == "All stores"
        else product_service.store_id_for_display_name(store_pick)
    )
    sku = None
    if sku_pick != "All products":
        sku = sku_pick.split(" — ", 1)[0].strip()
    vendor = None if vendor_pick == "All vendors" else vendor_pick

    filters = SummaryFilters(
        date_from=date_from,
        date_to=date_to,
        store_id=store_id,
        sku=sku,
        vendor=vendor,
        decision_type=decision_keys[decision_pick],
        risk_level=risk_keys[risk_pick],
        sales_window_days=int(sales_window),
    )

    st.caption(
        f"Period: {date_from.isoformat()} → {date_to.isoformat()} "
        f"(analytics as-of {options['as_of']})"
    )

    dash = build_summary_dashboard(filters)

    section_heading("Period summary")
    render_period_summary(dash["period_summary"])

    section_heading("Decision ownership")
    render_decision_ownership(dash["decision_ownership"])

    section_heading(
        "Agent vs human trend",
        "Share of agent-approved decisions versus human intervention over time.",
    )
    render_agent_human_trend(dash["agent_vs_human_trend"])

    section_heading("Top human overrides")
    render_top_overrides(dash["top_overrides"])

    section_heading("Sales vs replenishment")
    render_sales_vs_replenishment(dash["sales_vs_replenishment"])

    section_heading("Sales trend")
    render_sales_trend(dash["sales_trend"])

    section_heading("Recommendation performance")
    render_recommendation_performance(dash["recommendation_performance"])

    section_heading("Replenishment efficiency")
    render_replenishment_efficiency(dash["replenishment_efficiency"])

    section_heading("Stockout analysis")
    render_stockout_analysis(dash["stockout_analysis"])

    section_heading("Stockout horizon", "Projected coverage buckets for stockout-risk SKUs.")
    render_stockout_horizon(dash["stockout_horizon"])

    section_heading("Excess inventory")
    render_excess_inventory(dash["excess_inventory"])

    section_heading("Inventory efficiency")
    render_inventory_efficiency(dash["inventory_efficiency"])

    section_heading("Vendor performance")
    render_vendor_performance(dash["vendor_performance"])

    section_heading(
        "Product performance",
        "Days of supply vs sales velocity (median split into quadrants).",
    )
    render_product_performance(dash["product_performance"])

    section_heading("Historical replenishment decisions")
    render_historical_decisions(dash["historical_decisions"])

    with st.expander("Data notes", expanded=False):
        for note in dash.get("data_notes") or []:
            st.markdown(f"- {note}")


main()
