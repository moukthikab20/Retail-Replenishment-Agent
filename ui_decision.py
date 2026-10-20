"""Recommendation Detail — disposition-aware human decision controls."""

from __future__ import annotations

from typing import Any, Callable

import streamlit as st

from services import auth_service, decision_workflow_service
from services.errors import user_facing_error
from ui_components import kpi_row, role_label


def _reason_labels(codes: list[dict[str, str]]) -> list[str]:
    return [c["label"] for c in codes]


def _code_for_label(codes: list[dict[str, str]], label: str) -> str:
    for c in codes:
        if c["label"] == label:
            return c["code"]
    return "other"


def render_decision_workflow(
    *,
    recommendation_id: str,
    rec: dict[str, Any],
    actor: str,
    role: str,
    session_id: str,
    on_navigate_new: Callable[[str], None] | None = None,
) -> None:
    """Render Approve / Adjust / Decline / Retry / Manual based on disposition."""
    available = decision_workflow_service.get_available_actions(
        recommendation_id, actor_role=role
    )
    actions = set(available.get("actions") or [])
    codes = available.get("reason_codes") or decision_workflow_service.reason_code_options()
    disposition = available.get("disposition") or rec.get("disposition")

    with st.container(border=True):
        st.markdown(
            '<h3 class="il-panel-title il-dd-human-decision-title">Human decision</h3>',
            unsafe_allow_html=True,
        )
        for note in available.get("notes") or []:
            st.caption(note)

        if available.get("terminal"):
            st.info(f"This recommendation is already decided ({available.get('status')}).")
            if st.button("Back to Today's Decisions", use_container_width=True):
                st.switch_page("pages/1_Todays_Queue.py")
            return

        if disposition == "blocked" and not actions:
            st.warning(
                "This item cannot proceed until the blocking condition is resolved "
                "(for example stale inventory or missing data)."
            )
            if st.button("Back to Today's Decisions", use_container_width=True):
                st.switch_page("pages/1_Todays_Queue.py")
            return

        if disposition == "auto_release" and not actions:
            st.success(
                "Handled automatically — no approval controls are required for this item."
            )
            return

        if not actions:
            st.info("No decision actions are available for your role on this item.")
            if st.button("Back to Today's Decisions", use_container_width=True):
                st.switch_page("pages/1_Todays_Queue.py")
            return

        mode = st.radio(
            "Action",
            options=sorted(actions),
            format_func=lambda a: {
                "approve": "Approve recommendation",
                "adjust": "Adjust quantity",
                "decline": "Reject / No order",
                "recall": "Recall for review",
                "override": "Override quantity",
                "retry": "Retry scoring",
                "manual_quantity": "Enter manual quantity",
            }.get(a, a),
            horizontal=True,
            key=f"decision_mode_{recommendation_id}",
        )

        st.caption(
            "If you approve, the quantity is locked and prepared for the next purchasing "
            "transmission window. Rejecting prepares no order from this recommendation."
        )

        if mode == "approve":
            st.write(
                f"Approves agent quantity **{rec.get('agent_recommended_quantity')}** "
                "(agent recommendation preserved)."
            )
            if st.button("Approve recommendation", type="primary", use_container_width=True):
                try:
                    result = decision_workflow_service.approve_recommendation(
                        recommendation_id=recommendation_id,
                        actor=actor,
                        actor_role=role,
                        user_id=actor,
                        session_id=session_id,
                    )
                    _store_approval_ids(result)
                    st.success(result.get("message") or "Approved")
                except Exception as exc:  # noqa: BLE001
                    st.error(user_facing_error(exc))

        elif mode in {"adjust", "override"}:
            _render_adjust_form(
                recommendation_id=recommendation_id,
                rec=rec,
                actor=actor,
                role=role,
                session_id=session_id,
                codes=codes,
                is_override=(mode == "override"),
            )

        elif mode == "decline":
            label = st.selectbox(
                "Decline reason code",
                options=_reason_labels(codes),
                key=f"decline_code_{recommendation_id}",
            )
            code = _code_for_label(codes, label)
            comments = st.text_area(
                "Comments" + (" (required for Other)" if code == "other" else " (optional)"),
                key=f"decline_comments_{recommendation_id}",
            )
            if st.button("Confirm reject / no order", type="secondary", use_container_width=True):
                try:
                    result = decision_workflow_service.decline_recommendation(
                        recommendation_id=recommendation_id,
                        actor=actor,
                        actor_role=role,
                        reason_code=code,
                        comments=comments,
                        user_id=actor,
                        session_id=session_id,
                    )
                    st.warning(
                        f"Declined by {result.get('declined_by')} "
                        f"({result.get('declined_role')}). Recommendation retained."
                    )
                except Exception as exc:  # noqa: BLE001
                    st.error(user_facing_error(exc))

        elif mode == "recall":
            comments = st.text_input("Recall note (optional)")
            if st.button("Recall for review", type="primary", use_container_width=True):
                try:
                    result = decision_workflow_service.recall_auto_release(
                        recommendation_id=recommendation_id,
                        actor=actor,
                        actor_role=role,
                        comments=comments,
                        user_id=actor,
                        session_id=session_id,
                    )
                    st.success(result.get("message"))
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(user_facing_error(exc))

        elif mode == "retry":
            st.write("Re-scores this store/SKU with current inventory and policy data.")
            if st.button("Retry scoring", type="primary", use_container_width=True):
                try:
                    result = decision_workflow_service.retry_blocked(
                        recommendation_id=recommendation_id,
                        actor=actor,
                        actor_role=role,
                        user_id=actor,
                        session_id=session_id,
                    )
                    st.success(result.get("message"))
                    new_id = result.get("new_recommendation_id")
                    if new_id and on_navigate_new:
                        on_navigate_new(new_id)
                    elif new_id:
                        st.session_state["nav_recommendation_id"] = new_id
                        st.session_state["recommendation_id"] = new_id
                        st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(user_facing_error(exc))

        elif mode == "manual_quantity":
            st.warning(
                "AI recommendation was unavailable for this blocked item. "
                "The quantity you enter is a **human manual quantity** — "
                "it will not be attributed to the agent — and always routes to formal approval."
            )
            _render_manual_blocked_form(
                recommendation_id=recommendation_id,
                actor=actor,
                role=role,
                session_id=session_id,
                codes=codes,
            )

        if st.button(
            "Back to Today's Decisions",
            use_container_width=True,
            key="decision_back_queue",
        ):
            st.switch_page("pages/1_Todays_Queue.py")


def _store_approval_ids(result: dict[str, Any]) -> None:
    if result.get("approval_id"):
        st.session_state["approval_id"] = result["approval_id"]
    if result.get("review_id"):
        st.session_state["review_id"] = result["review_id"]
    if result.get("required_role"):
        st.session_state["required_role"] = result["required_role"]


def _render_adjust_form(
    *,
    recommendation_id: str,
    rec: dict[str, Any],
    actor: str,
    role: str,
    session_id: str,
    codes: list[dict[str, str]],
    is_override: bool,
) -> None:
    qty = st.number_input(
        "Proposed quantity",
        min_value=0,
        step=1,
        value=int(rec.get("agent_recommended_quantity") or 0),
        key=f"adjust_qty_{recommendation_id}",
    )
    label = st.selectbox(
        "Reason code",
        options=_reason_labels(codes),
        key=f"adjust_code_{recommendation_id}",
    )
    code = _code_for_label(codes, label)
    comments = st.text_area(
        "Comments" + (" (required for Other)" if code == "other" else " (optional)"),
        key=f"adjust_comments_{recommendation_id}",
    )

    evaluation = decision_workflow_service.preview_adjust(
        recommendation_id=recommendation_id,
        proposed_quantity=int(qty),
        reason_code=code,
        comments=comments,
    )
    if not evaluation.get("case_pack_compliant"):
        st.warning(
            "Quantity is not case-pack compliant. It will **not** be silently rounded. "
            f"Nearest valid: lower={evaluation.get('nearest_lower_case_pack')}, "
            f"higher={evaluation.get('nearest_higher_case_pack')}."
        )
    for message in evaluation.get("validation_messages") or []:
        if evaluation.get("valid"):
            st.info(message)
        else:
            st.error(message)

    label_btn = "Submit Override" if is_override else "Submit Adjustment"
    if st.button(
        label_btn,
        type="primary",
        use_container_width=True,
        disabled=not evaluation.get("valid"),
    ):
        try:
            result = decision_workflow_service.adjust_quantity(
                recommendation_id=recommendation_id,
                actor=actor,
                actor_role=role,
                proposed_quantity=int(qty),
                reason_code=code,
                comments=comments,
                user_id=actor,
                session_id=session_id,
            )
            _store_approval_ids(result)
            st.success(result.get("message") or "Submitted")
        except Exception as exc:  # noqa: BLE001
            st.error(user_facing_error(exc))


def _render_manual_blocked_form(
    *,
    recommendation_id: str,
    actor: str,
    role: str,
    session_id: str,
    codes: list[dict[str, str]],
) -> None:
    if not auth_service.can_manual_quantity_blocked(role):
        st.info("Manual quantity requires inventory planner or higher.")
        return

    qty = st.number_input(
        "Manual quantity (human-entered)",
        min_value=0,
        step=1,
        value=0,
        key=f"manual_qty_{recommendation_id}",
    )
    label = st.selectbox(
        "Reason code",
        options=_reason_labels(codes),
        key=f"manual_code_{recommendation_id}",
    )
    code = _code_for_label(codes, label)
    comments = st.text_area(
        "Reason / comments" + (" (required for Other)" if code == "other" else ""),
        key=f"manual_comments_{recommendation_id}",
    )
    evaluation = decision_workflow_service.preview_adjust(
        recommendation_id=recommendation_id,
        proposed_quantity=int(qty),
        reason_code=code,
        comments=comments,
    )
    kpi_row(
        [
            {"label": "Agent Quantity", "value": "Unavailable"},
            {"label": "Proposed Quantity", "value": evaluation.get("proposed_quantity")},
            {
                "label": "Projected Days of Supply",
                "value": evaluation.get("projected_days_of_supply"),
            },
            {
                "label": "Projected Risk",
                "value": str(evaluation.get("projected_risk") or "—").replace("_", " ").title(),
            },
            {
                "label": "Case Pack Compliance",
                "value": "Yes" if evaluation.get("case_pack_compliant") else "No",
            },
            {
                "label": "Additional Approval Required",
                "value": "Yes (always)",
                "sub": role_label(evaluation.get("required_role")),
            },
        ],
        columns=3,
    )
    for message in evaluation.get("validation_messages") or []:
        st.error(message) if not evaluation.get("valid") else st.info(message)

    if st.button(
        "Submit Manual Quantity for Approval",
        type="primary",
        use_container_width=True,
        disabled=not evaluation.get("valid"),
    ):
        try:
            result = decision_workflow_service.submit_manual_quantity_blocked(
                recommendation_id=recommendation_id,
                actor=actor,
                actor_role=role,
                proposed_quantity=int(qty),
                reason_code=code,
                comments=comments,
                user_id=actor,
                session_id=session_id,
            )
            _store_approval_ids(result)
            st.success(result.get("message"))
        except Exception as exc:  # noqa: BLE001
            st.error(user_facing_error(exc))
