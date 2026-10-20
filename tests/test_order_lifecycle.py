"""Checkpoint 6 — Order lifecycle (OrderIntent → ERP)."""

from __future__ import annotations

from database.connection import get_session
from repositories import order_intent_repository, purchase_order_repository
from services import (
    batch_run_service,
    disposition_service,
    erp_service,
    order_lifecycle_service,
    policy_service,
    purchase_order_service,
    queue_service,
)


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
            ("ST001", "SKU-1005"),
        ],
        trigger_type="manual",
        initiated_by="alex.store",
        user_id="alex.store",
        session_id="sess-lifecycle",
    )


def _approve_one_human(run: dict) -> str:
    human_id = next(
        i["recommendation_id"]
        for i in run["items"]
        if i.get("disposition") == "human_review" and i.get("recommendation_id")
    )
    disposition_service.approve_recommendation(
        recommendation_id=human_id,
        actor="alex.store",
        actor_role="store_manager",
        user_id="alex.store",
        session_id="sess-lifecycle",
    )
    return human_id


def test_approved_queues_pending_erp_not_transmitted(monkeypatch):
    run = _seed_mixed(monkeypatch)
    human_id = _approve_one_human(run)

    with get_session() as session:
        intent = order_intent_repository.get_by_recommendation(session, human_id)
        po = purchase_order_repository.get_purchase_order_by_recommendation(
            session, human_id
        )
    assert intent is not None
    assert intent.status == "queued_for_erp"
    assert intent.transmitted_at is None
    assert intent.mock_erp_reference is None
    assert po is not None
    assert po.order_status == "queued_for_erp"
    assert po.transmission_status == "draft"
    assert po.transmitted_at is None


def test_transmit_order_success_returns_realistic_erp_payload(monkeypatch):
    run = _seed_mixed(monkeypatch)
    human_id = _approve_one_human(run)
    with get_session() as session:
        intent = order_intent_repository.get_by_recommendation(session, human_id)
    assert intent is not None

    erp_service.reset_erp_adapter()
    result = order_lifecycle_service.transmit_order_to_erp(
        order_intent_id=intent.order_intent_id,
        actor="alex.store",
        actor_role="store_manager",
    )
    assert result["outcome"] == "transmitted"
    assert result["status"] == "completed"
    erp = result["erp"]
    assert erp["purchase_order_id"]
    assert erp["transmitted_at"]
    assert erp["vendor"]
    assert erp["lines"]
    assert erp["amount"] is not None
    assert erp["status"] in {"completed", "transmitted"}
    assert erp["mock_erp_reference"]
    assert str(erp["mock_erp_reference"]).startswith("ERP-MOCK-")

    with get_session() as session:
        refreshed = order_intent_repository.get_order_intent(
            session, intent.order_intent_id
        )
        po = purchase_order_repository.get_purchase_order(
            session, intent.purchase_order_id
        )
    assert refreshed is not None and refreshed.status == "completed"
    assert po is not None and po.order_status == "completed"
    assert po.transmission_status == "sent"


def test_transmit_order_failure(monkeypatch):
    run = _seed_mixed(monkeypatch)
    human_id = _approve_one_human(run)
    with get_session() as session:
        intent = order_intent_repository.get_by_recommendation(session, human_id)
    assert intent is not None

    monkeypatch.setattr(
        "services.erp_service.get_erp_adapter",
        lambda force_new=False: erp_service.MockErpAdapter(force_fail=True),
    )
    monkeypatch.setattr(
        "services.erp_service.transmit_purchase_order_payload",
        lambda payload: erp_service.MockErpAdapter(force_fail=True).transmit(payload),
    )

    result = order_lifecycle_service.transmit_order_to_erp(
        order_intent_id=intent.order_intent_id,
        actor="alex.store",
        actor_role="store_manager",
    )
    assert result["outcome"] in {"failed", "retry_pending"}
    assert result["status"] in {"failed", "transmission_failed", "retry_pending"}
    assert result["error"]

    with get_session() as session:
        refreshed = order_intent_repository.get_order_intent(
            session, intent.order_intent_id
        )
    assert refreshed is not None
    assert refreshed.status in {"failed", "transmission_failed", "retry_pending"}


def test_retry_after_failure(monkeypatch):
    run = _seed_mixed(monkeypatch)
    human_id = _approve_one_human(run)
    with get_session() as session:
        intent = order_intent_repository.get_by_recommendation(session, human_id)
    assert intent is not None

    monkeypatch.setattr(
        "services.erp_service.transmit_purchase_order_payload",
        lambda payload: erp_service.MockErpAdapter(force_fail=True).transmit(payload),
    )
    failed = order_lifecycle_service.transmit_order_to_erp(
        order_intent_id=intent.order_intent_id,
        actor="alex.store",
        actor_role="store_manager",
    )
    assert failed["outcome"] in {"failed", "retry_pending"}

    monkeypatch.setattr(
        "services.erp_service.transmit_purchase_order_payload",
        lambda payload: erp_service.MockErpAdapter(force_fail=False).transmit(payload),
    )
    retried = order_lifecycle_service.retry_failed_order(
        order_intent_id=intent.order_intent_id,
        actor="alex.store",
        actor_role="store_manager",
    )
    assert retried["outcome"] == "transmitted"
    assert retried["erp"]["mock_erp_reference"]


def test_duplicate_prevention_same_approval(monkeypatch):
    run = _seed_mixed(monkeypatch)
    human_id = _approve_one_human(run)

    with get_session() as session:
        intent = order_intent_repository.get_by_recommendation(session, human_id)
    assert intent is not None
    first_po = intent.purchase_order_id

    again = order_lifecycle_service.queue_approved_order(
        approval_id=intent.approval_id,
        actor="alex.store",
        actor_role="store_manager",
    )
    assert again["outcome"] == "already_queued"
    assert again["purchase_order_id"] == first_po

    # create_mock_purchase_order must not mint a second PO
    po1 = purchase_order_service.create_mock_purchase_order(
        intent.approval_id,
        actor="alex.store",
        actor_role="store_manager",
    )
    po2 = purchase_order_service.create_mock_purchase_order(
        intent.approval_id,
        actor="alex.store",
        actor_role="store_manager",
    )
    assert po1.purchase_order_id == po2.purchase_order_id == first_po

    with get_session() as session:
        for_rec = [
            p
            for p in purchase_order_repository.list_purchase_orders(session, limit=100)
            if p.recommendation_id == human_id
        ]
    assert len(for_rec) == 1


def test_approved_today_released_by_labels(monkeypatch):
    run = _seed_mixed(monkeypatch)
    _approve_one_human(run)
    approved = queue_service.get_approved_today(run_id=run["run_id"])
    assert approved["summary"]["human_approved"] >= 1
    assert approved["summary"]["auto_released"] >= 1

    human_rows = [r for r in approved["rows"] if r["source"] == "Human approved"]
    auto_rows = [r for r in approved["rows"] if r["source"] == "Auto-released"]
    assert all(r["released_by"] == "Alex Store Manager" for r in human_rows)
    assert all(r["released_by"] == "Agent — Within Policy" for r in auto_rows)


def test_mock_erp_payload_shape():
    erp_service.reset_erp_adapter()
    result = erp_service.transmit_purchase_order_payload(
        {
            "purchase_order_id": "PO-SHAPE",
            "store_id": "ST001",
            "sku": "SKU-1002",
            "approved_final_quantity": 8,
            "vendor": "Demo Vendor Co.",
            "unit_cost": 2.5,
            "amount": 20.0,
            "lines": [
                {
                    "line_number": 1,
                    "sku": "SKU-1002",
                    "store_id": "ST001",
                    "quantity": 8,
                    "unit_cost": 2.5,
                    "line_amount": 20.0,
                }
            ],
        }
    )
    assert result.ok
    raw = result.raw
    for key in (
        "purchase_order_id",
        "transmitted_at",
        "vendor",
        "lines",
        "amount",
        "status",
        "mock_erp_reference",
    ):
        assert key in raw
