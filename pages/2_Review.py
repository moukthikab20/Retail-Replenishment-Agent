"""Decision Detail — business-first story from persisted evidence."""

from __future__ import annotations

import streamlit as st

from agent.runner import (
    get_pending_order_flow,
    resume_order_run,
    start_order_agent_after_approval,
)
from services import (
    approval_service,
    audit_service,
    auth_service,
    evidence_service,
    product_service,
    recommendation_service,
)
from services.errors import user_facing_error
from services.perf_timing import perf_step
from ui_common import bootstrap_app
from ui_components import (
    info_grid,
    panel_title,
    role_label,
    status_pill,
)
from ui_decision import render_decision_workflow
from ui_evidence import render_decision_detail
from ui_follow_up import render_follow_up_section


def main() -> None:
    with perf_step("detail.page.bootstrap"):
        user = bootstrap_app(
            "Decision Detail | Retail Replenishment Agent",
            active_nav="todays_queue",
        )
    actor = user["user_id"]
    role = user["role"]
    session_id = user["session_id"]

    recommendation_id = st.session_state.get("nav_recommendation_id") or st.session_state.get(
        "recommendation_id"
    )

    st.markdown('<div class="il-detail-page">', unsafe_allow_html=True)

    if st.button("← Back to decisions", key="dd_back_link"):
        st.switch_page("pages/1_Todays_Queue.py")

    st.markdown(
        """
        <div class="il-dd-page-head">
          <h1>Decision Detail</h1>
          <p>What the agent recommends, why, and what you can do — from persisted evidence only.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if not recommendation_id:
        st.warning("No decision selected. Open an item from Today's Decisions.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    try:
        with perf_step("detail.lookup.recommendation"):
            rec = recommendation_service.get_recommendation(
                recommendation_id,
                user_id=actor,
                role=role,
                check_access=True,
            )
        with perf_step("detail.lookup.evidence"):
            evidence = evidence_service.get_recommendation_evidence(
                recommendation_id,
                rec=rec,
                user_id=actor,
                role=role,
                check_access=True,
            )
    except Exception as exc:  # noqa: BLE001
        st.error(user_facing_error(exc))
        st.markdown("</div>", unsafe_allow_html=True)
        return

    opened_key = f"audit_opened_{recommendation_id}"
    if not st.session_state.get(opened_key):
        try:
            with perf_step("detail.audit.mark_opened"):
                audit_service.mark_recommendation_opened(
                    recommendation_id,
                    actor=actor,
                    actor_role=role,
                    store_id=rec.get("store_id"),
                    sku=rec.get("sku"),
                    run_id=rec.get("run_id"),
                    user_id=actor,
                    session_id=session_id,
                )
            st.session_state[opened_key] = True
        except Exception:  # noqa: BLE001 — opening must not block the detail page
            pass

    # —— Customer story (no recompute) ——
    with perf_step("detail.render.story"):
        render_decision_detail(evidence)

    disposition = rec.get("disposition")
    needs_human_panel = disposition not in {"auto_release"}

    if needs_human_panel:
        st.markdown('<h3 class="il-dd-section-title">Your decision</h3>', unsafe_allow_html=True)
        with perf_step("detail.render.workflow"):
            render_decision_workflow(
                recommendation_id=recommendation_id,
                rec=rec,
                actor=actor,
                role=role,
                session_id=session_id,
            )

    approval_id = st.session_state.get("approval_id")
    required_role = st.session_state.get("required_role")
    if approval_id:
        with st.container(border=True):
            panel_title("Formal approval")
            status = approval_service.check_approval_status(approval_id)

            status_raw = str(status.get("status") or "pending")
            status_labels = {
                "pending": "Pending Approval",
                "approved": "Approved",
                "rejected": "Rejected",
            }
            status_label = status_labels.get(
                status_raw, status_raw.replace("_", " ").title()
            )
            required_role_raw = (
                status.get("required_role") or required_role or "store_manager"
            )
            required_role_display = role_label(required_role_raw)
            approved_qty = status.get("approved_final_quantity")
            approved_qty_display = (
                f"{approved_qty} units"
                if approved_qty is not None
                else "Pending formal approval"
            )

            st.markdown(status_pill(status_raw, status_label), unsafe_allow_html=True)
            info_grid(
                [
                    ("Status", status_label),
                    ("Required Role", required_role_display),
                    (
                        "Agent Recommended Quantity",
                        f"{status.get('agent_recommended_quantity')} units",
                    ),
                    (
                        "Human Proposed Quantity",
                        f"{status.get('human_proposed_quantity')} units",
                    ),
                    ("Approved Final Quantity", approved_qty_display),
                ]
            )

            needed = required_role or status.get("required_role", "store_manager")
            can_approve = auth_service.can_approve(role, needed)
            if status.get("status") == "pending":
                if can_approve:
                    a1, a2 = st.columns(2)
                    with a1:
                        if st.button("Approve Final Order", type="primary"):
                            try:
                                approved = approval_service.decide_approval(
                                    approval_id=approval_id,
                                    decision="approve",
                                    actor=actor,
                                    actor_role=role,
                                )
                                st.session_state["approved_final_quantity"] = (
                                    approved.approved_final_quantity
                                )
                                st.success(
                                    f"Approved final quantity={approved.approved_final_quantity}"
                                )
                                with st.spinner("Starting order flow…"):
                                    order_result = start_order_agent_after_approval(
                                        approval_id=approval_id,
                                        recommendation_id=recommendation_id,
                                        actor=actor,
                                        actor_role=role,
                                        user_id=actor,
                                        session_id=session_id,
                                    )
                                st.session_state["order_flow"] = order_result
                                st.rerun()
                            except Exception as exc:  # noqa: BLE001
                                st.error(user_facing_error(exc))
                    with a2:
                        if st.button("Reject Approval"):
                            try:
                                approval_service.decide_approval(
                                    approval_id=approval_id,
                                    decision="reject",
                                    actor=actor,
                                    actor_role=role,
                                    rejection_reason="Rejected by approver in UI",
                                )
                                st.warning("Approval rejected.")
                            except Exception as exc:  # noqa: BLE001
                                st.error(user_facing_error(exc))
                else:
                    st.info(
                        f"Approve Final Order is available only to "
                        f"{required_role_display} or higher. "
                        f"Your current role is {role_label(role)}."
                    )

    if approval_id and not st.session_state.get("order_flow"):
        reloaded = get_pending_order_flow(approval_id)
        if reloaded is not None:
            st.session_state["order_flow"] = reloaded

    order_flow = st.session_state.get("order_flow")
    if order_flow:
        with st.container(border=True):
            panel_title("Order confirmation")

            if order_flow.get("status") == "paused":
                st.warning(
                    "Order creation is paused for sensitive-tool approval. "
                    "Formal database approval is already recorded."
                )
                if auth_service.can_approve(role, required_role or "category_manager"):
                    r1, r2 = st.columns(2)
                    with r1:
                        if st.button("Approve Sensitive Tool & Resume"):
                            try:
                                resumed = resume_order_run(
                                    run_id=order_flow["run_id"],
                                    approve=True,
                                    actor=actor,
                                    actor_role=role,
                                )
                                st.session_state["order_flow"] = resumed
                                if resumed.get("status") == "error":
                                    st.error(resumed.get("message") or "Resume failed.")
                                st.rerun()
                            except Exception as exc:  # noqa: BLE001
                                st.error(user_facing_error(exc))
                    with r2:
                        if st.button("Reject Sensitive Tool"):
                            try:
                                resumed = resume_order_run(
                                    run_id=order_flow["run_id"],
                                    approve=False,
                                    actor=actor,
                                    actor_role=role,
                                )
                                st.session_state["order_flow"] = resumed
                                st.rerun()
                            except Exception as exc:  # noqa: BLE001
                                st.error(user_facing_error(exc))

            po = order_flow.get("purchase_order")
            if not po and order_flow.get("status") == "completed" and approval_id:
                try:
                    from database.connection import get_session
                    from repositories import purchase_order_repository

                    with get_session() as session:
                        existing = purchase_order_repository.get_purchase_order_by_approval(
                            session, approval_id
                        )
                    if existing:
                        po = existing.model_dump(mode="json")
                except Exception:
                    po = None

            if po:
                st.markdown(
                    f"""
                    <div class="il-success-card">
                        <div class="title">Order prepared successfully</div>
                        <div class="row">Purchase Order ID: <b>{po.get('purchase_order_id')}</b></div>
                        <div class="row">Store: <b>{product_service.store_display_name(po.get('store_id', rec.get('store_id')))}</b></div>
                        <div class="row">SKU: <b>{po.get('sku', rec.get('sku'))}</b></div>
                        <div class="row">Final Quantity: <b>{po.get('approved_final_quantity')}</b></div>
                        <div class="row">Status: <b>{po.get('status')}</b></div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.caption(
                    "Approved orders are prepared for the next purchasing transmission window."
                )
                if st.button("Back to Today's Decisions", type="primary"):
                    for key in (
                        "analysis_decision",
                        "recommendation_id",
                        "nav_recommendation_id",
                        "nav_store_id",
                        "nav_sku",
                        "review_id",
                        "approval_id",
                        "required_role",
                        "approved_final_quantity",
                        "order_flow",
                        "_analysis_context",
                    ):
                        st.session_state.pop(key, None)
                    st.switch_page("pages/1_Todays_Queue.py")

    # —— Advanced / technical (collapsed; not part of the primary story) ——
    with st.container(key="dd_follow_up"):
        with st.expander("Ask a follow-up question", expanded=False):
            render_follow_up_section(
                recommendation_id=recommendation_id,
                user_id=actor,
                session_id=session_id,
                actor=actor,
                actor_role=role,
                agent_recommended_quantity=rec.get("agent_recommended_quantity"),
            )

    st.markdown("</div>", unsafe_allow_html=True)


main()
