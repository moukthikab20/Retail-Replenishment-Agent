"""Human-in-the-loop helpers for sensitive order-tool pause/resume."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from config import AGENT_RUN_STATE_VERSION, HITL_RESUME_TTL_MINUTES
from services import approval_service
from services.errors import AppError

logger = logging.getLogger(__name__)

_SENSITIVE_KEYS = frozenset(
    {"api_key", "openai_api_key", "authorization", "password", "secret", "token"}
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_pause_envelope(
    *,
    approval_id: str,
    recommendation_id: str,
    approved_final_quantity: int,
    pending_tool_name: str,
    pending_tool_args: dict[str, Any],
    sdk_run_state: dict[str, Any] | None,
    mode: str,
    actor: str | None = None,
    actor_role: str | None = None,
) -> dict[str, Any]:
    """Versioned envelope stored in agent_run_states.state_json."""
    paused_at = utcnow()
    expires_at = paused_at + timedelta(minutes=HITL_RESUME_TTL_MINUTES)
    return {
        "version": AGENT_RUN_STATE_VERSION,
        "mode": mode,  # "sdk" | "deterministic_hitl"
        "sdk_run_state": _sanitize_jsonable(sdk_run_state) if sdk_run_state else None,
        "pending_tool_name": pending_tool_name,
        "pending_tool_args": _sanitize_jsonable(pending_tool_args),
        "guards": {
            "approval_id": approval_id,
            "recommendation_id": recommendation_id,
            "approved_final_quantity": approved_final_quantity,
            "approval_status": "approved",
            "paused_at": paused_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "actor_at_pause": actor,
            "actor_role_at_pause": actor_role,
        },
    }


def parse_state_envelope(raw: str | dict[str, Any]) -> dict[str, Any]:
    """Parse stored JSON; wrap legacy bare SDK payloads for compatibility."""
    payload = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(payload, dict):
        raise AppError("Stored agent run state is invalid.", code="hitl_state_invalid")
    if "version" in payload and "guards" in payload:
        return payload
    # Legacy: entire blob was SDK RunState JSON
    return {
        "version": 0,
        "mode": "sdk",
        "sdk_run_state": payload,
        "pending_tool_name": "create_mock_purchase_order",
        "pending_tool_args": {},
        "guards": {},
    }


def validate_resume_guards(
    envelope: dict[str, Any],
    *,
    expect_paused_status: str = "paused",
    row_status: str | None = None,
) -> dict[str, Any]:
    """
    Enforce formal approval still valid for SDK tool resume.

    Blocks expired pauses and changed approved quantities.
    """
    if row_status and row_status != expect_paused_status:
        raise AppError(
            f"Agent run is not paused (status={row_status}).",
            code="hitl_not_paused",
        )

    guards = envelope.get("guards") or {}
    approval_id = guards.get("approval_id")
    if not approval_id:
        # Legacy envelopes without guards: require pending args approval_id
        approval_id = (envelope.get("pending_tool_args") or {}).get("approval_id")
    if not approval_id:
        raise AppError(
            "Paused run is missing approval_id; cannot resume safely.",
            code="hitl_missing_approval",
        )

    expires_at_raw = guards.get("expires_at")
    if expires_at_raw:
        expires_at = datetime.fromisoformat(str(expires_at_raw))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if utcnow() > expires_at:
            raise AppError(
                "The pending sensitive-tool approval has expired. "
                "Restart the order flow after confirming formal approval.",
                code="hitl_expired",
            )

    approval = approval_service.get_approval_status(str(approval_id))
    status = approval.get("status")
    if status != "approved":
        raise AppError(
            f"Formal approval is no longer approved (status={status}). "
            "Sensitive-tool resume is blocked.",
            code="hitl_approval_not_approved",
        )

    expected_qty = guards.get("approved_final_quantity")
    current_qty = approval.get("approved_final_quantity")
    if expected_qty is not None and current_qty is not None:
        if int(expected_qty) != int(current_qty):
            raise AppError(
                "Approved final quantity changed since the order tool was paused. "
                "Resume is blocked to prevent an inconsistent purchase order.",
                code="hitl_quantity_changed",
            )

    return {
        "approval_id": str(approval_id),
        "recommendation_id": guards.get("recommendation_id")
        or approval.get("recommendation_id"),
        "approved_final_quantity": current_qty,
        "approval": approval,
    }


def _sanitize_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in _SENSITIVE_KEYS or "api_key" in str(key).lower():
                cleaned[key] = "[redacted]"
            else:
                cleaned[key] = _sanitize_jsonable(item)
        return cleaned
    if isinstance(value, list):
        return [_sanitize_jsonable(item) for item in value]
    return value


def envelope_to_json(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, default=str)
