"""Production Authentication / RBAC checkpoint tests."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from agent.runner import analyze_replenishment, resume_order_run, start_order_agent_after_approval
from database.connection import get_session
from integrations.auth.factory import validate_auth_provider_configuration
from integrations.failures import ProviderConfigError
from repositories import audit_repository
from services import (
    agent_ops_service,
    approval_service,
    auth_service,
    human_review_service,
    recommendation_service,
    scheduler_service,
)
from services.audit_service import infer_actor_type, record_event


def _patch_demo_code(monkeypatch, code: str = "secret-demo") -> None:
    # Access codes are unused for workspace selection; keep env patches for legacy callers.
    monkeypatch.setattr("config.DEMO_ACCESS_CODE", code)
    monkeypatch.setattr("integrations.auth.demo_provider.DEMO_ACCESS_CODE", code)
    monkeypatch.setattr("config.APP_ENV", "production")
    monkeypatch.setattr("integrations.auth.demo_provider.APP_ENV", "production")
    monkeypatch.setattr("services.auth_service.APP_ENV", "production")


def test_demo_login_issues_signed_session(monkeypatch):
    _patch_demo_code(monkeypatch)
    token, identity = auth_service.login(user_id="alex.store")
    assert identity.user_id == "alex.store"
    assert identity.role == "store_manager"
    assert identity.authentication_source == "demo"
    assert identity.session_id
    assert "." in token
    validated = auth_service.validate_session(token)
    assert validated.user_id == "alex.store"
    assert validated.role == "store_manager"


def test_invalid_login_rejected(monkeypatch):
    _patch_demo_code(monkeypatch)
    with pytest.raises(auth_service.AuthError):
        auth_service.login(user_id="unknown.user")
    with pytest.raises(auth_service.AuthError):
        auth_service.login(user_id=None)


def test_session_expiry_invalidates_token(monkeypatch):
    _patch_demo_code(monkeypatch)
    monkeypatch.setattr("integrations.auth.session_store.SESSION_TTL_MINUTES", 1)
    token, _ = auth_service.login(user_id="riley.viewer")
    store = __import__(
        "integrations.auth.session_store", fromlist=["get_session_store"]
    ).get_session_store()
    session_id = token.rsplit(".", 1)[0]
    record = store._sessions[session_id]
    record.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    with pytest.raises(auth_service.AuthError):
        auth_service.validate_session(token)


def test_logout_invalidates_session(monkeypatch):
    _patch_demo_code(monkeypatch)
    token, identity = auth_service.login(user_id="jamie.planner")
    auth_service.logout(session_token=token)
    with pytest.raises(auth_service.AuthError):
        auth_service.validate_session(token)
    assert identity.session_id


def test_role_enforcement_helpers():
    assert auth_service.can_run_analysis("viewer") is False
    assert auth_service.can_run_analysis("store_manager") is True
    assert auth_service.can_view_agent_operations("viewer") is False
    assert auth_service.can_view_agent_operations("administrator") is True
    assert auth_service.can_view_administration("inventory_planner") is False
    assert auth_service.can_view_administration("administrator") is True
    with pytest.raises(auth_service.AuthError):
        auth_service.authorize_run_analysis("viewer")
    with pytest.raises(auth_service.AuthError):
        auth_service.authorize_agent_operations("store_manager")
    with pytest.raises(auth_service.AuthError):
        auth_service.authorize_administration("category_manager")


def test_analysis_authorization_server_side(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    with pytest.raises(auth_service.AuthError):
        analyze_replenishment(
            "ST001",
            "SKU-1001",
            actor="riley.viewer",
            actor_role="viewer",
            user_id="riley.viewer",
            session_id="s",
        )
    decision = analyze_replenishment(
        "ST001",
        "SKU-1001",
        actor="alex.store",
        actor_role="store_manager",
        user_id="alex.store",
        session_id="s",
    )
    assert decision.get("recommendation_id") or decision.get("status")


def test_hitl_authorization_blocks_viewer(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("agent.runner.OPENAI_API_KEY", "")
    rec = recommendation_service.create_recommendation_record(
        "ST001", "SKU-1001", rationale="hitl-auth"
    )
    review = human_review_service.submit_human_review(
        recommendation_id=rec.recommendation_id,
        choice="use_agent",
        submitted_by="alex.store",
        actor_role="store_manager",
        authentication_source="demo",
    )
    approval = approval_service.create_approval_request(
        review_id=review.review_id,
        actor="alex.store",
        actor_role="store_manager",
        authentication_source="demo",
    )
    approval_service.decide_approval(
        approval_id=approval.approval_id,
        decision="approve",
        actor="alex.store",
        actor_role="store_manager",
        authentication_source="demo",
    )
    paused = start_order_agent_after_approval(
        approval_id=approval.approval_id,
        recommendation_id=rec.recommendation_id,
        actor="alex.store",
        actor_role="store_manager",
    )
    with pytest.raises(auth_service.AuthError):
        resume_order_run(
            run_id=paused["run_id"],
            approve=True,
            actor="riley.viewer",
            actor_role="viewer",
        )


def test_agent_operations_authorization():
    with pytest.raises(auth_service.AuthError):
        agent_ops_service.list_agent_executions(limit=5, actor_role="viewer")
    with pytest.raises(auth_service.AuthError):
        agent_ops_service.get_operations_metrics(actor_role="store_manager")
    rows = agent_ops_service.list_agent_executions(limit=5, actor_role="administrator")
    assert isinstance(rows, list)
    metrics = agent_ops_service.get_operations_metrics(actor_role="administrator")
    assert "active_executions" in metrics


def test_administration_authorization():
    with pytest.raises(auth_service.AuthError):
        auth_service.authorize_administration("viewer")
    with pytest.raises(auth_service.AuthError):
        scheduler_service.run_now(
            actor="riley.viewer",
            actor_role="viewer",
            session_id="s",
        )
    auth_service.authorize_administration("administrator")


def test_secret_sanitization(monkeypatch):
    _patch_demo_code(monkeypatch, "ultra-secret-code")
    monkeypatch.setattr("config.SESSION_SECRET", "session-secret-value")
    public = auth_service.public_auth_config()
    dumped = str(public).lower()
    assert "ultra-secret-code" not in dumped
    assert "session-secret-value" not in dumped
    assert "infolob-demo" not in dumped

    from health import check_health

    health = check_health()
    health_dump = str(health)
    assert "ultra-secret-code" not in health_dump
    assert "session-secret-value" not in health_dump

    event_id = record_event(
        "recommendation_opened",
        actor="alex.store",
        actor_role="store_manager",
        session_id="SESS-test",
        authentication_source="demo",
        details={
            "demo_access_code": "ultra-secret-code",
            "session_secret": "session-secret-value",
            "access_code": "should-hide",
        },
    )
    with get_session() as session:
        row = audit_repository.get_audit_event(session, event_id)
        details = json.loads(row.details_json)
    assert details["demo_access_code"] == "[redacted]"
    assert details["session_secret"] == "[redacted]"
    assert details["access_code"] == "[redacted]"
    assert details["authentication_source"] == "demo"


def test_authenticated_audit_identity(monkeypatch):
    _patch_demo_code(monkeypatch)
    token, identity = auth_service.login(user_id="casey.category")
    fields = auth_service.audit_actor_fields(identity)
    assert fields["actor"] == "casey.category"
    assert fields["actor_role"] == "category_manager"
    assert fields["session_id"] == identity.session_id
    assert fields["authentication_source"] == "demo"
    event_id = record_event(
        "recommendation_opened",
        **{k: fields[k] for k in ("actor", "actor_role", "user_id", "session_id", "authentication_source")},
    )
    with get_session() as session:
        row = audit_repository.get_audit_event(session, event_id)
        details = json.loads(row.details_json)
    assert row.actor == "casey.category"
    assert row.actor_role == "category_manager"
    assert row.session_id == identity.session_id
    assert details.get("authentication_source") == "demo"
    auth_service.logout(session_token=token)


def test_scheduler_system_actors_not_human():
    assert infer_actor_type("scheduler") == "scheduler"
    assert infer_actor_type("agent") == "agent"
    assert infer_actor_type("policy_engine") == "system"
    assert infer_actor_type("system") == "system"
    fields = auth_service.audit_actor_fields(
        None, actor="scheduler", actor_role=None, authentication_source="system"
    )
    assert fields["authentication_source"] == "system"
    assert fields["actor"] == "scheduler"


def test_unknown_provider_rejected(monkeypatch):
    monkeypatch.setattr("config.AUTH_PROVIDER", "oidc")
    monkeypatch.setattr("integrations.auth.factory.AUTH_PROVIDER", "oidc")
    monkeypatch.setattr("services.auth_service.AUTH_PROVIDER", "oidc")
    with pytest.raises(ProviderConfigError):
        validate_auth_provider_configuration()
    with pytest.raises(auth_service.AuthError):
        auth_service.login(user_id="alex.store")
    # Access codes never authenticate (demo or otherwise).
    assert auth_service.verify_access_code("secret-demo") is False


def test_client_cannot_escalate_role_via_identity_model(monkeypatch):
    _patch_demo_code(monkeypatch)
    token, identity = auth_service.login(user_id="riley.viewer")
    assert identity.role == "viewer"
    # Forged token signature fails validation.
    forged = token.rsplit(".", 1)[0] + ".deadbeef"
    with pytest.raises(auth_service.AuthError):
        auth_service.validate_session(forged)
    auth_service.logout(session_token=token)
