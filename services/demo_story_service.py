"""Customer demo story — deterministic scenarios over existing CSV + services.

Does not change production ERP lifecycle semantics, policy formulas, or CSV data.
Blocked (scenario C) uses the same in-process inventory-age override tests already use;
master data files are never rewritten.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from services import (
    agent_ops_service,
    audit_service,
    batch_run_service,
    disposition_service,
    erp_service,
    evidence_service,
    ops_health_service,
    order_lifecycle_service,
    overview_service,
    policy_service,
    purchase_order_service,
    queue_service,
)
from services import order_lifecycle_states as ols

# Canonical store/SKU pairs from data/*.csv — verified against default policy.
SCENARIO_A_AUTO = ("ST001", "SKU-1002")  # Sparkling Water — low-risk auto
SCENARIO_B_HUMAN = ("ST001", "SKU-1001")  # Organic Whole Milk — needs review
SCENARIO_C_BLOCKED = ("ST001", "SKU-1004")  # Greek Yogurt — blocked when stale
SCENARIO_D_NO_ORDER = ("ST002", "SKU-1003")  # Granola Bars Westside — no order

DEMO_BATCH_PAIRS: list[tuple[str, str]] = [
    SCENARIO_A_AUTO,
    SCENARIO_B_HUMAN,
    SCENARIO_C_BLOCKED,
    SCENARIO_D_NO_ORDER,
]

# Product names for walkthrough copy (from products.csv; not invented).
PRODUCT_NAMES = {
    "SKU-1001": "Organic Whole Milk",
    "SKU-1002": "Sparkling Water",
    "SKU-1003": "Granola Bars",
    "SKU-1004": "Greek Yogurt",
    "SKU-1005": "Paper Towels",
}

STORE_NAMES = {
    "ST001": "Downtown Flagship",
    "ST002": "Westside Mall",
}

DEMO_ACTOR = "alex.store"
DEMO_ACTOR_ROLE = "store_manager"
DEMO_ADMIN = "admin.demo"
DEMO_ADMIN_ROLE = "administrator"
DEMO_SESSION = "sess-customer-demo"


@contextmanager
def _blocked_stale_inventory_age() -> Iterator[None]:
    """During scoring only: treat SKU-1004 as stale so policy blocks it."""
    real_age = policy_service.inventory_age_hours

    def _age(position, **kwargs):  # type: ignore[no-untyped-def]
        if getattr(position, "sku", None) == SCENARIO_C_BLOCKED[1]:
            return 10_000.0
        return real_age(position, **kwargs)

    policy_service.inventory_age_hours = _age  # type: ignore[assignment]
    try:
        yield
    finally:
        policy_service.inventory_age_hours = real_age  # type: ignore[assignment]


def scenario_catalog() -> dict[str, dict[str, Any]]:
    """Static scenario descriptions for docs/tests (no side effects)."""
    return {
        "A": {
            "key": "auto_handled",
            "title": "Low-risk auto handled",
            "pair": SCENARIO_A_AUTO,
            "expected_disposition": "auto_release",
            "product": PRODUCT_NAMES[SCENARIO_A_AUTO[1]],
            "store": STORE_NAMES[SCENARIO_A_AUTO[0]],
            "story": (
                "Within-policy replenishment is released automatically — "
                "no human decision required."
            ),
        },
        "B": {
            "key": "human_review",
            "title": "Human review",
            "pair": SCENARIO_B_HUMAN,
            "expected_disposition": "human_review",
            "product": PRODUCT_NAMES[SCENARIO_B_HUMAN[1]],
            "store": STORE_NAMES[SCENARIO_B_HUMAN[0]],
            "story": (
                "Stockout / policy exception surfaces on Today's Decisions "
                "for an explicit approve/adjust decision."
            ),
        },
        "C": {
            "key": "blocked",
            "title": "Blocked",
            "pair": SCENARIO_C_BLOCKED,
            "expected_disposition": "blocked",
            "product": PRODUCT_NAMES[SCENARIO_C_BLOCKED[1]],
            "store": STORE_NAMES[SCENARIO_C_BLOCKED[0]],
            "story": (
                "Stale inventory signal fails freshness guardrails — "
                "Cannot proceed until data is trustworthy."
            ),
            "prep_note": (
                "Demo prep applies an in-process stale age for SKU-1004 during "
                "scoring only; CSV files are not modified."
            ),
        },
        "D": {
            "key": "no_order",
            "title": "No order needed",
            "pair": SCENARIO_D_NO_ORDER,
            "expected_disposition": "no_order",
            "product": PRODUCT_NAMES[SCENARIO_D_NO_ORDER[1]],
            "store": STORE_NAMES[SCENARIO_D_NO_ORDER[0]],
            "story": "Coverage is sufficient — the agent records no order needed.",
        },
        "E": {
            "key": "transmission_retry",
            "title": "Transmission retry / failure",
            "expected_status": ols.RETRY_PENDING,
            "mock_scenario": "temporary_failure",
            "story": (
                "Mock purchasing connection returns a temporary failure; "
                "status becomes Retry Scheduled (queue ≠ transmit preserved)."
            ),
        },
        "F": {
            "key": "erp_rejection",
            "title": "Purchasing system rejection",
            "expected_status": ols.ERP_REJECTED,
            "mock_scenario": "business_rejection",
            "story": (
                "Mock adapter returns a business rejection; status becomes "
                "Rejected by Purchasing System — review required, no auto-retry."
            ),
        },
    }


def prepare_customer_demo_run(
    *,
    actor: str = DEMO_ACTOR,
    actor_role: str = DEMO_ACTOR_ROLE,
    session_id: str = DEMO_SESSION,
    pairs: list[tuple[str, str]] | None = None,
    apply_blocked_stale: bool = True,
) -> dict[str, Any]:
    """
    Run one deterministic replenishment batch for the customer demo story.

    Returns scenario → recommendation metadata plus overview/queue summaries.
    """
    policy_service.ensure_default_policy()
    batch_pairs = list(pairs or DEMO_BATCH_PAIRS)

    if apply_blocked_stale:
        with _blocked_stale_inventory_age():
            run = batch_run_service.run_replenishment_batch(
                batch_pairs,
                trigger_type="manual",
                initiated_by=actor,
                user_id=actor,
                session_id=session_id,
            )
    else:
        run = batch_run_service.run_replenishment_batch(
            batch_pairs,
            trigger_type="manual",
            initiated_by=actor,
            user_id=actor,
            session_id=session_id,
        )

    items_by_sku_store = {
        (i.get("store_id"), i.get("sku")): i for i in (run.get("items") or [])
    }
    catalog = scenario_catalog()
    scenarios: dict[str, Any] = {}
    for letter in ("A", "B", "C", "D"):
        meta = catalog[letter]
        pair = meta["pair"]
        item = items_by_sku_store.get(pair) or {}
        scenarios[letter] = {
            **meta,
            "recommendation_id": item.get("recommendation_id"),
            "disposition": item.get("disposition"),
            "agent_recommended_quantity": item.get("agent_recommended_quantity"),
            "run_id": run.get("run_id"),
        }

    overview = overview_service.get_replenishment_overview(actor_role=actor_role)
    queue_all = queue_service.get_todays_queue(
        filter_key="all", run_id=run.get("run_id")
    )
    return {
        "run_id": run.get("run_id"),
        "run": run,
        "scenarios": scenarios,
        "overview_metrics": overview.get("metrics") or {},
        "overview": overview,
        "queue_summary": queue_all.get("summary") or {},
        "actor": actor,
        "actor_role": actor_role,
        "session_id": session_id,
    }


def approve_human_review_scenario(
    prepared: dict[str, Any],
    *,
    actor: str | None = None,
    actor_role: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Approve scenario B — returns disposition/workflow result."""
    scenario_b = prepared["scenarios"]["B"]
    rec_id = scenario_b["recommendation_id"]
    if not rec_id:
        raise ValueError("Scenario B recommendation_id missing — prepare demo first")
    return disposition_service.approve_recommendation(
        recommendation_id=rec_id,
        actor=actor or prepared.get("actor") or DEMO_ACTOR,
        actor_role=actor_role or prepared.get("actor_role") or DEMO_ACTOR_ROLE,
        user_id=actor or prepared.get("actor") or DEMO_ACTOR,
        session_id=session_id or prepared.get("session_id") or DEMO_SESSION,
    )


def evidence_for_scenario(prepared: dict[str, Any], letter: str = "B") -> dict[str, Any]:
    rec_id = prepared["scenarios"][letter]["recommendation_id"]
    if not rec_id:
        raise ValueError(f"Scenario {letter} has no recommendation_id")
    return evidence_service.get_recommendation_evidence(rec_id)


def transmit_demo_success(
    *,
    actor: str = DEMO_ACTOR,
    actor_role: str = DEMO_ACTOR_ROLE,
    session_id: str = DEMO_SESSION,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Demo action: Send now (ERP_AUTO_TRANSMIT=false). Uses mock success path."""
    erp_service.reset_erp_adapter()
    return purchase_order_service.send_approved_to_erp(
        actor=actor,
        actor_role=actor_role,
        user_id=actor,
        session_id=session_id,
        run_id=run_id,
    )


def transmit_scenario_with_mock(
    prepared: dict[str, Any],
    *,
    letter: str = "B",
    mock_scenario: str,
    actor: str = DEMO_ACTOR,
    actor_role: str = DEMO_ACTOR_ROLE,
) -> dict[str, Any]:
    """
    Transmit a single approved intent with a mock adapter scenario (E/F).
    Caller must have approved the recommendation so an intent is queued.
    Does not call the demo bulk send — preserves a single-intent failure path.
    """
    from database.connection import get_session
    from repositories import order_intent_repository

    rec_id = prepared["scenarios"][letter]["recommendation_id"]
    with get_session() as session:
        intent = order_intent_repository.get_by_recommendation(session, rec_id)
    if intent is None:
        raise ValueError(
            f"No order intent for scenario {letter} — approve the recommendation first"
        )

    erp_service.reset_erp_adapter()
    status = ols.normalize_status(intent.status)
    if status not in {ols.QUEUED_FOR_ERP, ols.RETRY_PENDING, ols.TRANSMISSION_FAILED}:
        raise ValueError(
            f"Scenario {letter} is not transmit-eligible ({status}); "
            "prepare a fresh demo run for failure demos."
        )
    return order_lifecycle_service.transmit_order_intent(
        order_intent_id=intent.order_intent_id,
        actor=actor,
        actor_role=actor_role,
        mock_scenario=mock_scenario,
    )


def business_trail_types(*, recommendation_id: str | None = None) -> set[str]:
    events = audit_service.list_business_events(limit=200)
    types: set[str] = set()
    for ev in events:
        if recommendation_id and ev.get("recommendation_id") not in {
            None,
            recommendation_id,
        }:
            # Keep run-level events even when filtering
            details = ev.get("details") or {}
            if details.get("recommendation_id") not in {None, recommendation_id}:
                if ev.get("recommendation_id") != recommendation_id:
                    continue
        types.add(str(ev.get("event_type") or ""))
    return types


def agent_ops_snapshot(*, actor_role: str = DEMO_ADMIN_ROLE) -> dict[str, Any]:
    """Administrator Agent Operations metrics (deeper execution trail)."""
    metrics = agent_ops_service.get_operations_metrics(actor_role=actor_role)
    executions = agent_ops_service.list_agent_executions(limit=20)
    return {
        "metrics": metrics,
        "executions": executions,
        "has_signal": bool(executions)
        or any(
            int(metrics.get(k) or 0) > 0
            for k in (
                "completed_today",
                "active_executions",
                "waiting_for_human",
                "failed_executions",
                "retry_pending",
            )
        ),
    }


def system_health_is_ok() -> dict[str, Any]:
    """
    Demo CSV watermarks may truthfully report stale freshness.
    'ok' means dependencies are not unavailable — we do not fake Healthy.
    """
    snap = ops_health_service.get_operational_health()
    overall = str(snap.get("overall_status") or "").lower()
    return {
        "overall_status": snap.get("overall_status"),
        "ok": overall not in {"unavailable", "error", "down"},
        "snapshot": snap,
    }


def verify_happy_path_labels(workbench: dict[str, Any]) -> list[str]:
    """Return customer status labels present on the orders workbench."""
    labels = []
    for o in workbench.get("orders") or []:
        labels.append(str(o.get("order_status_label") or ""))
    return labels
