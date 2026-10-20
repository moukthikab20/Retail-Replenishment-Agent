"""Approved + Purchase Orders — business purchasing lifecycle (presentation only)."""

from __future__ import annotations

from html import escape
from typing import Any

import streamlit as st

from config import ERP_AUTO_TRANSMIT
from services import auth_service, product_service, purchase_order_service, queue_service
from services.errors import user_facing_error
from services.order_lifecycle_states import format_lifecycle_label, normalize_status
from ui_components import (
    AGENT_LANGUAGE,
    compact_kpi_row,
    empty_state,
    page_heading,
    panel_title,
    section_heading,
    status_pill,
)


_ORDERS_TABLE_STATUS_DISPLAY = {
    "Accepted by Purchasing System": "Accepted",
}


def _orders_table_status_label(label: str) -> str:
    text = str(label or "")
    return _ORDERS_TABLE_STATUS_DISPLAY.get(text, text)


def _status_kind(status: str | None) -> str:
    canon = normalize_status(status)
    return {
        "queued_for_erp": "attention",
        "transmitting": "progress",
        "erp_acknowledged": "success",
        "completed": "success",
        "transmission_failed": "critical",
        "retry_pending": "attention",
        "erp_rejected": "critical",
        "cancelled": "neutral",
    }.get(canon, "neutral")


def manual_send_visibility(
    *,
    can_send: bool,
    auto_transmit: bool,
    ready_count: int,
    attention_count: int,
) -> dict[str, Any]:
    """
    When to surface manual send in the UI.
    Queue != transmit remains a backend concern; this only controls prominence.
    """
    if not can_send:
        return {
            "show": False,
            "mode": "hidden",
            "label": "",
            "section": "",
            "primary": False,
        }
    if not auto_transmit:
        return {
            "show": True,
            "mode": "demo",
            "label": "Send now",
            "section": "Demo action",
            "primary": ready_count > 0 or attention_count > 0,
        }
    if attention_count > 0:
        return {
            "show": True,
            "mode": "intervention",
            "label": "Send now",
            "section": "Action needed",
            "primary": True,
        }
    if ready_count > 0:
        return {
            "show": True,
            "mode": "override",
            "label": "Send now",
            "section": "Manual override",
            "primary": False,
        }
    return {
        "show": False,
        "mode": "scheduled",
        "label": "",
        "section": "",
        "primary": False,
    }


def render_approved_page() -> None:
    payload = queue_service.get_approved_today()
    run = payload.get("run")
    summary = payload["summary"]
    page_heading(
        "Approved for Purchase",
        summary.get("story")
        or "Approved replenishment decisions ready for purchasing.",
    )

    next_tx = str(summary.get("next_transmission") or "—")
    if " — " in next_tx:
        next_primary, next_secondary = next_tx.split(" — ", 1)
        next_kpi: dict[str, Any] = {
            "label": "Next transmission",
            "value": next_primary,
            "sub": next_secondary,
            "text_value": True,
        }
    else:
        next_kpi = {
            "label": "Next transmission",
            "value": next_tx,
            "text_value": True,
        }

    compact_kpi_row(
        [
            {
                "label": "Approved today",
                "value": summary.get("approved_today", summary["total"]),
                "accent": summary["total"] > 0,
            },
            {
                "label": AGENT_LANGUAGE["handled_automatically"],
                "value": summary["auto_released"],
            },
            {
                "label": "Approved by people",
                "value": summary["human_approved"],
            },
            {
                "label": "Total value",
                "value": summary["order_value_display"],
            },
            next_kpi,
        ],
        columns=5,
        column_template="1fr 1fr 1fr 1fr 1.18fr",
        row_class="il-approved-kpi-row",
    )

    rows = payload["rows"]
    if not run or not rows:
        empty_state(
            title="No approved items yet",
            explanation=(
                "Orders are created after replenishment decisions are approved."
            ),
            next_step="Review today's decisions to approve exceptions.",
            primary_label="Review today's decisions" if run else None,
            primary_action=(
                (lambda: st.switch_page("pages/1_Todays_Queue.py")) if run else None
            ),
            key_prefix="approved_empty",
        )
        return

    with st.container(border=True, key="approved_decisions_panel"):
        section_heading("Approved Decisions")
        header = (
            "<div class='il-queue-table il-approved-table'>"
            "<div class='il-queue-head'>"
            "<div>Store</div><div>Product</div>"
            "<div class='num'>Quantity</div><div class='num'>Value</div>"
            "<div>Approval source</div><div>Approved at</div><div>Next step</div>"
            "</div>"
        )
        parts = [header]
        for row in rows:
            store = row.get("store_name") or product_service.store_display_name(row.get("store_id"))
            qty = row.get("final_quantity")
            qty_display = "—" if qty is None else str(qty)
            product = row.get("product") or row.get("item") or row.get("sku") or "—"
            approval = str(row.get("approval_source") or row.get("source") or "—")
            next_step = str(row.get("next_step") or "—")
            parts.append(
                "<div class='il-queue-row'>"
                f"<div>{escape(str(store))}</div>"
                f"<div>{escape(str(product))}</div>"
                f"<div class='num'>{escape(qty_display)}</div>"
                f"<div class='num'>{escape(str(row['order_value_display']))}</div>"
                f"<div class='il-approved-nowrap'>{escape(approval)}</div>"
                f"<div>{escape(str(row.get('approved_at_display') or row.get('release_time_display') or '—'))}</div>"
                f"<div class='il-approved-nowrap'>{escape(next_step)}</div>"
                "</div>"
            )
        parts.append("</div>")
        st.markdown("".join(parts), unsafe_allow_html=True)


_ORDERS_COL_SPEC = [1.45, 1.45, 1.25, 0.55, 0.65, 1.45, 1.35, 1.15, 1.05]
_ORDERS_HEADERS = (
    "PO",
    "Vendor",
    "Store",
    "Items",
    "Value",
    "Status",
    "Expected/Submitted",
    "Approved by",
    "Action",
)


def _select_purchase_order(po_id: str) -> None:
    st.session_state["selected_po_id"] = po_id
    st.session_state["orders_po_dialog"] = po_id


def _dismiss_po_dialog() -> None:
    st.session_state.pop("orders_po_dialog", None)


def _money_display(value: Any) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _render_po_detail_body(po_id: str) -> None:
    """Render selected PO metadata + line items (modal or panel body)."""
    payload = purchase_order_service.get_purchase_order_status(po_id)
    if not payload or payload.get("status") == "not_found":
        st.caption("Purchase order not found.")
        return

    status = payload.get("order_status") or payload.get("status") or "queued_for_erp"
    status_label = format_lifecycle_label(str(status))
    amount = payload.get("amount")
    lines = list(payload.get("lines") or [])
    if amount is None and lines:
        amount = sum(
            float(ln.get("line_amount") or 0)
            for ln in lines
            if ln.get("line_amount") is not None
        )
    vendor = payload.get("vendor") or "—"
    store = product_service.store_display_name(payload.get("store_id"))
    approved_by = payload.get("approved_by") or "—"
    erp_ref = payload.get("external_order_id") or payload.get("erp_reference") or "—"

    if not lines and payload.get("sku"):
        lines = [
            {
                "sku": payload.get("sku"),
                "product_name": payload.get("product_name") or payload.get("sku"),
                "quantity": payload.get("approved_final_quantity"),
                "unit_cost": payload.get("unit_cost"),
                "line_amount": amount,
            }
        ]

    parts = [
        '<div class="modal-inner modal-content il-po-modal-content">',
        f'<div class="il-po-detail-id">{escape(str(po_id))}</div>',
        "<div class='metadata-grid il-po-detail-meta'>",
        f"<div><span class='lab'>Supplier</span><span class='val'>{escape(str(vendor))}</span></div>",
        f"<div><span class='lab'>Store</span><span class='val'>{escape(str(store))}</span></div>",
        f"<div class='status-cell'><span class='lab'>Status</span>"
        f"<span class='val'>{status_pill(_status_kind(str(status)), status_label)}</span></div>",
        f"<div><span class='lab'>ERP state</span><span class='val'>{escape(str(erp_ref))}</span></div>",
        f"<div><span class='lab'>Approval source</span><span class='val'>{escape(str(approved_by))}</span></div>",
        f"<div><span class='lab'>Order total</span><span class='val'>{escape(_money_display(amount))}</span></div>",
        "</div>",
        '<h3 class="il-po-detail-lines-title">Line Items</h3>',
        "<div class='il-queue-table il-po-lines-table'>",
        "<div class='il-queue-head line-items-grid'>",
        "<div>SKU</div><div>Item</div><div class='num'>Qty</div>",
        "<div class='num'>Unit Cost</div><div class='num'>Line Total</div>",
        "</div>",
    ]
    if lines:
        for ln in lines:
            qty = ln.get("quantity") or ln.get("qty") or payload.get("approved_final_quantity")
            unit = ln.get("unit_cost")
            line_total = ln.get("line_amount")
            if line_total is None and unit is not None and qty is not None:
                try:
                    line_total = float(unit) * float(qty)
                except (TypeError, ValueError):
                    line_total = None
            item = ln.get("product_name") or ln.get("item") or ln.get("sku") or "—"
            parts.append(
                "<div class='il-queue-row line-items-grid'>"
                f"<div>{escape(str(ln.get('sku') or payload.get('sku') or '—'))}</div>"
                f"<div>{escape(str(item))}</div>"
                f"<div class='num'>{escape(str(qty if qty is not None else '—'))}</div>"
                f"<div class='num'>{escape(_money_display(unit) if unit is not None else '—')}</div>"
                f"<div class='num'>{escape(_money_display(line_total) if line_total is not None else '—')}</div>"
                "</div>"
            )
    else:
        parts.append(
            "<div class='il-queue-row line-items-grid'><div>—</div><div>No line items recorded</div>"
            "<div class='num'>—</div><div class='num'>—</div><div class='num'>—</div></div>"
        )
    parts.append("</div></div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


@st.dialog("Purchase Order Details", width="large", on_dismiss=_dismiss_po_dialog)
def _po_details_dialog(po_id: str) -> None:
    _render_po_detail_body(po_id)


def _orders_row_values(po: dict[str, Any]) -> list[str]:
    status = po.get("order_status") or po.get("status") or "queued_for_erp"
    status_label = po.get("order_status_label") or format_lifecycle_label(str(status))
    status_label = _orders_table_status_label(str(status_label))
    value = po.get("value") if po.get("value") is not None else po.get("amount")
    failure = po.get("failure") or {}
    action = po.get("next_step") or "—"
    if failure.get("kind") in {"rejection", "failed", "retry"}:
        action = failure.get("title") or action
    return [
        str(po.get("purchase_order_id") or ""),
        str(po.get("vendor") or "—"),
        product_service.store_display_name(po.get("store_id")),
        str(po.get("items_count") or po.get("lines_count") or "—"),
        _money_display(value),
        str(status_label),
        str(po.get("expected_or_submitted") or "—"),
        str(po.get("approved_by_display") or po.get("approved_by") or "—"),
        str(action),
    ]


def _render_orders_table(orders: list[dict[str, Any]], selected_po_id: str | None) -> None:
    """In-flow table: every row occupies document space; click any cell to select."""
    if selected_po_id:
        safe = (
            str(selected_po_id)
            .replace("\\", "\\\\")
            .replace('"', '\\"')
        )
        # One continuous selected row block — never per-cell borders/backgrounds.
        st.markdown(
            "<style>"
            f'div[class*="st-key-orders_row_{safe}"],'
            f'div[class*="st-key-orders_row_{safe}"].selected-po-row{{'
            "background:#EAF2FA!important;"
            "border:1px solid #BFD0E2!important;"
            "border-radius:8px!important;"
            "box-shadow:none!important;"
            "margin:2px 0!important;}"
            f'div[class*="st-key-orders_row_{safe}"] > *,'
            f'div[class*="st-key-orders_row_{safe}"] [data-testid="stHorizontalBlock"],'
            f'div[class*="st-key-orders_row_{safe}"] [data-testid="column"],'
            f'div[class*="st-key-orders_row_{safe}"] [data-testid="stVerticalBlock"],'
            f'div[class*="st-key-orders_row_{safe}"] [data-testid="stElementContainer"],'
            f'div[class*="st-key-orders_row_{safe}"] .il-orders-status-cell{{'
            "background:transparent!important;"
            "border:none!important;"
            "border-left:none!important;"
            "border-right:none!important;"
            "box-shadow:none!important;"
            "outline:none!important;}"
            f'div[class*="st-key-orders_row_{safe}"] [data-testid="stHorizontalBlock"]{{'
            "border-bottom:none!important;}"
            f'div[class*="st-key-orders_row_{safe}"] [class*="st-key-orders_sel_"]'
            " div[data-testid='stButton'] button,"
            f'div[class*="st-key-orders_row_{safe}"] [class*="st-key-orders_sel_"]'
            " div[data-testid='stButton'] button:hover,"
            f'div[class*="st-key-orders_row_{safe}"] [class*="st-key-orders_sel_"]'
            " div[data-testid='stButton'] button:focus{{"
            "background:transparent!important;"
            "border:none!important;"
            "box-shadow:none!important;"
            "outline:none!important;"
            "border-radius:0!important;}"
            "</style>",
            unsafe_allow_html=True,
        )
    with st.container(key="orders_table_grid"):
        head_cols = st.columns(_ORDERS_COL_SPEC, gap="small")
        for col, label in zip(head_cols, _ORDERS_HEADERS):
            with col:
                st.markdown(
                    f"<div class='il-orders-head-cell'>{escape(label)}</div>",
                    unsafe_allow_html=True,
                )
        for po in orders:
            po_id = str(po.get("purchase_order_id") or "")
            if not po_id:
                continue
            values = _orders_row_values(po)
            status = po.get("order_status") or po.get("status") or "queued_for_erp"
            status_label = values[5]
            suffixes = (
                "po",
                "vendor",
                "store",
                "items",
                "value",
                "status",
                "expected",
                "approved",
                "action",
            )
            with st.container(key=f"orders_row_{po_id}"):
                row_cols = st.columns(_ORDERS_COL_SPEC, gap="small")
                for idx, (col, value) in enumerate(zip(row_cols, values)):
                    with col:
                        if idx == 5:
                            pill = status_pill(_status_kind(str(status)), status_label)
                            st.markdown(
                                f"<div class='il-orders-status-cell'>{pill}</div>",
                                unsafe_allow_html=True,
                            )
                            continue
                        st.button(
                            value,
                            key=f"orders_sel_{po_id}_{suffixes[idx]}",
                            use_container_width=True,
                            type="secondary",
                            on_click=_select_purchase_order,
                            kwargs={"po_id": po_id},
                        )


def render_orders_page(user: dict[str, Any]) -> None:
    actor = user["user_id"]
    role = user["role"]
    session_id = user["session_id"]

    workbench = purchase_order_service.get_orders_workbench()
    summary = workbench["summary"]
    can_send = auth_service.can_create_purchase_order(role)
    auto_transmit = bool(summary.get("auto_transmit", ERP_AUTO_TRANSMIT))
    visibility = manual_send_visibility(
        can_send=can_send,
        auto_transmit=auto_transmit,
        ready_count=int(summary.get("ready_to_send") or 0),
        attention_count=int(summary.get("attention_needed") or 0),
    )

    page_heading(
        "Purchase Orders",
        workbench.get("subtitle") or workbench.get("story") or "",
    )
    st.caption(workbench.get("story") or "")

    compact_kpi_row(
        [
            {
                "label": AGENT_LANGUAGE["ready_to_send"],
                "value": summary.get("ready_to_send", 0),
                "accent": summary.get("ready_to_send", 0) > 0,
            },
            {
                "label": "Sending",
                "value": summary.get("sending", 0),
            },
            {
                "label": AGENT_LANGUAGE["accepted"],
                "value": summary.get("accepted", 0),
            },
            {
                "label": "Attention needed",
                "value": summary.get("attention_needed", 0),
                "accent": summary.get("attention_needed", 0) > 0,
            },
        ],
        columns=4,
    )

    if visibility["show"]:
        with st.container(border=True):
            panel_title(visibility["section"])
            if visibility["mode"] == "demo":
                st.caption(
                    "Demo environment — production purchasing schedule is not active. "
                    "Queueing an approved order is separate from sending it."
                )
            elif visibility["mode"] == "override":
                st.caption(
                    "Orders will send on the purchasing schedule. "
                    "Use this only for a deliberate manual override."
                )
            elif visibility["mode"] == "intervention":
                st.caption(
                    "Some orders need attention. An authorized user may send or retry."
                )
            send = st.button(
                visibility["label"],
                type="primary" if visibility["primary"] else "secondary",
                use_container_width=False,
                disabled=not can_send,
                key="orders_manual_send",
            )
            if send:
                try:
                    result = purchase_order_service.send_approved_to_erp(
                        actor=actor,
                        actor_role=role,
                        user_id=actor,
                        session_id=session_id,
                    )
                    st.session_state["erp_cutoff_result"] = result
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(user_facing_error(exc))
    elif auto_transmit:
        empty_state(
            title="Sending on schedule",
            explanation=(
                "The agent prepares approved orders and sends them according to "
                "the configured purchasing schedule."
            ),
            next_step="No manual send is required.",
            key_prefix="orders_scheduled",
            bordered=True,
        )
    elif not can_send:
        st.caption("Your role can view orders but cannot send to the purchasing system.")

    if "erp_cutoff_result" in st.session_state:
        result = st.session_state.pop("erp_cutoff_result")
        st.success(
            f"Sent {result['transmitted']} order(s). "
            f"Created {result['purchase_orders_created']}, "
            f"failed {result['transmission_failed']}, "
            f"skipped {result['already_sent_skipped']}."
        )

    order_flow = st.session_state.get("order_flow") or {}
    session_po = order_flow.get("purchase_order")
    if session_po:
        with st.container(border=True):
            panel_title("Session confirmation")
            status = session_po.get("order_status") or session_po.get("status")
            st.markdown(
                f"""
                <div class="il-success-card">
                    <div class="title">Order created in this session</div>
                    <div class="row">Purchase Order: <b>{escape(str(session_po.get('purchase_order_id')))}</b></div>
                    <div class="row">Store: <b>{escape(product_service.store_display_name(session_po.get('store_id')))}</b></div>
                    <div class="row">SKU: <b>{escape(str(session_po.get('sku')))}</b></div>
                    <div class="row">Quantity: <b>{escape(str(session_po.get('approved_final_quantity')))}</b></div>
                    <div class="row">Status: <b>{escape(format_lifecycle_label(status))}</b></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    orders = workbench["orders"]
    if not orders:
        empty_state(
            title="No purchase orders yet",
            explanation=(
                "Orders are created after replenishment decisions are approved."
            ),
            next_step="Review today's decisions to approve exceptions.",
            primary_label="Review today's decisions",
            primary_action=lambda: st.switch_page("pages/1_Todays_Queue.py"),
            key_prefix="orders_empty",
        )
        return

    selected_po_id = st.session_state.get("selected_po_id")
    known_ids = {str(o.get("purchase_order_id") or "") for o in orders}
    if selected_po_id and selected_po_id not in known_ids:
        selected_po_id = None
        st.session_state.pop("selected_po_id", None)

    highlight_po_id = (
        selected_po_id if st.session_state.get("orders_po_dialog") else None
    )
    with st.container(border=True, key="il_orders_card"):
        panel_title("Orders")
        _render_orders_table(orders, highlight_po_id)

        attention_orders = [
            o
            for o in orders
            if (o.get("failure") or {}).get("kind") in {"rejection", "failed", "retry"}
        ]
        if attention_orders:
            with st.expander("Orders needing attention", expanded=True):
                for o in attention_orders:
                    fail = o.get("failure") or {}
                    st.markdown(
                        f"**{escape(str(o.get('purchase_order_id')))}** — "
                        f"{escape(str(fail.get('title') or ''))}"
                    )
                    st.caption(fail.get("message") or "")

    dialog_po = st.session_state.get("orders_po_dialog")
    if dialog_po:
        _po_details_dialog(str(dialog_po))

    is_admin = role in {"administrator", "admin"}
    with st.expander("Advanced technical status", expanded=False):
        if is_admin:
            st.caption(
                f"Purchasing connection: {workbench.get('purchasing_connection')} · "
                f"Outbox pending={workbench['outbox_pending']} · "
                f"failed={workbench['outbox_failed']}"
            )
        else:
            st.caption(
                f"Purchasing connection: {workbench.get('purchasing_connection')}"
            )
        st.dataframe(
            [
                {
                    "Order ID": o.get("purchase_order_id"),
                    "Order Intent": o.get("order_intent_id"),
                    "SKU": o.get("sku"),
                    "Store": product_service.store_display_name(o.get("store_id")),
                    "Status (raw)": o.get("order_status"),
                    "Status": o.get("order_status_label"),
                    "Attempts": o.get("attempt_count"),
                    "External Order ID": o.get("external_order_id"),
                    "Last Failure": o.get("last_failure"),
                    "Next retry": o.get("next_retry_at"),
                }
                for o in orders
            ],
            use_container_width=True,
            hide_index=True,
        )
