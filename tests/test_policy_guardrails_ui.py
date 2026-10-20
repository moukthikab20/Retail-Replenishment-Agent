"""Checkpoint 8 — Policy & Guardrails UI + versioned admin publish."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from database.connection import get_session
from database.models import AuditEventRow
from repositories import policy_repository, recommendation_repository
from services import (
    auth_service,
    batch_run_service,
    policy_catalog,
    policy_service,
)
from sqlalchemy import select


def test_rule_catalog_covers_required_business_rules():
    policy = policy_service.ensure_default_policy()
    rows = policy_catalog.rule_rows_for_policy(policy)
    names = {r["business_name"] for r in rows}
    assert "Auto-release ceiling" in names
    assert "Minimum confidence" in names
    assert "Maximum inventory-feed age" in names
    assert "Exception routing" in names
    assert "Maximum days of supply" in names
    assert "Minimum historical demand requirement" in names
    assert "Promotion overlap rule" in names
    assert "Manual override threshold" in names
    assert "Formal approval threshold" in names
    for row in rows:
        assert row["business_name"]
        assert row["explanation"]
        assert row["configured_value"]
        assert row["internal_key"]


def test_guardrails_view_is_read_model():
    view = policy_service.get_policy_guardrails_view()
    assert view["policy_version"]
    assert view["active"] is True
    assert len(view["rules"]) >= 9
    assert view["rules"][0]["business_name"] == "Auto-release ceiling"
    assert "under this value" in view["rules"][0]["explanation"].lower() or (
        "at or under" in view["rules"][0]["explanation"].lower()
    )


def test_only_administrator_can_edit_policy():
    assert auth_service.can_edit_policy("administrator") is True
    assert auth_service.can_edit_policy("store_manager") is False
    assert auth_service.can_edit_policy("viewer") is False


def test_publish_creates_new_version_preserves_old():
    prior = policy_service.ensure_default_policy(created_by="seed")
    prior_version = prior.policy_version
    prior_ceiling = prior.auto_release_max_value
    prior_id = prior.policy_id

    result = policy_service.publish_policy_version(
        actor="admin.demo",
        actor_role="administrator",
        changes={"auto_release_max_value": Decimal("1800")},
    )
    assert result["policy_version"] != prior_version
    assert result["supersedes_policy_version"] == prior_version
    assert result["created_by"] == "admin.demo"
    assert result["created_at"]

    active = policy_service.get_active_policy()
    assert active.policy_version == result["policy_version"]
    assert active.auto_release_max_value == Decimal("1800")
    assert active.created_by == "admin.demo"

    with get_session() as session:
        old = policy_repository.get_policy(session, prior_id)
        assert old is not None
        assert old.active is False
        assert old.effective_to is not None
        # Prior thresholds untouched.
        assert old.auto_release_max_value == prior_ceiling
        assert old.policy_version == prior_version


def test_publish_writes_audit_event():
    policy_service.ensure_default_policy()
    result = policy_service.publish_policy_version(
        actor="admin.demo",
        actor_role="administrator",
        changes={"minimum_confidence": Decimal("0.80")},
    )
    with get_session() as session:
        events = list(
            session.scalars(
                select(AuditEventRow)
                .where(AuditEventRow.event_type == "policy_version_published")
                .order_by(AuditEventRow.timestamp.desc())
            )
        )
    assert events
    latest = events[0]
    assert latest.actor == "admin.demo"
    assert latest.actor_role == "administrator"
    assert result["policy_version"] in (latest.details_json or "")
    assert latest.timestamp is not None


def test_non_admin_cannot_publish():
    policy_service.ensure_default_policy()
    try:
        policy_service.publish_policy_version(
            actor="alex.store",
            actor_role="store_manager",
            changes={"auto_release_max_value": Decimal("1000")},
        )
        assert False, "expected AuthError"
    except auth_service.AuthError:
        pass


def test_recommendations_keep_policy_version_after_publish():
    policy_service.ensure_default_policy()
    run = batch_run_service.run_replenishment_batch(
        [("ST001", "SKU-1001")],
        trigger_type="manual",
        initiated_by="admin.demo",
    )
    rec_id = next(
        i["recommendation_id"]
        for i in run["items"]
        if i.get("recommendation_id")
    )
    with get_session() as session:
        row = recommendation_repository.get_recommendation_row(session, rec_id)
        assert row is not None
        frozen_version = row.policy_version
        frozen_eval = row.policy_evaluation_json

    policy_service.publish_policy_version(
        actor="admin.demo",
        actor_role="administrator",
        changes={"auto_release_max_value": Decimal("999")},
    )

    with get_session() as session:
        refreshed = recommendation_repository.get_recommendation_row(session, rec_id)
        assert refreshed is not None
        assert refreshed.policy_version == frozen_version
        assert refreshed.policy_evaluation_json == frozen_eval

    active = policy_service.get_active_policy()
    assert active.policy_version != frozen_version


def test_policy_page_renders_for_business_user():
    from streamlit.testing.v1 import AppTest

    policy_service.ensure_default_policy()
    app = Path(__file__).parent / "ui_apps" / "policy_app.py"
    at = AppTest.from_file(str(app), default_timeout=60)
    at.run(timeout=60)
    assert not at.exception
    text = " ".join(str(m.value) for m in at.markdown)
    assert "Auto-release ceiling" in text
    assert "Minimum confidence" in text
    assert "auto_release_max_value" in text
    assert "Publish new version" not in text  # viewer / non-admin fixture
