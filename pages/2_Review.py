"""Page 2 — Review, approval, and mock purchase order."""

from __future__ import annotations

import streamlit as st

from agent.runner import (
    get_pending_order_flow,
    resume_order_run,
    start_order_agent_after_approval,
)
from services import (
    approval_service,
    auth_service,
    human_review_service,
    product_service,
    recommendation_service,
)
from services.errors import user_facing_error
from ui_common import bootstrap_app
from ui_components import (
    info_grid,
    kpi_row,
    page_heading,
    panel_title,
    risk_pill,
    role_label,
    status_pill,
)


def main() -> None:
    user = bootstrap_app("Review | Retail Replenishment Agent", active_nav="review")
    actor = user["user_id"]
    role = user["role"]
    session_id = user["session_id"]

    page_heading("Review", "Quantity decision and formal approval")

    recommendation_id = st.session_state.get("nav_recommendation_id") or st.session_state.get(
        "recommendation_id"
    )
    if not recommendation_id:
        st.warning("No recommendation selected. Return to Analysis and continue from there.")
        if st.button("Back to Analysis"):
            st.switch_page("pages/1_Analysis.py")
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
        return

    product = product_service.get_product_details(rec["sku"])

    with st.container(border=True):
        panel_title("Recommendation Summary")
        st.markdown(risk_pill(rec["risk_level"]), unsafe_allow_html=True)
        info_grid(
            [
                ("Store", rec["store_id"]),
                ("SKU", rec["sku"]),
                ("Product", product.product_name),
                ("Agent Recommended Qty", rec["agent_recommended_quantity"]),
                ("Forecast", rec["forecast_units"]),
                ("Case Pack", rec["case_pack"]),
            ]
        )

    with st.container(border=True):
        panel_title("Quantity Selection")
        choice_label = st.radio(
            "Choice",
            options=["Use recommended quantity", "Enter another quantity"],
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
            override_reason = st.text_area(
                "Override reason", help="Required when quantity differs."
            )

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

        kpi_row(
            [
                {
                    "label": "Agent Recommended",
                    "value": rec["agent_recommended_quantity"],
                },
                {
                    "label": "Proposed Quantity",
                    "value": preview.get("human_proposed_quantity"),
                },
                {
                    "label": "Difference",
                    "value": preview.get("difference_units"),
                    "sub": f"{preview.get('difference_percent')}%",
                },
                {
                    "label": "Projected Coverage",
                    "value": preview.get("projected_days_of_supply"),
                    "sub": "Days of supply",
                },
                {
                    "label": "Projected Risk",
                    "value": str(preview.get("projected_risk") or "—").replace("_", " ").title(),
                },
                {
                    "label": "Required Approval",
                    "value": role_label(preview.get("approval_level")),
                },
            ],
            columns=3,
        )

        for message in preview.get("validation_messages", []):
            if preview.get("valid"):
                st.info(message)
            else:
                st.error(message)

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
                    reason="Rejected on Review page",
                )
                st.warning("Recommendation rejected. No purchase order will be created.")
            except Exception as exc:  # noqa: BLE001
                st.error(user_facing_error(exc))

    approval_id = st.session_state.get("approval_id")
    required_role = st.session_state.get("required_role")
    if approval_id:
        with st.container(border=True):
            panel_title("Formal Approval")
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
                    ("Approval ID", status.get("approval_id", approval_id)),
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

            with st.expander("View technical details", expanded=False):
                st.json(status)

    # Browser refresh recovery — pending HITL work lives in the database.
    if approval_id and not st.session_state.get("order_flow"):
        reloaded = get_pending_order_flow(approval_id)
        if reloaded is not None:
            st.session_state["order_flow"] = reloaded

    order_flow = st.session_state.get("order_flow")
    if order_flow:
        with st.container(border=True):
            panel_title("Order Confirmation")

            if order_flow.get("status") == "paused":
                st.warning(
                    "Order creation is paused for sensitive-tool approval. "
                    "Formal database approval is already recorded; this step confirms "
                    "the create_mock_purchase_order tool. Refresh-safe pending run: "
                    f"{order_flow.get('run_id')}."
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
                else:
                    st.info(
                        "Another authorized approver can resume this paused order tool "
                        "after refresh — pending state is stored in the database."
                    )

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
                        <div class="title">Order created successfully</div>
                        <div class="row">Purchase Order ID: <b>{po.get('purchase_order_id')}</b></div>
                        <div class="row">Store: <b>{po.get('store_id', rec.get('store_id'))}</b></div>
                        <div class="row">SKU: <b>{po.get('sku', rec.get('sku'))}</b></div>
                        <div class="row">Final Quantity: <b>{po.get('approved_final_quantity')}</b></div>
                        <div class="row">Status: <b>{po.get('status')}</b></div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                if st.button("Start New Replenishment", type="primary"):
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
                    st.switch_page("pages/1_Analysis.py")

            with st.expander("View technical details", expanded=False):
                st.json(order_flow)

    if approval_id and st.button("Refresh purchase order status"):
        from database.connection import get_session
        from repositories import purchase_order_repository

        with get_session() as session:
            existing = purchase_order_repository.get_purchase_order_by_approval(
                session, approval_id
            )
        if existing:
            st.session_state["order_flow"] = {
                "status": "completed",
                "purchase_order": existing.model_dump(mode="json"),
            }
            st.rerun()
        else:
            st.info("No purchase order found yet for this approval.")


main()
