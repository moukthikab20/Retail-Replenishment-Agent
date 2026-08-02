"""Multi-user isolation, rate limits, idempotency, and demo reset tests."""

from __future__ import annotations

import pytest

from database.connection import get_session, init_db, reset_engine
from services import (
    approval_service,
    auth_service,
    human_review_service,
    purchase_order_service,
    recommendation_service,
)
from services.demo_data_service import reset_and_seed, reset_demo_workflow_data, seed_demo_data
from services.errors import AppError, RateLimitError, user_facing_error
from services.isolation_service import can_access_recommendation
from services.rate_limit_service import assert_within_agent_run_limit, count_recommendations_for_user


def test_separate_user_sessions_own_recommendations():
    a = recommendation_service.create_recommendation_record(
        "ST001",
        "SKU-1001",
        rationale="user-a",
        user_id="alex.store",
        session_id="SESS-A",
    )
    b = recommendation_service.create_recommendation_record(
        "ST002",
        "SKU-1002",
        rationale="user-b",
        user_id="jamie.planner",
        session_id="SESS-B",
    )
    assert a.recommendation_id != b.recommendation_id
    a_list = recommendation_service.list_recommendations_for_user("alex.store")
    b_list = recommendation_service.list_recommendations_for_user("jamie.planner")
    assert {row["recommendation_id"] for row in a_list} == {a.recommendation_id}
    assert {row["recommendation_id"] for row in b_list} == {b.recommendation_id}
    assert a.session_id == "SESS-A"
    assert b.session_id == "SESS-B"


def test_concurrent_recommendations_from_two_users():
    first = recommendation_service.create_recommendation_record(
        "ST001",
        "SKU-1001",
        rationale="concurrent-1",
        user_id="user-1",
        session_id="s1",
    )
    second = recommendation_service.create_recommendation_record(
        "ST001",
        "SKU-1001",
        rationale="concurrent-2",
        user_id="user-2",
        session_id="s2",
    )
    assert first.recommendation_id != second.recommendation_id
    assert first.agent_recommended_quantity == second.agent_recommended_quantity
    assert count_recommendations_for_user("user-1") == 1
    assert count_recommendations_for_user("user-2") == 1


def test_viewer_cannot_access_other_users_recommendation():
    rec = recommendation_service.create_recommendation_record(
        "ST001",
        "SKU-1001",
        rationale="owned",
        user_id="alex.store",
        session_id="s-alex",
    )
    data = recommendation_service.get_recommendation(rec.recommendation_id)
    assert can_access_recommendation(data, user_id="riley.viewer", role="viewer") is False
    with pytest.raises(AppError):
        recommendation_service.get_recommendation(
            rec.recommendation_id,
            user_id="riley.viewer",
            role="viewer",
            check_access=True,
        )


def test_approver_can_access_peer_recommendation_for_review():
    rec = recommendation_service.create_recommendation_record(
        "ST001",
        "SKU-1001",
        rationale="peer",
        user_id="alex.store",
        session_id="s-alex",
    )
    data = recommendation_service.get_recommendation(
        rec.recommendation_id,
        user_id="jamie.planner",
        role="inventory_planner",
        check_access=True,
    )
    assert data["recommendation_id"] == rec.recommendation_id


def test_duplicate_approval_and_order_protection():
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="dup", user_id="u", session_id="s"
    )
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="use_agent",
        submitted_by="alex.store",
        actor_role="store_manager",
        user_id="alex.store",
        session_id="s",
    )
    a1 = approval_service.create_approval_request(
        review_id=review.review_id, actor="alex.store", actor_role="store_manager"
    )
    a2 = approval_service.create_approval_request(
        review_id=review.review_id, actor="alex.store", actor_role="store_manager"
    )
    assert a1.approval_id == a2.approval_id

    decided = approval_service.decide_approval(
        approval_id=a1.approval_id,
        decision="approve",
        actor="alex.store",
        actor_role="store_manager",
    )
    with pytest.raises(ValueError, match="Duplicate"):
        approval_service.decide_approval(
            approval_id=a1.approval_id,
            decision="approve",
            actor="alex.store",
            actor_role="store_manager",
        )

    po1 = purchase_order_service.create_mock_purchase_order(
        decided.approval_id, actor="alex.store", actor_role="store_manager"
    )
    po2 = purchase_order_service.create_mock_purchase_order(
        decided.approval_id, actor="alex.store", actor_role="store_manager"
    )
    assert po1.purchase_order_id == po2.purchase_order_id


def test_persistence_after_engine_restart(tmp_path, monkeypatch):
    db_path = tmp_path / "multiuser_persist.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr("config.DATABASE_URL", url)
    monkeypatch.setattr("database.connection.DATABASE_URL", url)
    reset_engine()
    init_db(url)

    rec = recommendation_service.create_recommendation_record(
        "ST001",
        "SKU-1001",
        rationale="persist-me",
        user_id="persist-user",
        session_id="persist-sess",
    )
    reset_engine()
    monkeypatch.setattr("database.connection.DATABASE_URL", url)
    init_db(url)
    loaded = recommendation_service.get_recommendation(rec.recommendation_id)
    assert loaded["user_id"] == "persist-user"
    assert loaded["session_id"] == "persist-sess"
    assert loaded["agent_recommended_quantity"] == rec.agent_recommended_quantity


def test_rate_limit_blocks_excess_runs(monkeypatch):
    monkeypatch.setattr("services.rate_limit_service.MAX_AGENT_RUNS_PER_USER_PER_HOUR", 2)
    monkeypatch.setattr("config.MAX_AGENT_RUNS_PER_USER_PER_HOUR", 2)
    user_id = "rate-limited-user"
    recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="r1", user_id=user_id, session_id="s"
    )
    recommendation_service.create_recommendation_record(
        "ST001", "SKU-1002", rationale="r2", user_id=user_id, session_id="s"
    )
    with pytest.raises(RateLimitError):
        assert_within_agent_run_limit(user_id)
    with pytest.raises(RateLimitError):
        recommendation_service.create_recommendation_record(
            "ST002", "SKU-1001", rationale="r3", user_id=user_id, session_id="s"
        )


def test_admin_reset_and_idempotent_seed():
    recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="to-clear", user_id="x", session_id="y"
    )
    with pytest.raises(auth_service.AuthError):
        reset_demo_workflow_data(actor="alex.store", actor_role="store_manager")

    result = reset_and_seed(actor="admin.demo", actor_role="administrator")
    assert result["reset"]["status"] == "reset"
    assert result["seed"]["status"] == "seeded"
    again = seed_demo_data(force=False)
    assert again["status"] == "skipped"


def test_user_facing_error_hides_secrets():
    message = user_facing_error(ValueError("bad OPENAI_API_KEY=sk-secret"))
    assert "sk-secret" not in message
    assert "configuration" in message.lower() or "wrong" in message.lower() or "error" in message.lower()
