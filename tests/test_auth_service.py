"""Demo authentication and role authorization tests."""

from __future__ import annotations

import pytest

from services import (
    approval_service,
    auth_service,
    human_review_service,
    purchase_order_service,
    recommendation_service,
)


def test_named_user_workspace_selection(monkeypatch):
    monkeypatch.setattr("config.APP_ENV", "production")
    monkeypatch.setattr("integrations.auth.demo_provider.APP_ENV", "production")
    monkeypatch.setattr("services.auth_service.APP_ENV", "production")
    with pytest.raises(auth_service.AuthError):
        auth_service.authenticate(user_id="unknown.user")
    identity = auth_service.select_demo_user("alex.store")
    assert identity["user_id"] == "alex.store"
    assert identity["role"] == "store_manager"
    assert identity["session_id"].startswith("SESS-")
    assert identity.get("session_token")
    assert identity.get("authentication_source") == "demo"
    # Access codes are ignored if still passed by legacy callers.
    legacy = auth_service.authenticate("anything", "jamie.planner")
    assert legacy["user_id"] == "jamie.planner"


def test_demo_users_include_all_required_roles():
    roles = {u.role for u in auth_service.list_demo_users()}
    assert roles == {
        "viewer",
        "store_manager",
        "inventory_planner",
        "category_manager",
        "administrator",
    }


def test_public_auth_config_does_not_expose_access_code():
    payload = auth_service.public_auth_config()
    dumped = str(payload).lower()
    assert "access_code" not in dumped or "access_code_configured" in dumped
    assert "infolob-demo" not in dumped
    assert "openai" not in dumped


def test_viewer_cannot_run_or_approve():
    assert auth_service.can_view("viewer") is True
    assert auth_service.can_run_analysis("viewer") is False
    assert auth_service.can_submit_human_review("viewer") is False
    assert auth_service.can_approve("viewer", "store_manager") is False
    assert auth_service.can_reset_demo("viewer") is False
    assert auth_service.can_reset_demo("administrator") is True


def test_role_based_approval_hierarchy():
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="auth", user_id="u", session_id="s"
    )
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="manual",
        human_proposed_quantity=0,
        override_reason="no order",
        submitted_by="jamie.planner",
        actor_role="inventory_planner",
        user_id="jamie.planner",
        session_id="s",
    )
    approval = approval_service.create_approval_request(
        review_id=review.review_id,
        actor="jamie.planner",
        actor_role="inventory_planner",
    )
    assert approval.required_role == "category_manager"

    with pytest.raises(auth_service.AuthError):
        approval_service.decide_approval(
            approval_id=approval.approval_id,
            decision="approve",
            actor="alex.store",
            actor_role="store_manager",
        )

    decided = approval_service.decide_approval(
        approval_id=approval.approval_id,
        decision="approve",
        actor="casey.category",
        actor_role="category_manager",
    )
    assert decided.status == "approved"


def test_viewer_cannot_submit_review_or_create_order():
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="viewer-block"
    )
    with pytest.raises(auth_service.AuthError):
        human_review_service.submit_human_review(
            recommendation_id=rec.recommendation_id,
            choice="use_agent",
            submitted_by="riley.viewer",
            actor_role="viewer",
        )

    # Prepare an approved approval as a privileged user, then block viewer PO create
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="use_agent",
        submitted_by="alex.store",
        actor_role="store_manager",
    )
    approval = approval_service.create_approval_request(
        review_id=review.review_id,
        actor="alex.store",
        actor_role="store_manager",
    )
    approval_service.decide_approval(
        approval_id=approval.approval_id,
        decision="approve",
        actor="alex.store",
        actor_role="store_manager",
    )
    with pytest.raises(auth_service.AuthError):
        purchase_order_service.create_mock_purchase_order(
            approval.approval_id,
            actor="riley.viewer",
            actor_role="viewer",
        )


def test_administrator_satisfies_elevated_approval():
    assert auth_service.can_approve("administrator", "category_manager") is True
    assert auth_service.role_satisfies("administrator", "store_manager") is True
