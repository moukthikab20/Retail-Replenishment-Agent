"""Overview landing — full-width operational decision dashboard (UI only)."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from services import (
    auth_service,
    disposition_service,
    overview_dashboard_service,
    product_service,
    purchase_order_service,
)
from services.errors import user_facing_error
from ui_components import status_pill


FILTER_CHIPS = (
    ("all", "All"),
    ("needs_review", "Needs review"),
    ("blocked", "Blocked"),
    ("auto_released", "Handled automatically"),
)


def _exception_pill(row: dict[str, Any]) -> str:
    exception = str(row.get("exception") or row.get("why") or "—")
    risk = row.get("risk_level") or ""
    disp = row.get("disposition") or ""
    failed = row.get("failed_rules") or []
    if disp == "blocked" or exception.lower() == "blocked":
        return status_pill("neutral", "Blocked")
    if risk == "stockout" or "stockout" in exception.lower():
        return status_pill("critical", "Stockout risk")
    if risk == "overstock" or "overstock" in exception.lower():
        return status_pill("attention", "Overstock")
    if "confidence" in exception.lower() or "minimum_confidence" in failed:
        return status_pill("warning", "Low confidence")
    return status_pill("attention", exception)


def _exception_cell(row: dict[str, Any]) -> str:
    """Exception label + optional human-intervention reason (policy/guardrail)."""
    pill = _exception_pill(row)
    reason = str(row.get("review_reason") or "").strip()
    if not reason:
        return f'<div class="il-exception-cell">{pill}</div>'
    return (
        '<div class="il-exception-cell">'
        f"{pill}"
        f'<div class="il-review-reason">{escape(reason)}</div>'
        "</div>"
    )


def _dos_bar(row: dict[str, Any]) -> str:
    raw = row.get("days_of_supply")
    display = row.get("days_of_supply_display") or "—"
    try:
        dos = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        dos = None
    if dos is None:
        return f'<span class="il-dos-val">{escape(str(display))}</span>'
    width = max(6, min(100, int(round((dos / 14.0) * 100))))
    risk = row.get("risk_level") or ""
    if risk == "stockout" or dos < 3:
        tone = "crit"
    elif risk == "overstock" or dos > 21:
        tone = "warn"
    elif dos < 7:
        tone = "warn"
    else:
        tone = "ok"
    return (
        '<div class="il-dos">'
        '<div class="il-dos-track">'
        f'<div class="il-dos-fill {tone}" style="width:{width}%"></div>'
        "</div>"
        f'<span class="il-dos-val">{escape(str(display))}</span>'
        "</div>"
    )


def _confidence_cell(row: dict[str, Any]) -> str:
    display = row.get("confidence_display") or "Not scored"
    raw = row.get("confidence")
    try:
        n = float(raw) if raw is not None else None
        if n is not None and n <= 1:
            pct = max(0, min(100, int(round(n * 100))))
        elif n is not None:
            pct = max(0, min(100, int(round(n))))
        else:
            pct = None
    except (TypeError, ValueError):
        pct = None
    if pct is None:
        return f'<span class="il-conf-na">{escape(str(display))}</span>'
    return (
        '<div class="il-conf">'
        f'<div class="il-conf-track"><div class="il-conf-fill" style="width:{pct}%"></div></div>'
        f"<span>{escape(str(display))}</span>"
        "</div>"
    )


def _card_sentence(tile: dict[str, Any]) -> str:
    """One concise business sentence for the card face."""
    return str(tile.get("explanation") or "").strip()


# Card key → detail filter + Streamlit page (existing multipage routes).
TILE_NAV = {
    "needs_review": {
        "filter": "needs_review",
        "route": "pages/11_Needs_Review.py",
    },
    "blocked": {
        "filter": "blocked",
        "route": "pages/12_Blocked.py",
    },
    "automated": {
        "filter": "handled_automatically",
        "route": "pages/13_Handled_Automatically.py",
    },
    "deliveries": {
        "filter": "expected_deliveries",
        "route": "pages/14_Expected_Deliveries.py",
    },
}


def render_summary_card(tile: dict[str, Any]) -> str:
    """Return HTML face for one summary card (navigation is Streamlit switch_page)."""
    accent = tile.get("accent") or "info"
    label = str(tile.get("label") or "Detail")
    return (
        f'<div class="il-dash-tile accent-{escape(accent)}" '
        f'aria-hidden="true">'
        f'<span class="lab">{escape(label)}</span>'
        f'<span class="val">{escape(str(tile.get("value")))}</span>'
        f'<span class="exp">{escape(_card_sentence(tile))}</span>'
        f'<span class="chev" aria-hidden="true">›</span>'
        f"</div>"
    )


def _handle_tile_navigation(tiles: list[dict[str, Any]]) -> None:
    """Honor a leftover overview_tile query param (e.g. after login), then clear it."""
    raw = st.query_params.get("overview_tile")
    if not raw:
        return
    key = raw[0] if isinstance(raw, list) else str(raw)
    try:
        del st.query_params["overview_tile"]
    except Exception:  # noqa: BLE001
        pass
    nav = TILE_NAV.get(key)
    if not nav:
        routes = {str(t.get("key")): t.get("route") for t in tiles}
        route = routes.get(key)
        if not route:
            return
        st.session_state["overview_tile"] = key
        st.session_state["overview_detail_filter"] = key
        st.switch_page(str(route))
        return
    st.session_state["overview_tile"] = key
    st.session_state["overview_detail_filter"] = nav["filter"]
    st.switch_page(nav["route"])


def _navigate_tile(key: str, route: str | None = None) -> None:
    """Set detail category and navigate without dropping the auth session."""
    nav = TILE_NAV.get(key) or {}
    detail_filter = str(nav.get("filter") or key)
    target = str(nav.get("route") or route or "")
    if not target:
        return
    st.session_state["overview_tile"] = key
    # Existing category key used by ui_tile_detail (keep as source of truth).
    st.session_state["overview_detail_filter"] = detail_filter
    # Alias requested by Overview card contract (same value as filter).
    st.session_state["overview_detail_category"] = detail_filter
    st.switch_page(target)


def _render_tiles(tiles: list[dict[str, Any]]) -> None:
    """Four equal cards; each is a real Streamlit button click target.

    Layout (per column):
    1. ``st.button`` — owns height + receives the click (never disabled).
    2. HTML card face — pulled over the button for visuals only, with
       ``pointer-events: none`` so it cannot steal the click.

    Zero-count tiles stay clickable. No visible Open/View buttons.
    """
    _handle_tile_navigation(tiles)
    if not tiles:
        return
    st.markdown(
        '<div class="il-dash-tiles-anchor" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    cols = st.columns(len(tiles), gap="medium")
    for col, tile in zip(cols, tiles):
        key = str(tile.get("key") or "")
        route = str(tile.get("route") or (TILE_NAV.get(key) or {}).get("route") or "")
        with col:
            # Real Streamlit event — label is a single space (tests ban visible titles).
            clicked = st.button(
                " ",
                key=f"dash_tile_nav_{key}",
                use_container_width=True,
                type="secondary",
            )
            # Decorative face only; clicks pass through to the button underneath.
            st.markdown(
                f'<div class="il-dash-tile-wrap">{render_summary_card(tile)}</div>',
                unsafe_allow_html=True,
            )
            if clicked:
                _navigate_tile(key, route)


def _filter_rows(rows: list[dict[str, Any]], chip: str) -> list[dict[str, Any]]:
    if chip == "all":
        return list(rows)
    if chip == "needs_review":
        return [
            r
            for r in rows
            if r.get("disposition") == "human_review" and r.get("open_for_decision")
        ]
    if chip == "blocked":
        return [r for r in rows if r.get("disposition") == "blocked"]
    if chip == "auto_released":
        # Same universe as the Handled automatically card (auto_release + no_order).
        return [
            r
            for r in rows
            if r.get("disposition") in {"auto_release", "no_order"}
        ]
    return list(rows)


def _sort_by_dos(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda r: (
            float(r["days_of_supply"])
            if r.get("days_of_supply") is not None
            else 999.0
        ),
    )


def _row_cells_html(row: dict[str, Any]) -> str:
    name = escape(str(row.get("item") or row.get("product_name") or "—"))
    sku = escape(str(row.get("sku") or ""))
    sku_html = f'<span class="sku">{sku}</span>' if sku else ""
    store = escape(
        str(row.get("store_name") or product_service.store_display_name(row.get("store")))
    )
    return (
        f'<div class="il-item-cell"><span class="name">{name}</span>{sku_html}</div>'
        f'<div class="il-store-cell">{store}</div>'
        f'<div class="il-exception-wrap">{_exception_cell(row)}</div>'
        f'<div class="num il-demand-cell">{escape(str(row.get("demand_7d_display") or "—"))}</div>'
        f'<div class="il-dos-wrap">{_dos_bar(row)}</div>'
        f'<div class="num il-qty">{escape(str(row.get("agent_qty_display") or "—"))}</div>'
        f'<div class="il-conf-wrap">{_confidence_cell(row)}</div>'
        f'<div class="il-status-cell">'
        f"{status_pill(row.get('status_kind') or 'neutral', row.get('business_status') or '—')}"
        f"</div>"
    )


def _render_table_head_html() -> str:
    return (
        "<div class='il-queue-table il-dash-table'>"
        "<div class='il-queue-head'>"
        "<div>Item</div><div>Store</div><div>Exception</div>"
        "<div class='num il-demand-head'>7-Day Demand</div>"
        "<div>Days of Supply</div>"
        "<div class='num'>Agent Qty</div><div>Confidence</div>"
        "<div>Status</div>"
        "</div>"
        "</div>"
    )


def _render_table_html(rows: list[dict[str, Any]]) -> str:
    """Full static table HTML (header + rows) for one continuous card."""
    parts = [
        "<div class='il-queue-table il-dash-table'>",
        "<div class='il-queue-head'>",
        "<div>Item</div><div>Store</div><div>Exception</div>",
        "<div class='num il-demand-head'>7-Day Demand</div>",
        "<div>Days of Supply</div>",
        "<div class='num'>Agent Qty</div><div>Confidence</div>",
        "<div>Status</div>",
        "</div>",
    ]
    for idx, row in enumerate(rows):
        last = " is-last" if idx == len(rows) - 1 else ""
        parts.append(
            f"<div class='il-queue-row il-dash-row{last}'>{_row_cells_html(row)}</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def _navigate_to_row_detail(
    recommendation_id: str,
    sku: str = "",
    store_id: str = "",
) -> None:
    """Session-safe navigation — runs when the row button is clicked."""
    if not recommendation_id:
        return
    st.session_state["nav_recommendation_id"] = recommendation_id
    st.session_state["recommendation_id"] = recommendation_id
    st.session_state["selected_decision_id"] = recommendation_id
    if sku:
        st.session_state["selected_sku"] = sku
    if store_id:
        st.session_state["selected_store_id"] = store_id
    st.switch_page("pages/2_Review.py")


def _open_row_detail(row: dict[str, Any]) -> None:
    rid = row.get("recommendation_id")
    if rid:
        _navigate_to_row_detail(
            str(rid),
            sku=str(row.get("sku") or ""),
            store_id=str(row.get("store_id") or ""),
        )


def _render_table(rows: list[dict[str, Any]]) -> None:
    st.markdown(_render_table_html(rows), unsafe_allow_html=True)


def _zero_state_inner_html(dash: dict[str, Any], *, chip: str) -> str:
    if dash.get("healthy_message") and chip == "all":
        title = dash["healthy_message"]
        detail = "The agent continues to monitor inventory across all locations."
    elif chip != "all":
        title = "No decisions in this filter."
        detail = "Try another filter or wait for the next completed analysis."
    else:
        title = dash.get("empty_table_message") or "No replenishment decisions yet"
        detail = (
            dash.get("empty_table_detail")
            or "Once the agent evaluates your inventory, decisions will appear here."
        )
    return (
        '<div class="il-dash-zero">'
        '<div class="il-dash-zero-icon" aria-hidden="true"></div>'
        f'<div class="il-dash-zero-title">{escape(title)}</div>'
        f'<div class="il-dash-zero-sub">{escape(detail)}</div>'
        "</div>"
    )


def _render_decisions_panel(
    dash: dict[str, Any],
    *,
    visible: list[dict[str, Any]],
    chip: str,
) -> None:
    """One continuous Replenishment Decisions card; whole rows navigate to detail.

    Per-row layout (same proven pattern as summary tiles):
    1. ``st.button`` — real Streamlit click target (never disabled).
    2. HTML row face — pulled over the button for visuals only, with
       ``pointer-events: none`` so it cannot steal clicks or wash out on hover.
    """
    if not visible:
        st.markdown(
            '<div class="il-dash-panel">'
            '<div class="il-dash-panel-head">'
            '<div class="il-dash-panel-title">Replenishment decisions</div>'
            '<div class="il-dash-panel-sub">Sorted by days of supply</div>'
            "</div>"
            '<div class="il-dash-panel-body">'
            f"{_zero_state_inner_html(dash, chip=chip)}"
            "</div></div>",
            unsafe_allow_html=True,
        )
        return

    with st.container(key="dash_decisions_wrap"):
        st.markdown(
            '<div class="il-dash-panel">'
            '<div class="il-dash-panel-head">'
            '<div class="il-dash-panel-title">Replenishment decisions</div>'
            '<div class="il-dash-panel-sub">Sorted by days of supply</div>'
            "</div>"
            '<div class="il-dash-panel-body il-dash-panel-body--table">'
            f"{_render_table_head_html()}"
            "</div></div>",
            unsafe_allow_html=True,
        )
        n = len(visible)
        for idx, row in enumerate(visible):
            rid = str(row.get("recommendation_id") or "")
            if not rid:
                continue
            last = " is-last" if idx == n - 1 else ""
            with st.container(key=f"dash_row_hit_{rid}"):
                clicked = st.button(
                    " ",
                    key=f"dash_row_nav_{rid}",
                    use_container_width=True,
                    type="secondary",
                )
                st.markdown(
                    f"<div class='il-queue-table il-dash-table'>"
                    f"<div class='il-queue-row il-dash-row{last}'>"
                    f"{_row_cells_html(row)}"
                    f"</div></div>",
                    unsafe_allow_html=True,
                )
                if clicked:
                    _navigate_to_row_detail(
                        rid,
                        sku=str(row.get("sku") or ""),
                        store_id=str(row.get("store_id") or ""),
                    )


def render_replenishment_overview(
    *,
    actor: str,
    actor_role: str,
    session_id: str | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    dash = overview_dashboard_service.get_overview_dashboard(
        actor_role=actor_role,
        display_name=display_name or st.session_state.get("actor_display") or actor,
    )

    st.markdown(
        f'<h1 class="il-overview-greeting">{escape(dash["greeting"])}</h1>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<p class="il-overview-lede">{escape(dash["subtitle"])}</p>',
        unsafe_allow_html=True,
    )

    _render_tiles(dash["tiles"])

    if "overview_filter_chip" not in st.session_state:
        st.session_state["overview_filter_chip"] = "all"
    chip = st.session_state["overview_filter_chip"]
    counts = dash["chip_counts"]

    st.markdown(
        '<div class="il-dash-toolbar-anchor" aria-hidden="true"></div>',
        unsafe_allow_html=True,
    )
    # Filters left / actions right — give "Handled automatically" enough width.
    filter_col, action_col = st.columns([2.85, 1.35], gap="small")
    with filter_col:
        st.markdown(
            '<div class="il-dash-filter-group" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        chip_cols = st.columns([0.85, 1.15, 0.9, 1.9], gap="small")
        for idx, (key, label) in enumerate(FILTER_CHIPS):
            with chip_cols[idx]:
                n = counts.get(key, 0)
                if st.button(
                    f"{label} {n}",
                    key=f"dash_chip_{key}",
                    type="primary" if chip == key else "secondary",
                    use_container_width=True,
                ):
                    st.session_state["overview_filter_chip"] = key
                    st.rerun()

    can_decide = auth_service.can_submit_human_review(actor_role)
    can_send = auth_service.can_create_purchase_order(actor_role)
    with action_col:
        st.markdown(
            '<div class="il-dash-action-group" aria-hidden="true"></div>',
            unsafe_allow_html=True,
        )
        action_cols = st.columns(2, gap="small")
        with action_cols[0]:
            if can_decide:
                if st.button(
                    "Approve all within policy",
                    key="dash_bulk_approve",
                    use_container_width=True,
                ):
                    try:
                        run = dash.get("run") or {}
                        bulk = disposition_service.approve_all_within_policy(
                            actor=actor,
                            actor_role=actor_role,
                            run_id=(run or {}).get("run_id"),
                            user_id=actor,
                            session_id=session_id,
                        )
                        st.session_state["dash_bulk_result"] = bulk
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(user_facing_error(exc))
        with action_cols[1]:
            if can_send:
                if st.button(
                    "Send approved to ERP",
                    type="primary",
                    key="dash_send_erp",
                    use_container_width=True,
                ):
                    try:
                        result = purchase_order_service.send_approved_to_erp(
                            actor=actor,
                            actor_role=actor_role,
                            user_id=actor,
                            session_id=session_id,
                        )
                        st.session_state["dash_erp_result"] = result
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(user_facing_error(exc))

    if "dash_bulk_result" in st.session_state:
        bulk = st.session_state.pop("dash_bulk_result")
        st.success(
            f"Bulk complete — approved {bulk.get('approved', 0)}, "
            f"skipped {bulk.get('skipped', 0)}, failed {bulk.get('failed', 0)}."
        )
    if "dash_erp_result" in st.session_state:
        result = st.session_state.pop("dash_erp_result")
        st.success(
            f"Sent {result.get('transmitted', 0)} order(s). "
            f"Failed {result.get('transmission_failed', 0)}."
        )

    chip = st.session_state["overview_filter_chip"]
    visible = _sort_by_dos(_filter_rows(dash["all_rows"], chip))

    _render_decisions_panel(dash, visible=visible, chip=chip)

    return dash
