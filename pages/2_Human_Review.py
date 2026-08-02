"""Page 2 — Human review, approval, and mock purchase order."""

from __future__ import annotations

import streamlit as st

from agent.runner import resume_order_flow, start_order_agent_after_approval
from services import (
    approval_service,
    auth_service,
    human_review_service,
    product_service,
    recommendation_service,
)
from services.errors import user_facing_error
from ui_common import (
    bootstrap_app,
    render_card_header,
    render_footer,
    render_header,
    risk_badge_html,
)


def main() -> None:
    user = bootstrap_app("Human Review | Retail Replenishment Agent")
    render_header("Human Review · Override controls · Formal approval")
    actor = user["user_id"]
    role = user["role"]
    session_id = user["session_id"]

    recommendation_id = st.session_state.get("nav_recommendation_id") or st.session_state.get(
        "recommendation_id"
    )
    if not recommendation_id:
        st.warning("No recommendation selected. Return to Analysis and continue from there.")
        if st.button("Back to Analysis"):
            st.switch_page("pages/1_Analysis.py")
        render_footer()
        return

    try:
        rec = recommendation_service.get_recommendation(
            recommendation_id,
            user_id=actor,
            role=role,
            check_access=True,
        )
    except Exception as exc:  # noqa: BLE001
        st.error(user_facing_error(exc))
        render_footer()
        return

    product = product_service.get_product_details(rec["sku"])

    st.markdown('<div class="card">', unsafe_allow_html=True)
    render_card_header("Recommendation Context")
    st.markdown('<div class="card-body">', unsafe_allow_html=True)
    st.markdown(
        f'<div class="chip-row">{risk_badge_html(rec["risk_level"])}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="stat-grid">
            <div class="stat-callout"><div class="stat-label">Store</div><div class="stat-value">{rec['store_id']}</div></div>
            <div class="stat-callout"><div class="stat-label">SKU</div><div class="stat-value">{rec['sku']}</div></div>
            <div class="stat-callout"><div class="stat-label">Agent Recommended Qty</div><div class="stat-value">{rec['agent_recommended_quantity']}</div></div>
            <div class="stat-callout"><div class="stat-label">Forecast</div><div class="stat-value">{rec['forecast_units']}</div></div>
            <div class="stat-callout"><div class="stat-label">Current Risk</div><div class="stat-value">{rec['risk_level']}</div></div>
            <div class="stat-callout"><div class="stat-label">Case Pack</div><div class="stat-value">{rec['case_pack']}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div></div>", unsafe_allow_html=True)

    st.markdown('<div class="card">', unsafe_allow_html=True)
    render_card_header("Human Quantity Decision")
    st.markdown('<div class="card-body">', unsafe_allow_html=True)

    choice_label = st.radio(
        "Choice",
        options=["Use recommended quantity", "Enter a different quantity"],
        horizontal=True,
    )
    choice = "use_agent" if choice_label.startswith("Use") else "manual"

    human_qty = rec["agent_recommended_quantity"]
    override_reason = None
    if choice == "manual":
        human_qty = st.number_input(
            "Manual replenishment quantity",
            min_value=0,
            step=1,
            value=int(rec["agent_recommended_quantity"]),
        )
        override_reason = st.text_area("Override reason", help="Required when quantity differs.")

    preview = human_review_service.preview_human_review(
        recommendation_id=recommendation_id,
        choice=choice,
        human_proposed_quantity=int(human_qty) if choice == "manual" else None,
        override_reason=override_reason,
    )

    if choice == "manual":
        st.markdown(
            f"""
            <p class="secondary-text">
            Nearest valid case-pack quantities:
            lower=<strong>{preview.get('nearest_lower_case_pack')}</strong>,
            higher=<strong>{preview.get('nearest_higher_case_pack')}</strong>
            </p>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        f"""
        <div class="stat-grid">
            <div class="stat-callout"><div class="stat-label">Difference Units</div><div class="stat-value">{preview.get('difference_units')}</div></div>
            <div class="stat-callout"><div class="stat-label">Difference %</div><div class="stat-value">{preview.get('difference_percent')}</div></div>
            <div class="stat-callout"><div class="stat-label">Projected DOS</div><div class="stat-value">{preview.get('projected_days_of_supply')}</div></div>
            <div class="stat-callout"><div class="stat-label">Projected Risk</div><div class="stat-value">{preview.get('projected_risk')}</div></div>
            <div class="stat-callout"><div class="stat-label">Approval Level</div><div class="stat-value">{preview.get('approval_level')}</div></div>
            <div class="stat-callout"><div class="stat-label">Escalation</div><div class="stat-value">{preview.get('requires_escalation')}</div></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    for message in preview.get("validation_messages", []):
        if preview.get("valid"):
            st.info(message)
        else:
            st.error(message)

    # Preserve three quantities visibly
    st.markdown(
        f"""
        <div class="recommendation-callout">
            <h4>Quantity separation (never overwritten)</h4>
            <p class="secondary-text">
                agent_recommended_quantity = <strong>{rec['agent_recommended_quantity']}</strong><br>
                human_proposed_quantity = <strong>{preview.get('human_proposed_quantity')}</strong><br>
                approved_final_quantity = <strong>{st.session_state.get('approved_final_quantity', '— (pending formal approval)')}</strong>
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    can_submit = auth_service.can_submit_human_review(role)
    if not can_submit:
        st.info("Your role can view this recommendation but cannot submit or reject it.")

    c1, c2, c3 = st.columns(3)
    with c1:
        submit = st.button(
            "Submit for Approval",
            type="primary",
            use_container_width=True,
            disabled=not can_submit,
        )
    with c2:
        reject = st.button(
            "Reject Recommendation",
            type="secondary",
            use_container_width=True,
            disabled=not can_submit,
        )
    with c3:
        if st.button("Back to Analysis", use_container_width=True):
            st.switch_page("pages/1_Analysis.py")

    if submit:
        try:
            review = human_review_service.submit_human_review(
                recommendation_id=recommendation_id,
                choice=choice,
                submitted_by=actor,
                human_proposed_quantity=int(human_qty) if choice == "manual" else None,
                override_reason=override_reason,
                actor_role=role,
                user_id=actor,
                session_id=session_id,
            )
            approval = approval_service.create_approval_request(
                review_id=review.review_id,
                actor=actor,
                actor_role=role,
                user_id=actor,
                session_id=session_id,
            )
            st.session_state["review_id"] = review.review_id
            st.session_state["approval_id"] = approval.approval_id
            st.session_state["required_role"] = approval.required_role
            st.success(
                f"Submitted. Review {review.review_id}, Approval {approval.approval_id}, "
                f"required role={approval.required_role}"
            )
        except Exception as exc:  # noqa: BLE001
            st.error(user_facing_error(exc))

    if reject:
        try:
            human_review_service.reject_recommendation(
                recommendation_id=recommendation_id,
                actor=actor,
                actor_role=role,
                reason="Rejected on Human Review page",
            )
            st.warning("Recommendation rejected. No purchase order will be created.")
        except Exception as exc:  # noqa: BLE001
            st.error(user_facing_error(exc))

    st.markdown("</div></div>", unsafe_allow_html=True)

    approval_id = st.session_state.get("approval_id")
    required_role = st.session_state.get("required_role")
    if approval_id:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        render_card_header("Formal Approval (role-gated)")
        st.markdown('<div class="card-body">', unsafe_allow_html=True)
        status = approval_service.check_approval_status(approval_id)
        st.write(
            {
                "approval_id": status.get("approval_id"),
                "status": status.get("status"),
                "required_role": status.get("required_role"),
                "agent_recommended_quantity": status.get("agent_recommended_quantity"),
                "human_proposed_quantity": status.get("human_proposed_quantity"),
                "approved_final_quantity": status.get("approved_final_quantity"),
            }
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
                    f"Approve Final Order hidden — current role `{role}` does not satisfy "
                    f"required role `{required_role}`."
                )
        st.markdown("</div></div>", unsafe_allow_html=True)

    order_flow = st.session_state.get("order_flow")
    if order_flow:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        render_card_header("Order Flow / HITL")
        st.markdown('<div class="card-body">', unsafe_allow_html=True)
        st.json(order_flow)

        if order_flow.get("status") == "paused":
            st.warning(
                f"Sensitive tool paused: {order_flow.get('pending_tool')} "
                f"args={order_flow.get('pending_args')}"
            )
            if auth_service.can_approve(role, required_role or "category_manager"):
                r1, r2 = st.columns(2)
                with r1:
                    if st.button("Approve Sensitive Tool & Resume"):
                        resumed = resume_order_flow(
                            run_id=order_flow["run_id"],
                            approve=True,
                            actor=actor,
                            actor_role=role,
                        )
                        st.session_state["order_flow"] = resumed
                        st.rerun()
                with r2:
                    if st.button("Reject Sensitive Tool"):
                        resumed = resume_order_flow(
                            run_id=order_flow["run_id"],
                            approve=False,
                            actor=actor,
                            actor_role=role,
                        )
                        st.session_state["order_flow"] = resumed
                        st.rerun()

        po = order_flow.get("purchase_order")
        if not po and order_flow.get("status") == "completed" and approval_id:
            # Deterministic fallback already embeds PO; also try lookup
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
                <div class="po-record">
                    <strong>Mock Purchase Order Created</strong><br>
                    Approval ID: {approval_id}<br>
                    PO ID: {po.get('purchase_order_id')}<br>
                    Final quantity: {po.get('approved_final_quantity')}<br>
                    Status: {po.get('status')}<br>
                    agent={po.get('agent_recommended_quantity')} ·
                    human={po.get('human_proposed_quantity')} ·
                    approved={po.get('approved_final_quantity')}
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.markdown("</div></div>", unsafe_allow_html=True)

    # If approval already granted earlier without agent pause, allow direct status refresh
    if approval_id and st.button("Refresh purchase order status"):
        from database.connection import get_session
        from repositories import purchase_order_repository

        with get_session() as session:
            existing = purchase_order_repository.get_purchase_order_by_approval(session, approval_id)
        if existing:
            st.session_state["order_flow"] = {
                "status": "completed",
                "purchase_order": existing.model_dump(mode="json"),
            }
            st.rerun()
        else:
            st.info("No purchase order found yet for this approval.")

    render_footer()


main()
