"""System Health / operational dependency checks — no secrets, truthful demo labels."""

from __future__ import annotations

from datetime import datetime, timezone

from health import check_health, is_healthy
from services import ops_health_service, policy_service
from services.recommendation_service import build_analysis


def test_health_ok_on_sqlite_test_db():
    payload = check_health()
    assert payload["status"] == "ok"
    assert is_healthy() is True
    assert payload["database"]["ok"] is True
    assert payload["demo"]["real_erp"] is False
    assert payload["demo"]["real_pos"] is False
    assert payload["erp"]["adapter"] == "mock"
    assert payload["erp"]["real_erp"] is False
    assert payload["erp"]["ok"] is True
    assert payload["erp"]["real_erp"] is False
    assert payload["erp"]["ok"] is True
    assert "Mock" in (payload["erp"].get("label") or "") or payload["erp"].get("adapter") == "mock"


def test_health_payload_has_no_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value")
    monkeypatch.setattr("config.OPENAI_API_KEY", "sk-test-secret-value")
    monkeypatch.setattr("health.OPENAI_MODEL", "gpt-test")
    monkeypatch.setattr("config.DEMO_ACCESS_CODE", "super-secret-access")
    payload = check_health()
    dumped = str(payload)
    assert "sk-test-secret-value" not in dumped
    assert "super-secret-access" not in dumped
    assert "password" not in dumped.lower() or "***" in dumped
    assert payload["openai"]["api_key_present"] is True
    assert "banner" in payload["demo"]


def test_operational_dependencies_shape():
    payload = check_health()
    deps = payload["dependencies"]
    assert len(deps) >= 12
    by_name = {d["component"]: d for d in deps}
    for key in (
        "application",
        "postgresql_database",
        "recommendation_repository",
        "forecast_service",
        "inventory_master_data",
        "sales_data_source",
        "product_master_data",
        "supplier_data_source",
        "openai_model_service",
        "scheduler_last_run",
        "agent_runtime",
        "mock_erp_order_channel",
    ):
        assert key in by_name
        row = by_name[key]
        assert row["purpose"]
        assert row["checked_at"]
        assert row["status"] in {"healthy", "degraded", "stale", "unavailable"}
        assert "message" in row
        assert "latency_ms" in row
        assert "last_success" in row

    assert "Demo CSV" in by_name["inventory_master_data"]["message"] or (
        by_name["inventory_master_data"].get("label") == "Inventory Data Source — Demo CSV"
        or "demo_csv" in str(by_name["inventory_master_data"])
    )
    assert by_name["mock_erp_order_channel"].get("real_erp") is False


def test_data_freshness_truthful_labels():
    freshness = ops_health_service.get_feed_freshness()
    assert "Demo CSV" in freshness["inventory"]["label"]
    assert "Demo CSV" in freshness["sales"]["label"]
    assert freshness["inventory"]["source_type"] == "demo_csv"
    assert freshness["sales"]["status"] in {"healthy", "stale", "unavailable"}
    assert freshness["inventory"]["status"] in {"healthy", "stale", "unavailable"}


def test_stale_inventory_feed_blocks_recommendation_disposition(monkeypatch):
    policy_service.ensure_default_policy()

    monkeypatch.setattr(
        "services.ops_health_service.inventory_feed_watermark",
        lambda data_dir=None: datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    analysis = build_analysis("ST001", "SKU-1002")
    result = policy_service.evaluate_replenishment_policy(
        product=analysis["product"],
        inventory=analysis["inventory"],
        forecast=analysis["forecast"],
        replenishment=analysis["replenishment"],
        risk=analysis["risk"],
        confidence=0.95,
        history_days=30,
        order_value=100,
    )
    assert result.disposition == "blocked"
    assert "inventory_data_source" in result.failed_rules
    rule = next(r for r in result.evaluated_rules if r.rule_name == "inventory_data_source")
    assert rule.action == "blocked"
    assert rule.result == "fail"


def test_stale_sales_feed_blocks_recommendation_disposition(monkeypatch):
    policy_service.ensure_default_policy()

    monkeypatch.setattr(
        "services.ops_health_service.sales_feed_watermark",
        lambda data_dir=None: datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    analysis = build_analysis("ST001", "SKU-1002")
    result = policy_service.evaluate_replenishment_policy(
        product=analysis["product"],
        inventory=analysis["inventory"],
        forecast=analysis["forecast"],
        replenishment=analysis["replenishment"],
        risk=analysis["risk"],
        confidence=0.95,
        history_days=30,
        order_value=100,
    )
    assert result.disposition == "blocked"
    assert "sales_data_source" in result.failed_rules
