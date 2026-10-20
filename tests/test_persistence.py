"""PostgreSQL-compatible persistence, ownership, and uniqueness tests (SQLite)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from database.connection import (
    database_healthcheck,
    get_engine,
    get_session,
    init_db,
    normalize_database_url,
    reset_engine,
)
from database.models import ApprovalRow, PurchaseOrderRow, RecommendationRow
from repositories import audit_repository
from services import (
    approval_service,
    human_review_service,
    purchase_order_service,
    recommendation_service,
)


def test_normalize_postgres_urls():
    assert normalize_database_url("postgres://u:p@h/db").startswith("postgresql+psycopg://")
    assert normalize_database_url("postgresql://u:p@h/db").startswith("postgresql+psycopg://")
    assert normalize_database_url("sqlite:///tmp.db") == "sqlite:///tmp.db"


def test_sqlite_remains_supported_for_tests():
    engine = get_engine()
    assert engine.dialect.name == "sqlite"
    health = database_healthcheck()
    assert health["ok"] is True


def test_workflow_tables_exist():
    engine = get_engine()
    tables = set(inspect(engine).get_table_names())
    assert {
        "recommendations",
        "human_reviews",
        "approvals",
        "purchase_orders",
        "erp_outbox",
        "audit_events",
        "agent_run_states",
    }.issubset(tables)


def test_recommendation_persists_ownership_and_survives_engine_reset(tmp_path, monkeypatch):
    db_path = tmp_path / "persist.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr("config.DATABASE_URL", url)
    monkeypatch.setattr("database.connection.DATABASE_URL", url)
    reset_engine()
    init_db(url)

    rec = recommendation_service.create_recommendation_record(
        "ST001",
        "SKU-1001",
        rationale="owned",
        user_id="user-a",
        session_id="sess-1",
    )
    assert rec.user_id == "user-a"
    assert rec.session_id == "sess-1"

    reset_engine()
    monkeypatch.setattr("database.connection.DATABASE_URL", url)
    init_db(url)
    loaded = recommendation_service.get_recommendation(rec.recommendation_id)
    assert loaded["recommendation_id"] == rec.recommendation_id
    assert loaded["user_id"] == "user-a"
    assert loaded["session_id"] == "sess-1"
    assert loaded["agent_recommended_quantity"] == rec.agent_recommended_quantity


def test_unique_approval_per_review():
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="t", user_id="u1", session_id="s1"
    )
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="use_agent",
        submitted_by="alex.store",
        user_id="u1",
        session_id="s1",
    )
    a1 = approval_service.create_approval_request(
        review_id=review.review_id, user_id="u1", session_id="s1"
    )
    a2 = approval_service.create_approval_request(
        review_id=review.review_id, user_id="u1", session_id="s1"
    )
    assert a1.approval_id == a2.approval_id

    from sqlalchemy.orm import Session

    with Session(get_engine()) as session:
        with pytest.raises(IntegrityError):
            session.add(
                ApprovalRow(
                    approval_id="APR-duplicate-test",
                    review_id=review.review_id,
                    recommendation_id=rec.recommendation_id,
                    agent_recommended_quantity=review.agent_recommended_quantity,
                    human_proposed_quantity=review.human_proposed_quantity,
                    approved_final_quantity=None,
                    required_role="store_manager",
                    status="pending",
                    requested_at=datetime.now(timezone.utc),
                    user_id="u1",
                    session_id="s1",
                )
            )
            session.flush()
            session.rollback()


def test_unique_purchase_order_and_idempotency_key():
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="t", user_id="u2", session_id="s2"
    )
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="use_agent",
        submitted_by="jamie.planner",
        user_id="u2",
        session_id="s2",
    )
    approval = approval_service.create_approval_request(review_id=review.review_id)
    decided = approval_service.decide_approval(
        approval_id=approval.approval_id,
        decision="approve",
        actor="casey.category",
        actor_role="category_manager",
    )
    po1 = purchase_order_service.create_mock_purchase_order(
        decided.approval_id, user_id="u2", session_id="s2"
    )
    po2 = purchase_order_service.create_mock_purchase_order(
        decided.approval_id, user_id="u2", session_id="s2"
    )
    assert po1.purchase_order_id == po2.purchase_order_id
    assert po1.idempotency_key == f"po:{decided.approval_id}"

    from sqlalchemy.orm import Session

    with Session(get_engine()) as session:
        with pytest.raises(IntegrityError):
            session.add(
                PurchaseOrderRow(
                    purchase_order_id="PO-DUP",
                    approval_id=decided.approval_id,
                    store_id=rec.store_id,
                    sku=rec.sku,
                    agent_recommended_quantity=po1.agent_recommended_quantity,
                    human_proposed_quantity=po1.human_proposed_quantity,
                    approved_final_quantity=po1.approved_final_quantity,
                    override_used=False,
                    override_reason=None,
                    status="pending_erp",
                    order_status="pending_erp",
                    lines_json="[]",
                    created_at=datetime.now(timezone.utc),
                    idempotency_key="different-key-same-approval",
                    user_id="u2",
                    session_id="s2",
                )
            )
            session.flush()
            session.rollback()


def test_agent_run_state_persists_with_ownership():
    with get_session() as session:
        audit_repository.save_agent_run_state(
            session,
            run_id="RUN-persist-1",
            state_json='{"paused": true}',
            status="paused",
            recommendation_id="REC-x",
            approval_id="APR-x",
            user_id="user-z",
            session_id="sess-z",
            idempotency_key="order:APR-x",
            pending_tool_name="create_mock_purchase_order",
            pending_tool_args={"approval_id": "APR-x"},
        )
        row = audit_repository.get_agent_run_state(session, "RUN-persist-1")
        assert row is not None
        assert row.user_id == "user-z"
        assert row.session_id == "sess-z"
        assert row.idempotency_key == "order:APR-x"


def test_ownership_columns_present_on_recommendation_table():
    engine = get_engine()
    cols = {c["name"] for c in inspect(engine).get_columns("recommendations")}
    assert {"user_id", "session_id"}.issubset(cols)
    # Ensure ORM model exposes ownership too
    assert hasattr(RecommendationRow, "user_id")
    assert hasattr(RecommendationRow, "session_id")
