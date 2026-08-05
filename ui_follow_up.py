"""Compact Analysis-page follow-up Q&A section (Infolob styling)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from services.errors import user_facing_error


def example_follow_up_prompts(agent_recommended_quantity: int | None) -> list[str]:
    """Business-readable example questions for the follow-up input."""
    qty = int(agent_recommended_quantity) if agent_recommended_quantity is not None else 72
    lower = max(qty - 12, 0)
    return [
        f"Why is the recommendation {qty} units?",
        f"What happens if I order {lower} units?",
        "What if the incoming shipment is delayed by two days?",
        "Which factors contributed most to the risk?",
    ]


def _scenario_summary(follow_up: dict[str, Any]) -> str | None:
    scenario = follow_up.get("scenario_result") or {}
    if not scenario and follow_up.get("mode") != "scenario_service":
        return None
    answer = (follow_up.get("answer") or "").strip()
    if answer.lower().startswith("hypothetical"):
        return answer
    if scenario.get("proposed_quantity") is not None:
        return (
            f"Hypothetical quantity scenario: proposed "
            f"{scenario.get('proposed_quantity')} vs recommended "
            f"{scenario.get('agent_recommended_quantity')} "
            f"(risk={scenario.get('projected_risk', 'n/a')})."
        )
    if scenario.get("delay_days") is not None:
        return (
            f"Hypothetical delay scenario: {scenario.get('delay_days')} day(s); "
            f"stockout_before_arrival={scenario.get('stockout_before_arrival')}; "
            f"shortfall={scenario.get('expected_shortfall_units', 0)}."
        )
    return answer or None


def render_follow_up_section(
    *,
    recommendation_id: str,
    user_id: str,
    session_id: str | None,
    actor: str,
    actor_role: str | None,
    agent_recommended_quantity: int | None = None,
) -> None:
    """
    Compact follow-up section. Requires an existing recommendation_id.
    No approval or purchase-order action buttons.
    """
    if not recommendation_id:
        return

    with st.expander("Ask about this recommendation", expanded=False):
        st.caption(
            "Answers use the saved recommendation. Hypothetical quantity or delay "
            "scenarios are labeled and do not change the stored recommendation."
        )

        examples = example_follow_up_prompts(agent_recommended_quantity)
        st.markdown(
            '<p class="il-meta-line"><strong>Example prompts</strong></p>',
            unsafe_allow_html=True,
        )
        for example in examples:
            st.markdown(
                f'<p class="secondary-text">• {example}</p>',
                unsafe_allow_html=True,
            )

        def _apply_example() -> None:
            choice = st.session_state.get("follow_up_example_select")
            if choice and choice != "(type your own question)":
                st.session_state["follow_up_question_input"] = choice

        st.selectbox(
            "Use an example",
            options=["(type your own question)"] + examples,
            key="follow_up_example_select",
            on_change=_apply_example,
            label_visibility="collapsed",
        )
        follow_up_q = st.text_input(
            "Question",
            key="follow_up_question_input",
            placeholder=examples[0],
            label_visibility="collapsed",
        )

        ask_col, clear_col, _ = st.columns([1, 1.4, 2])
        with ask_col:
            ask_clicked = st.button("Ask", key="follow_up_ask_btn")
        with clear_col:
            clear_clicked = st.button(
                "Clear conversation",
                key="follow_up_clear_btn",
            )

        if clear_clicked:
            try:
                from agent.sessions import clear_follow_up_session

                clear_follow_up_session(user_id, recommendation_id)
            except Exception as exc:  # noqa: BLE001
                st.error(user_facing_error(exc))
            else:
                st.session_state.pop("follow_up_answer", None)
                st.session_state.pop("follow_up_question", None)
                # Recommendation and analysis decision must remain.
                st.caption("Conversation cleared. The recommendation was not changed.")
                st.rerun()

        if ask_clicked:
            question = (follow_up_q or "").strip()
            if not question:
                st.warning("Enter a follow-up question first.")
            else:
                with st.spinner("Answering…"):
                    from agent.runner import answer_follow_up

                    try:
                        st.session_state["follow_up_question"] = question
                        st.session_state["follow_up_answer"] = answer_follow_up(
                            recommendation_id,
                            question,
                            user_id=user_id,
                            session_id=session_id,
                            actor=actor,
                            actor_role=actor_role,
                        )
                    except Exception as exc:  # noqa: BLE001
                        st.error(user_facing_error(exc))

        follow_up = st.session_state.get("follow_up_answer")
        if not follow_up:
            return

        if follow_up.get("status") == "error":
            st.warning(
                follow_up.get("answer") or follow_up.get("message") or "Follow-up failed."
            )
        else:
            st.markdown(
                f'<p class="agent-explanation">{follow_up.get("answer", "")}</p>',
                unsafe_allow_html=True,
            )

        facts = follow_up.get("verified_facts") or []
        if facts:
            st.markdown(
                '<p class="il-meta-line"><strong>Verified facts</strong></p>',
                unsafe_allow_html=True,
            )
            for fact in facts:
                st.markdown(
                    f'<p class="secondary-text">• {fact}</p>',
                    unsafe_allow_html=True,
                )

        assumptions = follow_up.get("assumptions") or []
        if assumptions:
            st.markdown(
                '<p class="il-meta-line"><strong>Assumptions</strong></p>',
                unsafe_allow_html=True,
            )
            for item in assumptions:
                st.markdown(
                    f'<p class="secondary-text">• {item}</p>',
                    unsafe_allow_html=True,
                )

        unresolved = follow_up.get("unresolved_items") or []
        if unresolved:
            st.markdown(
                '<p class="il-meta-line"><strong>Unresolved</strong></p>',
                unsafe_allow_html=True,
            )
            for item in unresolved:
                st.markdown(
                    f'<p class="secondary-text">• {item}</p>',
                    unsafe_allow_html=True,
                )

        scenario_summary = _scenario_summary(follow_up)
        if scenario_summary:
            st.markdown(
                '<p class="il-meta-line"><strong>Hypothetical scenario</strong></p>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<p class="secondary-text">{scenario_summary}</p>',
                unsafe_allow_html=True,
            )

        with st.expander("Technical details", expanded=False):
            st.caption(f"question_type: {follow_up.get('question_type') or 'general'}")
            if follow_up.get("suggested_next_action"):
                st.caption(
                    f"suggested_next_action: {follow_up.get('suggested_next_action')}"
                )
            tools_used = follow_up.get("tools_used") or []
            if tools_used:
                st.caption("tools_used: " + ", ".join(str(t) for t in tools_used))
            st.caption(
                "can_change_business_state: "
                + ("yes" if follow_up.get("can_change_business_state") else "no")
            )
            if follow_up.get("follow_up_session_id") or follow_up.get("conversation_id"):
                st.caption(
                    "follow_up_session_id: "
                    + str(
                        follow_up.get("follow_up_session_id")
                        or follow_up.get("conversation_id")
                    )
                )
            # Raw JSON stays optional and collapsed — not shown by default.
            if st.checkbox(
                "Show raw response JSON",
                value=False,
                key="follow_up_show_raw_json",
            ):
                st.json(follow_up)
