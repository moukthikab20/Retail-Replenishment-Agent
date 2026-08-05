"""Checkpoint 8 — follow-up UI on Analysis (Streamlit AppTest)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from streamlit.testing.v1 import AppTest

from services import recommendation_service
from ui_follow_up import example_follow_up_prompts


APP_PATH = Path(__file__).parent / "ui_apps" / "follow_up_section_app.py"
TIMEOUT = 30


def _app() -> AppTest:
    return AppTest.from_file(str(APP_PATH), default_timeout=TIMEOUT)


def test_example_prompts_include_required_patterns():
    prompts = example_follow_up_prompts(72)
    joined = " ".join(prompts).lower()
    assert "why is the recommendation 72 units" in joined
    assert "what happens if i order" in joined
    assert "delayed by two days" in joined
    assert "risk" in joined


def test_follow_up_section_hidden_without_recommendation():
    at = _app()
    at.run(timeout=TIMEOUT)
    assert not at.exception
    assert any("No recommendation yet" in str(el.value) for el in at.markdown)
    assert "Ask about this recommendation" not in [e.label for e in at.expander]
    labels = [b.label for b in at.button]
    assert "Ask" not in labels
    assert "Clear conversation" not in labels


def test_follow_up_section_renders_compact_controls_when_recommendation_exists():
    at = _app()
    at.session_state["recommendation_id"] = "REC-ui-1"
    at.session_state["user_id"] = "alex.store"
    at.session_state["session_id"] = "sess-ui"
    at.session_state["actor_role"] = "store_manager"
    at.session_state["agent_recommended_quantity"] = 72
    at.run(timeout=TIMEOUT)
    assert not at.exception

    expanders = [e.label for e in at.expander]
    assert "Ask about this recommendation" in expanders

    labels = [b.label for b in at.button]
    assert "Ask" in labels
    assert "Clear conversation" in labels
    # No approval / PO actions inside follow-up section.
    forbidden = {"Approve", "Create Purchase Order", "Create PO", "Reject", "Submit Review"}
    assert forbidden.isdisjoint(set(labels))

    page_text = " ".join(str(m.value) for m in at.markdown).lower()
    assert "example prompts" in page_text
    assert "why is the recommendation 72 units" in page_text
    assert "delayed by two days" in page_text
    assert at.text_input
    assert at.selectbox


def test_ask_displays_structured_fields_not_raw_json(monkeypatch):
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="ui-follow-up"
    )
    fake = {
        "status": "completed",
        "recommendation_id": rec.recommendation_id,
        "question_type": "explanation",
        "answer": "The saved recommendation is based on forecast and case pack.",
        "verified_facts": [f"agent_recommended_quantity={rec.agent_recommended_quantity}"],
        "assumptions": ["Demand continues at the seven-day average."],
        "unresolved_items": [],
        "scenario_result": None,
        "tools_used": ["get_recommendation"],
        "can_change_business_state": False,
        "suggested_next_action": "review_recommendation",
        "follow_up_session_id": f"replenishment:alex.store:{rec.recommendation_id}",
        "mode": "deterministic_fallback",
    }
    monkeypatch.setattr("agent.runner.answer_follow_up", MagicMock(return_value=fake))

    at = _app()
    at.session_state["recommendation_id"] = rec.recommendation_id
    at.session_state["user_id"] = "alex.store"
    at.session_state["session_id"] = "sess-ui"
    at.session_state["actor_role"] = "store_manager"
    at.session_state["agent_recommended_quantity"] = rec.agent_recommended_quantity
    at.run(timeout=TIMEOUT)
    assert not at.exception

    at.text_input(key="follow_up_question_input").set_value(
        "Why is this quantity recommended?"
    ).run(timeout=TIMEOUT)
    at.button(key="follow_up_ask_btn").click().run(timeout=TIMEOUT)

    assert not at.exception
    page_text = " ".join(str(m.value) for m in at.markdown)
    assert "forecast" in page_text.lower() or "saved recommendation" in page_text.lower()
    assert "Verified facts" in page_text
    assert "Assumptions" in page_text
    # Raw JSON checkbox present but off by default.
    assert at.checkbox
    assert all(c.value is False for c in at.checkbox)


def test_clear_conversation_keeps_recommendation(monkeypatch):
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="ui-clear"
    )
    cleared = {"called": False}

    def _clear(user_id: str, recommendation_id: str) -> int:
        cleared["called"] = True
        assert user_id == "alex.store"
        assert recommendation_id == rec.recommendation_id
        return 2

    monkeypatch.setattr("agent.sessions.clear_follow_up_session", _clear)

    at = _app()
    at.session_state["recommendation_id"] = rec.recommendation_id
    at.session_state["user_id"] = "alex.store"
    at.session_state["session_id"] = "sess-ui"
    at.session_state["actor_role"] = "store_manager"
    at.session_state["follow_up_answer"] = {
        "status": "completed",
        "answer": "prior answer",
        "verified_facts": ["x=1"],
    }
    at.session_state["follow_up_question"] = "prior"
    at.run(timeout=TIMEOUT)
    assert not at.exception

    at.button(key="follow_up_clear_btn").click().run(timeout=TIMEOUT)
    assert not at.exception
    assert cleared["called"] is True
    assert at.session_state["recommendation_id"] == rec.recommendation_id
    assert "follow_up_answer" not in at.session_state
    assert "follow_up_question" not in at.session_state


def test_scenario_summary_shown_when_present(monkeypatch):
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="ui-scenario"
    )
    fake = {
        "status": "completed",
        "recommendation_id": rec.recommendation_id,
        "question_type": "quantity_scenario",
        "answer": "Hypothetical quantity scenario: ordering less reduces cover.",
        "verified_facts": ["proposed_quantity=60"],
        "assumptions": ["Hypothetical only."],
        "unresolved_items": [],
        "scenario_result": {
            "proposed_quantity": 60,
            "agent_recommended_quantity": rec.agent_recommended_quantity,
            "projected_risk": "stockout",
            "hypothetical": True,
        },
        "can_change_business_state": False,
        "mode": "scenario_service",
    }
    monkeypatch.setattr("agent.runner.answer_follow_up", MagicMock(return_value=fake))

    at = _app()
    at.session_state["recommendation_id"] = rec.recommendation_id
    at.session_state["user_id"] = "alex.store"
    at.session_state["agent_recommended_quantity"] = rec.agent_recommended_quantity
    at.run(timeout=TIMEOUT)
    at.text_input(key="follow_up_question_input").set_value(
        "What happens if I order 60 units?"
    ).run(timeout=TIMEOUT)
    at.button(key="follow_up_ask_btn").click().run(timeout=TIMEOUT)

    assert not at.exception
    page_text = " ".join(str(m.value) for m in at.markdown)
    assert "Hypothetical scenario" in page_text
    assert "Hypothetical quantity scenario" in page_text
