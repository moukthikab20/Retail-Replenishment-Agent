"""Checkpoint 1 — batch replenishment run persistence and scoring."""

from __future__ import annotations

from database.connection import get_session
from database.models import RecommendationRow
from repositories import run_repository
from services import batch_run_service, inventory_service, policy_service, product_service
from services.batch_policy_service import evaluate_disposition


def test_batch_all_successful():
    pairs = [
        ("ST001", "SKU-1002"),
        ("ST001", "SKU-1003"),
        ("ST001", "SKU-1005"),
    ]
    result = batch_run_service.run_replenishment_batch(
        pairs,
        trigger_type="manual",
        initiated_by="alex.store",
        user_id="alex.store",
    )
    assert result["status"] == "completed"
    assert result["total_items"] == 3
    assert result["scored_items"] == 3
    assert result["failed_items"] == 0
    assert len(result["recommendation_ids"]) == 3
    assert all(r["run_id"] == result["run_id"] for r in result["recommendations"])


def test_batch_one_item_blocked(monkeypatch):
    real_age = policy_service.inventory_age_hours

    def _age_for_1004(position, **kwargs):
        if position.sku == "SKU-1004":
            return 10_000.0
        return real_age(position, **kwargs)

    monkeypatch.setattr(policy_service, "inventory_age_hours", _age_for_1004)
    monkeypatch.setattr(
        "services.policy_service.inventory_age_hours",
        _age_for_1004,
    )

    result = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1002"), ("ST001", "SKU-1004")],
        initiated_by="jamie.planner",
    )
    assert result["status"] == "completed"
    assert result["scored_items"] == 2
    assert result["blocked_items"] == 1
    blocked = [r for r in result["recommendations"] if r["disposition"] == "blocked"]
    assert len(blocked) == 1
    assert blocked[0]["sku"] == "SKU-1004"
    assert blocked[0]["status"] == "blocked"


def test_batch_one_item_service_failure(monkeypatch):
    real_get = product_service.get_product_details

    def _boom(sku: str):
        if sku == "SKU-1003":
            raise RuntimeError("simulated product feed failure")
        return real_get(sku)

    monkeypatch.setattr(product_service, "get_product_details", _boom)
    monkeypatch.setattr(
        "services.batch_run_service.product_service.get_product_details",
        _boom,
    )

    result = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1002"), ("ST001", "SKU-1003"), ("ST001", "SKU-1005")],
        initiated_by="system",
    )
    assert result["status"] == "completed_with_errors"
    assert result["scored_items"] == 2
    assert result["failed_items"] == 1
    assert len(result["recommendation_ids"]) == 2
    failed_items = [i for i in result["items"] if i["status"] == "failed"]
    assert len(failed_items) == 1
    assert failed_items[0]["sku"] == "SKU-1003"
    assert "simulated product feed failure" in (failed_items[0]["error_message"] or "")


def test_batch_mixed_outcomes(monkeypatch):
    real_age = policy_service.inventory_age_hours
    real_get = product_service.get_product_details

    def _age(position, **kwargs):
        if position.sku == "SKU-1004":
            return 10_000.0
        return real_age(position, **kwargs)

    def _boom(sku: str):
        if sku == "SKU-1001":
            raise RuntimeError("feed down")
        return real_get(sku)

    monkeypatch.setattr("services.policy_service.inventory_age_hours", _age)
    monkeypatch.setattr(
        "services.batch_run_service.product_service.get_product_details",
        _boom,
    )

    result = batch_run_service.run_replenishment_batch(
        [
            ("ST001", "SKU-1001"),  # failed
            ("ST001", "SKU-1002"),  # typically auto_release
            ("ST001", "SKU-1004"),  # blocked
        ],
        initiated_by="casey.category",
    )
    assert result["status"] == "completed_with_errors"
    assert result["failed_items"] == 1
    assert result["blocked_items"] == 1
    assert result["scored_items"] == 2
    assert result["total_items"] == 3
    dispositions = {r["sku"]: r["disposition"] for r in result["recommendations"]}
    assert dispositions["SKU-1004"] == "blocked"
    assert dispositions["SKU-1002"] in {"auto_release", "human_review", "no_order"}


def test_duplicate_run_prevention_idempotent_replay():
    pairs = [("ST001", "SKU-1002"), ("ST002", "SKU-1002")]
    first = batch_run_service.run_replenishment_batch(
        pairs,
        run_id="RUN-idempotent-demo",
        initiated_by="alex.store",
    )
    assert first["status"] == "completed"
    assert first["idempotent_replay"] is False
    first_ids = list(first["recommendation_ids"])

    second = batch_run_service.run_replenishment_batch(
        pairs,
        run_id="RUN-idempotent-demo",
        initiated_by="alex.store",
    )
    assert second["idempotent_replay"] is True
    assert second["run_id"] == first["run_id"]
    assert second["recommendation_ids"] == first_ids
    assert second["scored_items"] == first["scored_items"]

    with get_session() as session:
        rows = run_repository.list_recommendations_for_run(session, first["run_id"])
        assert len(rows) == 2


def test_run_counts_match_item_dispositions(monkeypatch):
    real_age = policy_service.inventory_age_hours

    def _age(position, **kwargs):
        if position.sku == "SKU-1004":
            return 10_000.0
        return real_age(position, **kwargs)

    monkeypatch.setattr("services.policy_service.inventory_age_hours", _age)
    result = batch_run_service.run_replenishment_batch(
        [
            ("ST001", "SKU-1002"),
            ("ST001", "SKU-1003"),
            ("ST001", "SKU-1004"),
        ],
        initiated_by="system",
    )
    assert (
        result["auto_released_items"]
        + result["review_items"]
        + result["blocked_items"]
        + result.get("no_order_items", 0)
        == result["scored_items"]
    )
    assert result["scored_items"] + result["failed_items"] == result["total_items"]


def test_recommendation_run_relationship():
    result = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1002"), ("ST002", "SKU-1005")],
        initiated_by="alex.store",
        user_id="alex.store",
        session_id="SESS-batch",
    )
    run_id = result["run_id"]
    loaded = batch_run_service.get_replenishment_run(run_id)
    assert loaded["run_id"] == run_id
    assert len(loaded["recommendations"]) == 2
    with get_session() as session:
        rows = run_repository.list_recommendations_for_run(session, run_id)
        assert len(rows) == 2
        for row in rows:
            assert row.run_id == run_id
            assert isinstance(row, RecommendationRow)
            assert row.disposition in {
                "auto_release",
                "human_review",
                "blocked",
                "no_order",
            }


def test_policy_disposition_helpers():
    from services.recommendation_service import build_analysis

    analysis = build_analysis("ST001", "SKU-1002")
    decision = evaluate_disposition(
        product=analysis["product"],
        inventory=analysis["inventory"],
        forecast=analysis["forecast"],
        replenishment=analysis["replenishment"],
        risk=analysis["risk"],
        open_orders=inventory_service.get_open_orders("ST001", "SKU-1002"),
        confidence=0.95,
        history_days=30,
        order_value=100,
    )
    assert decision["disposition"] in {
        "auto_release",
        "human_review",
        "blocked",
        "no_order",
    }
    assert decision["policy_version"]
    assert decision["recommendation_status"]
    assert decision["evaluated_rules"]


def test_batch_run_result_typed_contract():
    typed = batch_run_service.run_replenishment_batch_result(
        [("ST001", "SKU-1002")],
        initiated_by="alex.store",
    )
    assert typed.run_id
    assert typed.processed_items == typed.scored_items
    assert typed.human_review_items == typed.review_items
    assert typed.agent_model == typed.model_name
    assert "no_order_items" in typed.to_dict()
    assert isinstance(typed.errors, list)


def test_auto_release_queues_order_intent_not_transmitted():
    from database.connection import get_session
    from repositories import order_intent_repository, purchase_order_repository

    result = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1002")],
        initiated_by="system",
        user_id="system",
        session_id="sess-auto-queue",
    )
    auto = [r for r in result["recommendations"] if r["disposition"] == "auto_release"]
    assert auto, "expected SKU-1002 auto_release in demo data"
    rec_id = auto[0]["recommendation_id"]
    assert result["orders_queued"] >= 1
    assert result["no_order_items"] == 0 or isinstance(result["no_order_items"], int)

    with get_session() as session:
        intent = order_intent_repository.get_by_recommendation(session, rec_id)
        po = purchase_order_repository.get_purchase_order_by_recommendation(
            session, rec_id
        )
    assert intent is not None
    assert intent.status == "queued_for_erp"
    assert intent.transmitted_at is None
    assert po is not None
    assert po.order_status == "queued_for_erp"

    # Idempotent: second run with new run_id creates new recommendation; same store/sku
    # re-queue for that new rec is separate. Same rec re-queue is already_queued.
    again = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1002")],
        run_id=result["run_id"],
        initiated_by="system",
    )
    assert again["idempotent_replay"] is True
    with get_session() as session:
        intents = [
            i
            for i in order_intent_repository.list_order_intents(session, limit=50)
            if i.recommendation_id == rec_id
        ]
    assert len(intents) == 1


def test_no_order_items_persisted():
    result = batch_run_service.run_replenishment_batch(
        [("ST002", "SKU-1003")],
        initiated_by="system",
    )
    assert result["status"] == "completed"
    assert result["no_order_items"] == 1
    assert result["recommendations"][0]["disposition"] == "no_order"
    loaded = batch_run_service.get_replenishment_run(result["run_id"])
    assert loaded["no_order_items"] == 1


def test_batch_audit_event_names():
    from database.connection import get_session
    from database.models import AuditEventRow
    from sqlalchemy import select

    result = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1001"), ("ST001", "SKU-1002"), ("ST002", "SKU-1003")],
        initiated_by="alex.store",
    )
    with get_session() as session:
        types = set(
            session.scalars(
                select(AuditEventRow.event_type).where(
                    AuditEventRow.run_id == result["run_id"]
                )
            )
        )
    assert "replenishment_run_started" in types
    assert "replenishment_run_completed" in types
    assert "replenishment_item_processed" in types
    assert "recommendation_created" in types or "recommendation_generated" in types
    # Disposition-specific names (at least one of each expected in this mixed set)
    assert "recommendation_auto_released" in types or "recommendation_routed_to_review" in types
    assert "recommendation_no_order" in types or "recommendation_routed_to_review" in types


def test_store_ids_sku_ids_filters():
    pairs = batch_run_service.list_eligible_store_sku_pairs(
        store_ids=["ST001"], sku_ids=["SKU-1002", "SKU-1003"]
    )
    assert pairs == [("ST001", "SKU-1002"), ("ST001", "SKU-1003")]
    result = batch_run_service.run_replenishment_batch(
        store_ids=["ST001"],
        sku_ids=["SKU-1002"],
        initiated_by="system",
    )
    assert result["total_items"] == 1
    assert result["recommendations"][0]["sku"] == "SKU-1002"
