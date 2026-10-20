"""Unit tests for Today's Queue read model."""

from __future__ import annotations

from services import batch_run_service, policy_service, queue_service


def test_get_todays_queue_empty_without_run():
    payload = queue_service.get_todays_queue()
    assert payload["run"] is None
    assert payload["rows"] == []
    assert payload["summary"]["needs_review"] == 0


def test_get_todays_queue_from_latest_batch(monkeypatch):
    policy_service.ensure_default_policy()
    real_age = policy_service.inventory_age_hours

    def _age(position, **kwargs):
        if position.sku == "SKU-1004":
            return 10_000.0
        return real_age(position, **kwargs)

    monkeypatch.setattr("services.policy_service.inventory_age_hours", _age)
    run = batch_run_service.run_replenishment_batch(
        [
            ("ST001", "SKU-1001"),
            ("ST001", "SKU-1002"),
            ("ST001", "SKU-1004"),
        ],
        initiated_by="alex.store",
        user_id="alex.store",
    )
    payload = queue_service.get_todays_queue()
    assert payload["run"]["run_id"] == run["run_id"]
    assert payload["summary"]["needs_review"] >= 1
    assert payload["summary"]["blocked"] >= 1
    assert payload["summary"]["auto_released"] >= 1
    assert "no_order" in payload["summary"]
    assert len(payload["rows"]) == 3
    assert all("recommendation_id" in row for row in payload["rows"])
    assert all("exception" in row for row in payload["rows"])
    # Awaiting decision value is human-review only (blocked excluded).
    needs = queue_service.get_todays_queue(filter_key="needs_review")
    human_only = sum(float(r["order_value"] or 0) for r in needs["rows"])
    assert payload["summary"]["order_value_awaiting_decision"] == human_only
