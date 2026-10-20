"""Summary / replenishment intelligence presentation helpers."""

from __future__ import annotations

from html import escape
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from services.summary_analytics_service import UNAVAILABLE
from ui_components import compact_kpi_row, panel_title


def section_heading(title: str, subtitle: str | None = None) -> None:
    sub = f'<p class="il-sum-sec-sub">{escape(subtitle)}</p>' if subtitle else ""
    st.markdown(
        f'<div class="il-sum-sec"><h2 class="il-sum-sec-title">{escape(title)}</h2>{sub}</div>',
        unsafe_allow_html=True,
    )


def unavailable(message: str = UNAVAILABLE, detail: str | None = None) -> None:
    text = escape(message)
    if detail:
        text += f'<div class="il-sum-muted">{escape(detail)}</div>'
    st.markdown(f'<div class="il-sum-empty">{text}</div>', unsafe_allow_html=True)


def render_period_summary(cards: list[dict[str, Any]]) -> None:
    items = []
    for card in cards:
        items.append(
            {
                "label": card["label"],
                "value": card["value"],
                "sub": card.get("sub") or "",
            }
        )
    compact_kpi_row(items, columns=min(4, max(len(items), 1)))


def render_decision_ownership(ownership: list[dict[str, Any]]) -> None:
    if not ownership or sum(o["count"] for o in ownership) == 0:
        unavailable()
        return
    total = sum(o["count"] for o in ownership) or 1
    colors = {
        "agent_approved": "#167A38",
        "human_approved": "#1d4ed8",
        "human_adjusted": "#c2410c",
        "rejected": "#6b7280",
    }
    segments = "".join(
        f'<div class="il-sum-stack-seg" style="flex:{max(o["count"], 0)};'
        f'background:{colors.get(o["key"], "#94a3b8")}" '
        f'title="{escape(o["label"])}: {o["count"]} ({o["percent"]}%)"></div>'
        for o in ownership
        if o["count"] > 0
    )
    legend = "".join(
        f'<div class="il-sum-legend-item">'
        f'<span class="swatch" style="background:{colors.get(o["key"], "#94a3b8")}"></span>'
        f'<span><b>{escape(o["label"])}</b> — {o["count"]} ({o["percent"]}%)</span></div>'
        for o in ownership
    )
    st.markdown(
        f"""
        <div class="il-sum-card">
          <div class="il-sum-stack">{segments or '<div class="il-sum-stack-seg" style="flex:1;background:#E5E9EF"></div>'}</div>
          <div class="il-sum-legend">{legend}</div>
          <div class="il-sum-muted">n = {total} classified decisions in the selected period</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_agent_human_trend(payload: dict[str, Any]) -> None:
    if not payload.get("available"):
        unavailable(payload.get("message") or UNAVAILABLE)
        return
    points = payload.get("points") or []
    frame = pd.DataFrame(points)
    if frame.empty:
        unavailable()
        return
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=frame["period"],
            y=frame["agent_pct"],
            name="Agent-approved %",
            mode="lines+markers",
            line={"color": "#167A38", "width": 2},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=frame["period"],
            y=frame["human_pct"],
            name="Human intervention %",
            mode="lines+markers",
            line={"color": "#c2410c", "width": 2},
        )
    )
    fig.update_layout(
        height=320,
        margin={"l": 40, "r": 20, "t": 30, "b": 40},
        yaxis_title="Percent",
        xaxis_title="Period" if payload.get("grain") == "day" else "Week starting",
        legend={"orientation": "h", "y": 1.12},
        plot_bgcolor="#fff",
        paper_bgcolor="#fff",
        font={"color": "#1f2937"},
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_top_overrides(payload: dict[str, Any]) -> None:
    if not payload.get("available"):
        unavailable(payload.get("message") or UNAVAILABLE)
        return
    frame = pd.DataFrame(payload["rows"])
    frame = frame.rename(
        columns={
            "product": "Product",
            "agent_recommendations": "Agent recommendations",
            "human_overrides": "Human overrides",
            "override_pct": "Override %",
            "avg_qty_adjustment": "Average quantity adjustment",
        }
    )
    st.dataframe(
        frame[
            [
                "Product",
                "Agent recommendations",
                "Human overrides",
                "Override %",
                "Average quantity adjustment",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )


def render_sales_vs_replenishment(payload: dict[str, Any]) -> None:
    if not payload.get("available"):
        unavailable(payload.get("message") or UNAVAILABLE)
        return
    frame = pd.DataFrame(payload["points"])
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=frame["date"],
            y=frame["units_sold"],
            name="Units sold",
            mode="lines+markers",
            line={"color": "#1d4ed8", "width": 2},
            customdata=frame[["units_ordered", "difference"]],
            hovertemplate=(
                "Date: %{x}<br>Units sold: %{y}<br>"
                "Units ordered: %{customdata[0]}<br>"
                "Difference: %{customdata[1]}<br>"
                "Ending inventory: not available"
                "<extra></extra>"
            ),
        )
    )
    fig.add_trace(
        go.Scatter(
            x=frame["date"],
            y=frame["units_ordered"],
            name="Units ordered",
            mode="lines+markers",
            line={"color": "#167A38", "width": 2},
            customdata=frame[["units_sold", "difference"]],
            hovertemplate=(
                "Date: %{x}<br>Units ordered: %{y}<br>"
                "Units sold: %{customdata[0]}<br>"
                "Difference: %{customdata[1]}<br>"
                "Ending inventory: not available"
                "<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        height=340,
        margin={"l": 40, "r": 20, "t": 30, "b": 40},
        legend={"orientation": "h", "y": 1.12},
        plot_bgcolor="#fff",
        paper_bgcolor="#fff",
        font={"color": "#1f2937"},
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    if payload.get("note"):
        st.caption(payload["note"])


def render_sales_trend(payload: dict[str, Any]) -> None:
    if not payload.get("available"):
        unavailable(payload.get("message") or UNAVAILABLE)
        return
    frame = pd.DataFrame(payload["points"])
    fig = px.line(frame, x="date", y="units_sold", markers=True)
    fig.update_traces(line={"color": "#1d4ed8", "width": 2})
    fig.update_layout(
        height=300,
        margin={"l": 40, "r": 20, "t": 20, "b": 40},
        yaxis_title="Units sold",
        xaxis_title="Date",
        plot_bgcolor="#fff",
        paper_bgcolor="#fff",
        font={"color": "#1f2937"},
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    stats = payload.get("stats")
    if stats:
        change = stats.get("change_pct")
        change_txt = (
            f"{'↑' if change >= 0 else '↓'} {abs(change):.1f}% vs previous {payload['window_days']} days"
            if change is not None
            else UNAVAILABLE
        )
        compact_kpi_row(
            [
                {"label": "Units sold", "value": f"{stats['units_sold']:,.0f}"},
                {"label": "Average daily sales", "value": f"{stats['avg_daily_sales']:,.2f}"},
                {
                    "label": "Highest sales day",
                    "value": f"{stats['highest_day']['units']:,.0f}",
                    "sub": stats["highest_day"]["date"],
                },
                {
                    "label": "Lowest sales day",
                    "value": f"{stats['lowest_day']['units']:,.0f}",
                    "sub": stats["lowest_day"]["date"],
                },
                {"label": "% change vs prior period", "value": change_txt},
            ],
            columns=5,
        )
    elif payload.get("stats_note"):
        st.caption(payload["stats_note"])


def render_recommendation_performance(payload: dict[str, Any]) -> None:
    unavailable(payload.get("message") or UNAVAILABLE, payload.get("detail"))


def render_stockout_analysis(payload: dict[str, Any]) -> None:
    if not payload.get("available"):
        unavailable(payload.get("message") or UNAVAILABLE)
        return
    compact_kpi_row(
        [
            {
                "label": k["label"],
                "value": k["value"],
                "sub": k.get("sub"),
            }
            for k in payload.get("kpis") or []
        ],
        columns=4,
    )
    worst = payload.get("worst") or []
    if worst:
        frame = pd.DataFrame(worst)
        show = frame.rename(
            columns={
                "product": "Product",
                "store": "Store",
                "stockout_days": "Stockout days",
                "lost_units": "Lost units",
                "lost_revenue": "Lost revenue",
                "risk_events": "Risk events",
            }
        )
        cols = ["Product", "Store", "Stockout days", "Lost units", "Lost revenue", "Risk events"]
        st.dataframe(show[cols], use_container_width=True, hide_index=True)


def render_stockout_horizon(payload: dict[str, Any]) -> None:
    if not payload.get("available"):
        unavailable(payload.get("message") or UNAVAILABLE)
        return
    buckets = payload.get("buckets") or []
    max_count = max((b["count"] for b in buckets), default=1) or 1
    bars = "".join(
        f'<div class="il-sum-hbar-row">'
        f'<div class="lab">{escape(b["label"])}</div>'
        f'<div class="track"><div class="fill" style="width:{b["count"] / max_count * 100:.1f}%"></div></div>'
        f'<div class="val">{b["count"]} SKUs</div></div>'
        for b in buckets
    )
    st.markdown(f'<div class="il-sum-card">{bars}</div>', unsafe_allow_html=True)
    if payload.get("note"):
        st.caption(payload["note"])


def render_excess_inventory(payload: dict[str, Any]) -> None:
    if not payload.get("available"):
        unavailable(payload.get("message") or UNAVAILABLE)
        return
    compact_kpi_row(
        [{"label": k["label"], "value": k["value"]} for k in payload.get("kpis") or []],
        columns=3,
    )
    if payload.get("note"):
        st.caption(payload["note"])
    rows = payload.get("rows") or []
    if rows:
        frame = pd.DataFrame(rows).rename(
            columns={
                "product": "Product",
                "store": "Store",
                "days_of_supply": "Days of supply",
                "units_on_hand": "Units on hand",
                "sales_velocity": "Sales velocity",
                "inventory_value": "Inventory value",
                "days_since_last_sale": "Days since last sale",
            }
        )
        st.markdown("##### Slow-moving inventory")
        st.dataframe(
            frame[
                [
                    "Product",
                    "Store",
                    "Days of supply",
                    "Units on hand",
                    "Sales velocity",
                    "Inventory value",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )


def render_inventory_efficiency(payload: dict[str, Any]) -> None:
    unavailable(payload.get("message") or UNAVAILABLE, payload.get("detail"))


def render_vendor_performance(payload: dict[str, Any]) -> None:
    if not payload.get("available"):
        unavailable(payload.get("message") or UNAVAILABLE)
        return
    frame = pd.DataFrame(payload["rows"]).rename(
        columns={
            "vendor": "Vendor",
            "orders": "Orders",
            "units": "Units",
            "spend": "Spend",
            "avg_lead_time": "Average lead time",
            "fill_rate": "Fill rate",
            "late_delivery_pct": "Late delivery %",
        }
    )
    st.dataframe(frame, use_container_width=True, hide_index=True)
    if payload.get("note"):
        st.caption(payload["note"])


def render_product_performance(payload: dict[str, Any]) -> None:
    if not payload.get("available"):
        unavailable(payload.get("message") or UNAVAILABLE)
        return
    frame = pd.DataFrame(payload["points"])
    fig = px.scatter(
        frame,
        x="days_of_supply",
        y="sales_velocity",
        color="quadrant",
        hover_name="product",
        hover_data=["sku", "store"],
        labels={
            "days_of_supply": "Days of supply",
            "sales_velocity": "Sales velocity (avg daily)",
            "quadrant": "Quadrant",
        },
        color_discrete_map={
            "Stockout risk": "#b91c1c",
            "Ideal": "#167A38",
            "Slow movers": "#c2410c",
            "Potential over-ordering": "#1d4ed8",
        },
    )
    fig.add_vline(x=payload["mid_days_of_supply"], line_dash="dot", line_color="#94a3b8")
    fig.add_hline(y=payload["mid_sales_velocity"], line_dash="dot", line_color="#94a3b8")
    fig.update_layout(
        height=420,
        margin={"l": 40, "r": 20, "t": 30, "b": 40},
        plot_bgcolor="#fff",
        paper_bgcolor="#fff",
        font={"color": "#1f2937"},
        legend={"orientation": "h", "y": 1.12},
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_replenishment_efficiency(payload: dict[str, Any]) -> None:
    if not payload.get("available"):
        unavailable(payload.get("message") or UNAVAILABLE)
        return
    compact_kpi_row(
        [
            {
                "label": m["label"],
                "value": m["value"],
                "sub": m.get("sub"),
            }
            for m in payload.get("metrics") or []
        ],
        columns=5,
    )


def render_historical_decisions(rows: list[dict[str, Any]]) -> None:
    if not rows:
        unavailable()
        return
    frame = pd.DataFrame(rows)
    display = frame.rename(
        columns={
            "date": "Date",
            "product": "Product / SKU",
            "store": "Store",
            "agent_quantity": "Agent quantity",
            "final_quantity": "Final quantity",
            "decision": "Decision",
            "sales_after_order": "Sales after order",
            "outcome": "Outcome",
        }
    )
    st.dataframe(
        display[
            [
                "Date",
                "Product / SKU",
                "Store",
                "Agent quantity",
                "Final quantity",
                "Decision",
                "Sales after order",
                "Outcome",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )
    options = {
        f"{r['date']} · {r['product']} · {r.get('store') or '—'}": r["recommendation_id"]
        for r in rows
        if r.get("recommendation_id")
    }
    if not options:
        return
    with st.container(border=True):
        panel_title("Open decision detail")
        pick = st.selectbox(
            "Select a historical decision",
            options=["(select)"] + list(options.keys()),
            key="summary_hist_pick",
        )
        if pick != "(select)" and st.button(
            "Open Decision Detail", type="primary", key="summary_open_detail"
        ):
            rid = options[pick]
            st.session_state["nav_recommendation_id"] = rid
            st.session_state["recommendation_id"] = rid
            st.switch_page("pages/2_Review.py")
