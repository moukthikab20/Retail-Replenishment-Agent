"""Drill-down views for Overview dashboard tiles (presentation only)."""

from __future__ import annotations

from datetime import datetime
from html import escape
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from services import auth_service, evidence_service, overview_dashboard_service, product_service
from ui_components import page_heading, status_pill
from ui_decision import render_decision_workflow


def _store_label(row: dict[str, Any]) -> str:
    return row.get("store_name") or product_service.store_display_name(
        row.get("store_id") or row.get("store")
    )

# Map session / page category → get_tile_detail key.
CATEGORY_TO_TILE = {
    "needs_review": "needs_review",
    "blocked": "blocked",
    "handled_automatically": "automated",
    "automated": "automated",
    "expected_deliveries": "deliveries",
    "deliveries": "deliveries",
}

EMPTY_COPY = {
    "needs_review": "Nothing currently requires your review.",
    "blocked": "No recommendations are currently blocked.",
    "handled_automatically": "No decisions have been handled automatically yet.",
    "automated": "No decisions have been handled automatically yet.",
    "expected_deliveries": "No inbound deliveries are currently expected.",
    "deliveries": "No inbound deliveries are currently expected.",
}

SUBTITLES = {
    "needs_review": "Items held for human judgment.",
    "blocked": "Items the agent could not progress automatically.",
    "handled_automatically": "Decisions completed by the agent without human intervention.",
    "automated": "Decisions completed by the agent without human intervention.",
    "expected_deliveries": "Inbound purchase orders currently expected.",
    "deliveries": "Inbound purchase orders currently expected.",
}


def _sales_chart(store_id: str | None, sku: str | None) -> None:
    st.markdown("#### Recent sales")
    if not store_id or not sku:
        st.caption("Not enough recent sales history to chart.")
        return
    series = overview_dashboard_service.get_item_sales_series(str(store_id), str(sku), days=14)
    if not series.get("ok"):
        st.caption(series.get("message") or "Not enough recent sales history to chart.")
        return
    frame = pd.DataFrame(series["points"])
    frame = frame.rename(columns={"date": "Date", "units_sold": "Units sold"})
    frame = frame.set_index("Date")
    st.line_chart(frame, height=180)


def _open_review(recommendation_id: str) -> None:
    st.session_state["nav_recommendation_id"] = recommendation_id
    st.session_state["recommendation_id"] = recommendation_id
    st.switch_page("pages/2_Review.py")


def _back_overview() -> None:
    if st.button("← Back to Overview", key="tile_back_overview"):
        st.switch_page("pages/0_Overview.py")


def _empty_state(category: str) -> None:
    message = EMPTY_COPY.get(category) or "No items in this category."
    st.markdown(
        '<div class="il-dash-panel" style="margin-top:8px">'
        '<div class="il-dash-panel-body">'
        f'<div class="il-dash-zero">'
        f'<div class="il-dash-zero-title">{escape(message)}</div>'
        '<div class="il-dash-zero-sub">Return to Overview to choose another category.</div>'
        "</div></div></div>",
        unsafe_allow_html=True,
    )


def _evidence_bits(row: dict[str, Any], *, actor: str, role: str) -> dict[str, Any]:
    rid = row.get("recommendation_id")
    out: dict[str, Any] = {
        "rationale": None,
        "guardrail": None,
        "impact": None,
        "supplier": None,
    }
    if not rid:
        return out
    try:
        evidence = evidence_service.get_recommendation_evidence(
            rid,
            user_id=actor,
            role=role,
            check_access=True,
        )
        out["rationale"] = evidence.get("rationale") or evidence.get("summary")
        out["guardrail"] = evidence.get("guardrail_summary") or evidence.get("policy_summary")
        out["impact"] = evidence.get("expected_impact") or evidence.get("impact_if_approved")
        failed = evidence.get("failed_rules") or row.get("failed_rules")
        if failed and not out["guardrail"]:
            out["guardrail"] = ", ".join(str(x) for x in failed[:4])
        supplier = evidence.get("supplier_status") or evidence.get("supplier_name")
        if supplier:
            out["supplier"] = supplier
    except Exception:  # noqa: BLE001
        pass
    return out


def _item_deep_detail(
    row: dict[str, Any],
    *,
    actor: str,
    role: str,
    session_id: str | None = None,
    show_decision: bool = False,
) -> None:
    bits = _evidence_bits(row, actor=actor, role=role)

    st.markdown("#### Inventory position")
    cols = st.columns(4)
    cols[0].metric("On hand", row.get("on_hand_display") or "—")
    cols[1].metric("Incoming", row.get("in_transit_display") or "—")
    cols[2].metric("Days of supply", row.get("days_of_supply_display") or "—")
    cols[3].metric("Safety stock", row.get("safety_stock_display") or "—")

    st.markdown("#### Why the agent flagged it")
    st.write(row.get("why_review") or row.get("why") or row.get("exception") or "—")

    st.markdown("#### Agent recommendation")
    st.write(f"Quantity: **{row.get('agent_qty_display') or '—'}**")
    if bits["rationale"]:
        st.write(str(bits["rationale"])[:400])
    else:
        st.caption("Reasoning is available on the full recommendation detail.")

    st.markdown("#### Policy / guardrail")
    if bits["guardrail"]:
        st.write(str(bits["guardrail"])[:280])
    else:
        failed = row.get("failed_rules") or []
        st.write(", ".join(str(x) for x in failed[:4]) if failed else "Human review required by policy.")

    st.markdown("#### Expected impact")
    if bits["impact"]:
        st.write(str(bits["impact"])[:280])
    else:
        st.caption("Impact metrics are shown only when supported by persisted evidence.")

    _sales_chart(row.get("store_id") or row.get("store"), row.get("sku"))

    rid = row.get("recommendation_id")
    if show_decision and rid and auth_service.can_submit_human_review(role):
        try:
            from services import recommendation_service

            rec = recommendation_service.get_recommendation(
                rid, user_id=actor, role=role, check_access=True
            )
            render_decision_workflow(
                recommendation_id=rid,
                rec=rec if isinstance(rec, dict) else {"disposition": row.get("disposition")},
                actor=actor,
                role=role,
                session_id=session_id or "sess-tile",
            )
        except Exception:  # noqa: BLE001
            if st.button("Review / decide on recommendation", key=f"nr_decide_{rid}"):
                _open_review(rid)
    elif rid:
        if st.button("Open recommendation detail", key=f"nr_open_{rid}"):
            _open_review(rid)


def _render_needs_review_rows(
    detail: dict[str, Any],
    *,
    actor: str,
    actor_role: str,
    session_id: str | None,
) -> None:
    n = detail["total_items"]
    st.markdown(f"**{n} item{'s' if n != 1 else ''} require your decision**")
    for row in detail["rows"]:
        with st.expander(
            f"{row.get('item') or row.get('product_name')} · "
            f"{_store_label(row)} · "
            f"{row.get('exception') or 'Needs review'}",
            expanded=False,
        ):
            st.markdown(
                f"**Product:** {row.get('item') or row.get('product_name') or '—'}  \n"
                f"**SKU:** {row.get('sku') or '—'}  \n"
                f"**Store:** {_store_label(row)}  \n"
                f"**Business exception:** {row.get('exception') or '—'}  \n"
                f"**Why it needs review:** "
                f"{row.get('review_reason') or row.get('why_review') or row.get('why') or '—'}  \n"
                f"**Current inventory:** {row.get('on_hand_display') or '—'}  \n"
                f"**7-day demand:** {row.get('demand_7d_display') or '—'}  \n"
                f"**Days of supply:** {row.get('days_of_supply_display') or '—'}  \n"
                f"**Agent quantity:** {row.get('agent_qty_display') or '—'}  \n"
                f"**Confidence:** {row.get('confidence_display') or 'Not scored'}  \n"
                f"**Status:** {row.get('business_status') or '—'}"
            )
            _item_deep_detail(
                row,
                actor=actor,
                role=actor_role,
                session_id=session_id,
                show_decision=True,
            )


def _blocked_vendor_display(row: dict[str, Any]) -> str:
    """Supplier label for blocked detail metadata (presentation only)."""
    rid = row.get("recommendation_id")
    if rid:
        try:
            from services import recommendation_service

            rec = recommendation_service.get_recommendation(str(rid), check_access=False)
            vendor = (rec.get("evidence") or {}).get("vendor")
            if vendor:
                return str(vendor)
        except Exception:  # noqa: BLE001
            pass
    state = str(row.get("supplier_state") or "").strip()
    if state and "could not be verified" not in state.lower():
        if state.lower().startswith("no active supplier"):
            return state
        if len(state) < 80:
            return state
    return "—"


def _blocked_detail_row(label: str, value: str) -> str:
    display = str(value or "—")
    return (
        '<div class="il-blk-detail-row">'
        f'<span class="il-blk-detail-label">{escape(label)}</span>'
        f'<span class="il-blk-detail-value">{escape(display)}</span>'
        "</div>"
    )


def _render_blocked_sales_chart(store_id: str | None, sku: str | None) -> None:
    if not store_id or not sku:
        st.markdown(
            '<p class="il-blk-chart-empty">Not enough recent sales history to chart.</p>',
            unsafe_allow_html=True,
        )
        return
    series = overview_dashboard_service.get_item_sales_series(str(store_id), str(sku), days=14)
    if not series.get("ok"):
        st.markdown(
            f'<p class="il-blk-chart-empty">{escape(series.get("message") or "Not enough recent sales history to chart.")}</p>',
            unsafe_allow_html=True,
        )
        return
    frame = pd.DataFrame(series["points"])
    if frame.empty:
        st.markdown(
            '<p class="il-blk-chart-empty">Not enough recent sales history to chart.</p>',
            unsafe_allow_html=True,
        )
        return
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=frame["date"],
            y=frame["units_sold"],
            mode="lines+markers",
            line={"color": "#1d4ed8", "width": 2},
            marker={"size": 7, "color": "#1d4ed8"},
            hovertemplate="Date: %{x}<br>Units sold: %{y}<extra></extra>",
        )
    )
    fig.update_layout(
        height=220,
        margin={"l": 44, "r": 16, "t": 12, "b": 36},
        xaxis_title="",
        yaxis_title="",
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        font={"color": "#1C2B3A", "size": 12},
        xaxis={
            "showgrid": False,
            "tickfont": {"size": 11, "color": "#6B7280"},
            "linecolor": "#E5E7EB",
        },
        yaxis={
            "showgrid": True,
            "gridcolor": "#EEF1F5",
            "gridwidth": 1,
            "tickfont": {"size": 11, "color": "#6B7280"},
            "linecolor": "#E5E7EB",
            "zeroline": False,
        },
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    st.markdown(
        '<p class="il-blk-chart-caption">Showing last 14 days</p>',
        unsafe_allow_html=True,
    )


def _render_blocked_item_card(row: dict[str, Any]) -> None:
    product = str(row.get("item") or row.get("product_name") or "—")
    sku = str(row.get("sku") or "—")
    store = _store_label(row)
    supplier = _blocked_vendor_display(row)
    blocking_reason = str(row.get("blocking_reason") or "—")
    unblock_action = str(row.get("unblock_action") or "—")
    guardrail = str(row.get("guardrail") or "—")
    supplier_state = str(row.get("supplier_state") or "—")
    confidence = str(row.get("confidence_display") or "Not scored")

    left_details = "".join(
        [
            _blocked_detail_row("Current inventory", str(row.get("on_hand_display") or "—")),
            _blocked_detail_row("7-day demand", str(row.get("demand_7d_display") or "—")),
            _blocked_detail_row("Days of supply", str(row.get("days_of_supply_display") or "—")),
            _blocked_detail_row("Policy / guardrail", guardrail),
        ]
    )
    right_details = "".join(
        [
            _blocked_detail_row(
                "Recommended quantity",
                str(row.get("agent_qty_display") or "—"),
            ),
            _blocked_detail_row("Confidence", confidence),
            _blocked_detail_row("Supplier state", supplier_state),
            _blocked_detail_row("Blocked reason", blocking_reason),
        ]
    )

    st.markdown('<div class="il-blk-stack">', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="il-blk-main-card">
          <div class="il-blk-header">
            <div class="il-blk-title-row">
              <h2 class="il-blk-product">{escape(product)}</h2>
              <span class="il-blk-badge">Blocked</span>
            </div>
            <div class="il-blk-meta">
              SKU: {escape(sku)} &middot; Store: {escape(store)} &middot; Supplier: {escape(supplier)}
            </div>
          </div>
          <div class="il-blk-warning">
            <div class="il-blk-warning-col">
              <div class="il-blk-warning-head is-why">Why this was blocked</div>
              <div class="il-blk-warning-body">{escape(blocking_reason)}</div>
            </div>
            <div class="il-blk-warning-divider" aria-hidden="true"></div>
            <div class="il-blk-warning-col">
              <div class="il-blk-warning-head is-action">What is needed to continue</div>
              <div class="il-blk-warning-body">{escape(unblock_action)}</div>
            </div>
          </div>
        </div>
        <div class="il-blk-card">
          <div class="il-blk-card-title">Details</div>
          <div class="il-blk-details-grid">
            <div class="il-blk-details-col">{left_details}</div>
            <div class="il-blk-details-col">{right_details}</div>
          </div>
        </div>
        <div class="il-blk-card il-blk-card-chart">
          <div class="il-blk-card-title">Recent sales (units)</div>
        """,
        unsafe_allow_html=True,
    )
    _render_blocked_sales_chart(row.get("store_id") or row.get("store"), row.get("sku"))
    st.markdown("</div></div>", unsafe_allow_html=True)


def _render_blocked_rows(detail: dict[str, Any], *, actor: str, actor_role: str) -> None:
    del actor, actor_role  # presentation-only page; data resolved in service layer
    for row in detail["rows"]:
        _render_blocked_item_card(row)


def _auto_detail_row(label: str, value: str) -> str:
    display = str(value or "—")
    return (
        '<div class="il-auto-detail-row">'
        f'<span class="il-auto-detail-label">{escape(label)}</span>'
        f'<span class="il-auto-detail-value">{escape(display)}</span>'
        "</div>"
    )


def _auto_qty_units(value: str | None) -> str:
    text = str(value or "—").strip()
    if text in {"", "—", "Withheld"}:
        return text
    if text.endswith(" units"):
        return text
    return f"{text} units"


def _auto_sales_date_label(raw: str) -> str:
    try:
        return datetime.strptime(str(raw)[:10], "%Y-%m-%d").strftime("%b %d, %Y")
    except (TypeError, ValueError):
        return str(raw)


def _auto_sales_series(store_id: str | None, sku: str | None) -> dict[str, Any]:
    if not store_id or not sku:
        return {"ok": False, "message": "Not enough recent sales history to chart.", "points": []}
    return overview_dashboard_service.get_item_sales_series(str(store_id), str(sku), days=14)


def _auto_sales_widget_key_part(value: str | None) -> str:
    return str(value or "unknown").replace(" ", "_")


def _auto_sales_view_key(key_prefix: str, sku: str | None, store_id: str | None) -> str:
    return (
        f"auto_sales_view_{_auto_sales_widget_key_part(key_prefix)}"
        f"_{_auto_sales_widget_key_part(sku)}"
        f"_{_auto_sales_widget_key_part(store_id)}"
    )


def _auto_sales_graph_key(key_prefix: str, sku: str | None, store_id: str | None) -> str:
    return (
        f"auto_sales_graph_{_auto_sales_widget_key_part(key_prefix)}"
        f"_{_auto_sales_widget_key_part(sku)}"
        f"_{_auto_sales_widget_key_part(store_id)}"
    )


def _render_auto_sales_graph(points: list[dict[str, Any]], *, chart_key: str) -> None:
    frame = pd.DataFrame(points)
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=frame["date"],
            y=frame["units_sold"],
            mode="lines+markers",
            line={"color": "#1d4ed8", "width": 2},
            marker={"size": 7, "color": "#1d4ed8"},
            hovertemplate="Date: %{x}<br>Units sold: %{y}<extra></extra>",
        )
    )
    fig.update_layout(
        height=220,
        margin={"l": 44, "r": 16, "t": 12, "b": 36},
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        font={"color": "#1C2B3A", "size": 12},
        xaxis={
            "showgrid": False,
            "tickfont": {"size": 11, "color": "#6B7280"},
            "linecolor": "#E5E7EB",
        },
        yaxis={
            "showgrid": True,
            "gridcolor": "#EEF1F5",
            "gridwidth": 1,
            "tickfont": {"size": 11, "color": "#6B7280"},
            "linecolor": "#E5E7EB",
            "zeroline": False,
        },
        hovermode="x unified",
    )
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displayModeBar": False},
        key=chart_key,
    )
    st.markdown(
        '<p class="il-auto-chart-caption">Showing last 14 days</p>',
        unsafe_allow_html=True,
    )


def _auto_sales_units_display(value: Any) -> str:
    """Format unit counts for table display only."""
    if value is None or value == "":
        return "—"
    try:
        num = float(value)
        if abs(num - round(num)) < 1e-9:
            return str(int(round(num)))
        return f"{num:.1f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _render_auto_sales_table(points: list[dict[str, Any]]) -> None:
    rows = "".join(
        "<tr>"
        f"<td>{escape(_auto_sales_date_label(str(p.get('date') or '')))}</td>"
        f"<td>{escape(_auto_sales_units_display(p.get('units_sold')))}</td>"
        "</tr>"
        for p in points
    )
    st.markdown(
        '<div class="il-auto-sales-table-wrap">'
        '<table class="il-auto-sales-table">'
        "<thead><tr><th>Date</th><th>Units sold</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
        "</div>",
        unsafe_allow_html=True,
    )


def _render_auto_sales_section(
    store_id: str | None,
    sku: str | None,
    *,
    key_prefix: str,
) -> None:
    series = _auto_sales_series(store_id, sku)
    points = list(series.get("points") or [])
    view_key = _auto_sales_view_key(key_prefix, sku, store_id)
    graph_key = _auto_sales_graph_key(key_prefix, sku, store_id)

    with st.container(border=True, key=f"auto_sales_{key_prefix}"):
        head_left, head_right = st.columns([1.35, 0.65], gap="small")
        with head_left:
            st.markdown(
                '<div class="il-auto-card-title il-auto-sales-heading">Recent sales (units)</div>',
                unsafe_allow_html=True,
            )
        with head_right:
            selected = st.radio(
                "Recent sales view",
                options=["Graph", "Table"],
                horizontal=True,
                label_visibility="collapsed",
                key=view_key,
            )

        if not series.get("ok") or len(points) < 2:
            st.markdown(
                f'<p class="il-auto-chart-empty">{escape(series.get("message") or "Not enough recent sales history to chart.")}</p>',
                unsafe_allow_html=True,
            )
        elif selected == "Table":
            _render_auto_sales_table(points)
        else:
            _render_auto_sales_graph(points, chart_key=graph_key)


def _auto_action_summary_html(row: dict[str, Any]) -> str:
    disposition = row.get("disposition")
    qty = escape(str(row.get("agent_qty_display") or "—"))
    if disposition == "auto_release":
        return f"Released <strong>{qty}</strong> units automatically."
    if disposition == "no_order":
        return "No order was placed — inventory is sufficient."
    label = escape(str(row.get("decision_label") or "Handled automatically"))
    return f"{label}."


def _auto_badge_label(row: dict[str, Any]) -> str:
    return str(row.get("decision_label") or "Handled automatically")


def _render_auto_item_card(row: dict[str, Any]) -> None:
    product = str(row.get("item") or row.get("product_name") or "—")
    sku = str(row.get("sku") or "—")
    store = _store_label(row)
    badge = _auto_badge_label(row)
    badge_class = (
        "il-auto-badge is-neutral"
        if row.get("disposition") == "no_order"
        else "il-auto-badge"
    )
    why = str(row.get("why_safe") or "—")
    ts = row.get("decided_at") or row.get("updated_at") or row.get("created_at") or "—"
    po_ref = (
        row.get("purchase_order_id")
        or row.get("external_order_id")
        or row.get("order_intent_id")
        or "—"
    )
    outcome = str(row.get("business_status") or row.get("policy_outcome") or "—")
    confidence = str(row.get("confidence_display") or "Not scored")
    action_taken = str(row.get("decision_label") or "—")
    qty_detail = _auto_qty_units(str(row.get("agent_qty_display") or "—"))

    left_details = "".join(
        [
            _auto_detail_row("Quantity", qty_detail),
            _auto_detail_row("Confidence", confidence),
            _auto_detail_row("Outcome / status", outcome),
            _auto_detail_row("Action taken", action_taken),
        ]
    )
    right_details = "".join(
        [
            _auto_detail_row("Days of supply", str(row.get("days_of_supply_display") or "—")),
            _auto_detail_row("PO / order reference", str(po_ref)),
            _auto_detail_row("Timestamp", str(ts)),
            _auto_detail_row("Store", store),
        ]
    )
    action_summary = _auto_action_summary_html(row)
    rid = str(row.get("recommendation_id") or row.get("sku") or "item")

    st.markdown('<div class="il-auto-stack">', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="il-auto-main-card">
          <div class="il-auto-header">
            <div class="il-auto-title-row">
              <h2 class="il-auto-product">{escape(product)}</h2>
              <span class="{badge_class}">{escape(badge)}</span>
            </div>
            <div class="il-auto-meta">SKU: {escape(sku)} &middot; Store: {escape(store)}</div>
          </div>
          <div class="il-auto-summary">
            <div class="il-auto-summary-col">
              <div class="il-auto-summary-head is-action">What the agent did</div>
              <div class="il-auto-summary-body">{action_summary}</div>
            </div>
            <div class="il-auto-summary-col is-why-col">
              <div class="il-auto-summary-head is-why">Why</div>
              <div class="il-auto-summary-body">{escape(why)}</div>
            </div>
          </div>
          <div class="il-auto-decision-panel">
            <div class="il-auto-decision-title">Decision details</div>
            <div class="il-auto-details-grid">
              <div class="il-auto-details-col">{left_details}</div>
              <div class="il-auto-details-col">{right_details}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _render_auto_sales_section(
        row.get("store_id") or row.get("store"),
        row.get("sku"),
        key_prefix=rid,
    )
    rec_id = row.get("recommendation_id")
    if rec_id:
        if st.button("View detail", key=f"auto_open_{rec_id}", type="secondary"):
            _open_review(str(rec_id))
    st.markdown("</div>", unsafe_allow_html=True)


def _render_automated_rows(detail: dict[str, Any]) -> None:
    st.markdown('<div class="il-auto-page">', unsafe_allow_html=True)
    for row in detail["rows"]:
        _render_auto_item_card(row)
    st.markdown("</div>", unsafe_allow_html=True)


def _open_delivery_panel(po_id: str) -> None:
    st.session_state["selected_delivery_po"] = str(po_id)
    st.session_state.pop("delivery_details_open", None)
    st.session_state.pop("delivery_modal_open", None)


def _close_delivery_panel() -> None:
    po_id = str(st.session_state.get("selected_delivery_po") or "").strip()
    st.session_state["selected_delivery_po"] = None
    st.session_state.pop("delivery_details_open", None)
    st.session_state.pop("delivery_modal_open", None)
    if po_id:
        st.session_state.pop(f"delivery_invoice_input_{po_id}", None)
        st.session_state.pop(f"delivery_invoice_sync_{po_id}", None)
        st.session_state.pop(f"delivery_invoice_loaded_{po_id}", None)


def _delivery_badge_html(stage: str, label: str) -> str:
    cls = {
        "order_placed": "placed",
        "in_transit": "transit",
        "delivered": "delivered",
    }.get(stage, "placed")
    return (
        f'<span class="il-del-badge il-del-badge--{cls}">'
        f"{escape(label)}</span>"
    )


def _delivery_tracker_html(
    stage: str,
    stage_dates: dict[str, Any] | None,
    *,
    compact: bool = False,
) -> str:
    order = ("order_placed", "in_transit", "delivered")
    labels = {
        "order_placed": "Order Placed",
        "in_transit": "In Transit",
        "delivered": "Delivered",
    }
    dates = stage_dates or {}
    try:
        active_idx = order.index(stage)
    except ValueError:
        active_idx = 0
    steps = []
    for i, key in enumerate(order):
        if stage == "delivered" or i < active_idx:
            state = "done"
        elif i == active_idx:
            state = "active"
        else:
            state = "todo"
        date_text = dates.get(key) or "—"
        steps.append(
            f'<div class="il-del-step is-{state}">'
            f'<div class="il-del-step-marker"><span class="dot"></span></div>'
            f'<div class="il-del-step-lab">{escape(labels[key])}</div>'
            f'<div class="il-del-step-date">{escape(str(date_text))}</div>'
            f"</div>"
        )
    cls = "il-del-tracker compact" if compact else "il-del-tracker"
    return f'<div class="{cls}">{"".join(steps)}</div>'


def _delivery_tile_html(o: dict[str, Any], *, po_id: str, selected: bool) -> str:
    stage = str(o.get("delivery_stage") or "order_placed")
    label = str(o.get("delivery_stage_label") or "Order Placed")
    date_text = str(
        o.get("primary_date_display")
        or o.get("arrival_display")
        or "—"
    )
    selected_cls = " is-selected" if selected else ""
    return (
        f'<div class="il-del-tile{selected_cls}">'
        f'<div class="il-del-tile-main">'
        f'<div class="il-del-tile-left">'
        f'<div class="il-del-po">{escape(str(o.get("po_ref") or po_id))}</div>'
        f'<div class="il-del-product">{escape(str(o.get("product") or "—"))}</div>'
        f"</div>"
        f'<div class="il-del-tile-right">'
        f"{_delivery_badge_html(stage, label)}"
        f'<div class="il-del-date">{escape(date_text)}</div>'
        f'<span class="il-del-chev" aria-hidden="true">›</span>'
        f"</div></div>"
        f"{_delivery_tracker_html(stage, o.get('stage_dates'), compact=True)}"
        f"</div>"
    )


def _render_deliveries_rows(detail: dict[str, Any]) -> None:
    """Active Expected deliveries card list + fixed overlay details panel."""
    from services import purchase_order_service

    groups = detail.get("groups") or {"All": detail.get("rows") or []}
    title_map = {
        "Arriving today": "ARRIVING TODAY",
        "Arriving soon": "COMING SOON",
        "Delayed / at risk": "AT RISK / DELAYED",
        "Other expected": "OTHER EXPECTED",
    }
    selected_po = st.session_state.get("selected_delivery_po")
    if selected_po:
        render_delivery_details_panel(
            str(selected_po),
            purchase_order_service=purchase_order_service,
        )

    selected = str(st.session_state.get("selected_delivery_po") or "").strip()

    for title, rows in groups.items():
        if not rows:
            continue
        st.markdown(f"#### {escape(title_map.get(title, title))}")
        for o in rows:
            po_id = str(
                o.get("purchase_order_id") or o.get("po_ref") or ""
            ).strip()
            if not po_id or po_id == "—":
                continue
            with st.container(key=f"delivery_hit_{po_id}"):
                st.button(
                    " ",
                    key=f"delivery_card_{po_id}",
                    use_container_width=True,
                    type="secondary",
                    on_click=_open_delivery_panel,
                    kwargs={"po_id": po_id},
                )
                st.markdown(
                    _delivery_tile_html(
                        o, po_id=po_id, selected=(po_id == selected)
                    ),
                    unsafe_allow_html=True,
                )


def render_delivery_details_panel(
    selected_po: str,
    *,
    purchase_order_service: Any,
) -> None:
    po_id = str(selected_po).strip()
    detail = overview_dashboard_service.get_delivery_detail(po_id)
    with st.container(key="delivery_side_panel"):
        title_col, close_col = st.columns([10, 1], gap="small")
        with title_col:
            st.markdown(
                '<div class="delivery-details-title">Delivery Details</div>',
                unsafe_allow_html=True,
            )
        with close_col:
            st.button(
                "×",
                key=f"close_delivery_{po_id}",
                help=None,
                on_click=_close_delivery_panel,
            )

        if not detail.get("ok"):
            st.caption(detail.get("message") or "Purchase order not found.")
            return

        stage = str(detail.get("delivery_stage") or "order_placed")
        stage_label = str(detail.get("delivery_stage_label") or "Order Placed")
        st.markdown(
            f'<div class="il-del-panel-hero">'
            f"{_delivery_badge_html(stage, stage_label)}"
            f'<div class="il-del-panel-po">{escape(str(detail.get("po_ref") or po_id))}</div>'
            f'<div class="il-del-panel-product">{escape(str(detail.get("product") or "—"))}</div>'
            f"</div>"
            f"{_delivery_tracker_html(stage, detail.get('stage_dates'))}"
            f'<div class="il-del-panel-grid">'
            f"{_delivery_panel_field('Store', detail.get('store'))}"
            f"{_delivery_panel_field('Quantity', detail.get('quantity_display'))}"
            f"{_delivery_panel_field('Supplier', detail.get('supplier'))}"
            f"{_delivery_panel_field('Unit Price', detail.get('unit_cost_display'))}"
            f"{_delivery_panel_field('SKU', detail.get('sku'))}"
            f"{_delivery_panel_field('Total Cost', detail.get('order_total_display'))}"
            f"{_delivery_panel_field('Order Date', detail.get('order_date'))}"
            f"{_delivery_panel_field('ERP Reference', detail.get('erp_reference'))}"
            f"{_delivery_panel_field('Expected Arrival', detail.get('expected_arrival'))}"
            f"</div>",
            unsafe_allow_html=True,
        )

        st.markdown('<div class="il-del-invoice-sep"></div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="il-del-invoice-lab">Invoice Number</div>',
            unsafe_allow_html=True,
        )
        saved = str(detail.get("invoice_number") or "").strip()
        input_key = f"delivery_invoice_input_{po_id}"
        sync_key = f"delivery_invoice_sync_{po_id}"
        if st.session_state.get(sync_key) != saved:
            st.session_state[input_key] = saved
            st.session_state[sync_key] = saved
        inv_col, btn_col = st.columns([0.72, 0.28])
        with inv_col:
            invoice_value = st.text_input(
                "Invoice Number",
                key=input_key,
                label_visibility="collapsed",
                placeholder="Enter invoice number",
            )
        with btn_col:
            save_clicked = st.button(
                "Save Invoice",
                key=f"delivery_invoice_save_{po_id}",
                use_container_width=True,
                type="primary",
            )
        if save_clicked:
            result = purchase_order_service.save_delivery_invoice(po_id, invoice_value)
            if result.get("ok"):
                st.success("Invoice number saved.")
            else:
                st.warning(result.get("message") or "Unable to save invoice number.")


def _delivery_panel_field(label: str, value: object) -> str:
    return (
        "<div class='il-del-panel-field'>"
        f"<span class='lab'>{escape(str(label))}</span>"
        f"<span class='val'>{escape(str(value if value not in (None, '') else '—'))}</span>"
        "</div>"
    )


def render_summary_detail(
    category: str,
    *,
    actor: str | None = None,
    actor_role: str | None = None,
    session_id: str | None = None,
) -> None:
    """Reusable detail view driven by Overview card category / filter."""
    # Prefer explicit arg; fall back to session filter set by card click.
    raw = (
        category
        or st.session_state.get("overview_detail_filter")
        or st.session_state.get("overview_tile")
        or "needs_review"
    )
    category = str(raw)
    tile_key = CATEGORY_TO_TILE.get(category, category)
    detail = overview_dashboard_service.get_tile_detail(tile_key)

    title = detail.get("title") or category.replace("_", " ").title()
    subtitle = SUBTITLES.get(category) or SUBTITLES.get(tile_key) or ""
    page_heading(title, subtitle)
    _back_overview()

    if detail.get("total_items", 0) == 0:
        _empty_state(category if category in EMPTY_COPY else tile_key)
        return

    if tile_key == "needs_review":
        _render_needs_review_rows(
            detail,
            actor=actor or st.session_state.get("user_id") or "",
            actor_role=actor_role or st.session_state.get("actor_role") or "viewer",
            session_id=session_id,
        )
    elif tile_key == "blocked":
        _render_blocked_rows(
            detail,
            actor=actor or st.session_state.get("user_id") or "",
            actor_role=actor_role or st.session_state.get("actor_role") or "viewer",
        )
    elif tile_key == "automated":
        _render_automated_rows(detail)
    elif tile_key == "deliveries":
        _render_deliveries_rows(detail)


def render_needs_review_detail(
    *,
    actor: str,
    actor_role: str,
    session_id: str | None = None,
) -> None:
    render_summary_detail(
        "needs_review",
        actor=actor,
        actor_role=actor_role,
        session_id=session_id,
    )


def render_blocked_detail(*, actor: str, actor_role: str) -> None:
    render_summary_detail("blocked", actor=actor, actor_role=actor_role)


def render_automated_detail() -> None:
    render_summary_detail("handled_automatically")


def render_deliveries_detail() -> None:
    render_summary_detail("expected_deliveries")
