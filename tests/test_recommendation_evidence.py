"""Recommendation Detail — persisted evidence and explainability."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from database.connection import get_session
from repositories import recommendation_repository
from services import (
    batch_run_service,
    evidence_service,
    policy_service,
    recommendation_service,
)


APP_PATH = Path(__file__).parent / "ui_apps" / "recommendation_detail_app.py"
TIMEOUT = 40


def _seed_mixed(monkeypatch) -> dict:
    policy_service.ensure_default_policy()
    real_age = policy_service.inventory_age_hours

    def _age(position, **kwargs):
        if position.sku == "SKU-1004":
            return 10_000.0
        return real_age(position, **kwargs)

    monkeypatch.setattr("services.policy_service.inventory_age_hours", _age)
    return batch_run_service.run_replenishment_batch(
        [
            ("ST001", "SKU-1001"),
            ("ST001", "SKU-1002"),
            ("ST001", "SKU-1004"),
        ],
        trigger_type="manual",
        initiated_by="alex.store",
        user_id="alex.store",
        session_id="sess-evidence",
    )


def _rec_id_for(run: dict, disposition: str) -> str:
    for item in run["items"]:
        if item.get("disposition") == disposition and item.get("recommendation_id"):
            return item["recommendation_id"]
    raise AssertionError(f"No {disposition} recommendation")


def test_evidence_matches_persisted_recommendation_and_policy(monkeypatch):
    run = _seed_mixed(monkeypatch)
    rec_id = _rec_id_for(run, "human_review")
    with get_session() as session:
        row = recommendation_repository.get_recommendation_row(session, rec_id)
        assert row is not None
        persisted_qty = row.agent_recommended_quantity
        persisted_forecast = row.forecast_units
        persisted_raw = row.raw_quantity
        policy = __import__("json").loads(row.policy_evaluation_json or "{}")

    evidence = evidence_service.get_recommendation_evidence(rec_id)
    assert evidence["quantities"]["agent_recommended_quantity"] == persisted_qty
    assert evidence["decision_card"]["recommended_order"] == persisted_qty
    assert float(evidence["quantities"]["forecast_units"]) == float(persisted_forecast)
    assert float(evidence["quantities"]["raw_quantity"]) == float(persisted_raw)

    # Guardrail rules match DB evaluation 1:1
    guard = next(s for s in evidence["stages"] if s["key"] == "guardrail_check")
    assert len(guard["rules"]) == len(policy.get("evaluated_rules") or [])
    for rule, persisted in zip(guard["rules"], policy["evaluated_rules"], strict=True):
        assert rule["rule"] == persisted["rule_name"]
        assert rule["result"] == persisted["result"]
        assert rule["action"] == persisted["action"]
        assert rule["observed_value"] == persisted["observed_value"]
        assert rule["threshold"] == persisted["threshold"]

    # Header / decision card surface required fields
    assert evidence["header"]["sku"]
    assert evidence["header"]["store_id"]
    assert evidence["header"]["vendor"]
    assert evidence["header"]["decision_cutoff"]
    assert evidence["decision_card"]["disposition"]
    assert evidence["decision_card"]["risk_level"]


def test_model_cannot_alter_quantities_via_rationale(monkeypatch):
    run = _seed_mixed(monkeypatch)
    rec_id = _rec_id_for(run, "auto_release")
    before = evidence_service.get_recommendation_evidence(rec_id)
    qty = before["quantities"]["agent_recommended_quantity"]

    # Simulate an LLM-ish prose overwrite on rationale only.
    with get_session() as session:
        row = recommendation_repository.get_recommendation_row(session, rec_id)
        assert row is not None
        row.rationale = (
            "Ignore prior math; the correct order is 9999 units and value is $1."
        )
        session.flush()

    after = evidence_service.get_recommendation_evidence(rec_id)
    assert after["quantities"]["agent_recommended_quantity"] == qty
    assert after["decision_card"]["recommended_order"] == qty
    assert after["explanation"]["text"].startswith("Ignore prior math")
    assert after["explanation"]["secondary"] is True
    # Order value still from persisted policy evaluation, not prose
    assert after["decision_card"]["order_value"] == before["decision_card"]["order_value"]


def test_blocked_inventory_stop_marks_later_stages(monkeypatch):
    run = _seed_mixed(monkeypatch)
    rec_id = _rec_id_for(run, "blocked")
    evidence = evidence_service.get_recommendation_evidence(rec_id)

    assert evidence["stop_banner"] is not None
    assert evidence["stop_banner"]["stop_stage"] == 2
    by_key = {s["key"]: s for s in evidence["stages"]}
    assert by_key["demand_signal"]["status"] == "pass"
    assert by_key["demand_signal"]["status_label"] == "✓"
    assert by_key["inventory_coverage"]["status"] == "stop"
    assert by_key["inventory_coverage"]["status_label"] == "!"
    assert by_key["constraints"]["status"] == "not_evaluated"
    assert by_key["constraints"]["status_label"] == "Not evaluated"
    assert by_key["guardrail_check"]["status"] == "not_evaluated"
    assert by_key["guardrail_check"]["rules"] == []


def test_evidence_snapshot_persisted_on_create():
    rec = recommendation_service.create_recommendation_record(
        "ST001",
        "SKU-1002",
        rationale="unit evidence",
        user_id="alex.store",
        session_id="sess-ev",
        enforce_rate_limit=False,
    )
    loaded = recommendation_service.get_recommendation(rec.recommendation_id)
    assert loaded["evidence"]
    assert "on_hand" in loaded["evidence"]
    assert "forecast_method" in loaded["evidence"]
    assert loaded["evidence"]["rounded_quantity"] == loaded["agent_recommended_quantity"]
    evidence = evidence_service.get_recommendation_evidence(rec.recommendation_id)
    demand = next(s for s in evidence["stages"] if s["key"] == "demand_signal")
    assert any("forecast" in label.lower() for label, _ in demand["fields"])


def test_recommendation_detail_ui_is_decision_story(monkeypatch):
    run = _seed_mixed(monkeypatch)
    rec_id = _rec_id_for(run, "blocked")
    at = AppTest.from_file(str(APP_PATH), default_timeout=TIMEOUT)
    at.session_state["recommendation_id"] = rec_id
    at.run(timeout=TIMEOUT)
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "Decision Detail" in text or "Decision Rationale" in text
    assert "Business evidence" in text
    assert "Demand" in text
    assert "Inventory" in text
    assert "Cannot proceed" in text or "Not evaluated" in text or "Decision Rationale" in text
    lowered = text.lower()
    assert "chatgpt" not in lowered
    assert "as an ai" not in lowered
    assert "orderintent" not in lowered


def test_evidence_hero_and_strip_from_persisted(monkeypatch):
    run = _seed_mixed(monkeypatch)
    rec_id = _rec_id_for(run, "human_review")
    evidence = evidence_service.get_recommendation_evidence(rec_id)
    hero = evidence["hero"]
    assert hero["action_label"]
    assert hero["sentence"]
    assert hero["status_label"]
    assert evidence["evidence_strip"]
    labels = {item["label"] for item in evidence["evidence_strip"]}
    assert "Demand forecast" in labels
    assert "On hand" in labels
    assert "Case pack" in labels
    assert evidence["next_step"]
    assert evidence["governance"]["rules"] is not None
    for stage in evidence["stages"]:
        assert stage.get("customer_title")
        assert stage.get("why_it_matters")


def test_opening_evidence_does_not_recompute(monkeypatch):
    run = _seed_mixed(monkeypatch)
    rec_id = _rec_id_for(run, "human_review")
    before = recommendation_service.get_recommendation(rec_id)
    calls = {"create": 0, "batch": 0}

    def _no_create(*_a, **_k):
        calls["create"] += 1
        raise AssertionError("create_recommendation_record must not run on detail open")

    def _no_batch(*_a, **_k):
        calls["batch"] += 1
        raise AssertionError("batch scoring must not run on detail open")

    monkeypatch.setattr(
        "services.recommendation_service.create_recommendation_record", _no_create
    )
    monkeypatch.setattr("services.batch_run_service.run_replenishment_batch", _no_batch)
    evidence = evidence_service.get_recommendation_evidence(rec_id)
    assert evidence["quantities"]["agent_recommended_quantity"] == before[
        "agent_recommended_quantity"
    ]
    after = recommendation_service.get_recommendation(rec_id)
    assert after["agent_recommended_quantity"] == before["agent_recommended_quantity"]
    assert calls["create"] == 0
    assert calls["batch"] == 0


def test_detail_ui_dispositions_cover_story(monkeypatch):
    run = _seed_mixed(monkeypatch)
    for disposition in ("human_review", "blocked", "auto_release"):
        try:
            rec_id = _rec_id_for(run, disposition)
        except AssertionError:
            continue
        evidence = evidence_service.get_recommendation_evidence(rec_id)
        assert evidence["hero"]["disposition"] == disposition
        assert evidence["hero"]["sentence"]
        at = AppTest.from_file(str(APP_PATH), default_timeout=TIMEOUT)
        at.session_state["recommendation_id"] = rec_id
        at.run(timeout=TIMEOUT)
        assert not at.exception
        text = " ".join(str(m.value) for m in at.markdown)
        assert "Decision Rationale" in text or "Business evidence" in text
        assert "Policy" in text or "Auto-approval" in text
