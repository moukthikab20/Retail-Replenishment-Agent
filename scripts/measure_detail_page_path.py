"""Console timing for row-click → detail page backend path (no Streamlit UI)."""

from __future__ import annotations

import time
from typing import Callable

from database.connection import init_db, reset_engine


def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000.0


def _step(label: str, fn: Callable[[], object]) -> object:
    t0 = time.perf_counter()
    out = fn()
    print(f"  {label}: {_ms(t0):.1f} ms")
    return out


def main() -> None:
    reset_engine()
    print("=== Detail page path timing ===")

    t0 = time.perf_counter()
    init_db()
    print(f"  init_db (cold): {_ms(t0):.1f} ms")
    t0 = time.perf_counter()
    init_db()
    print(f"  init_db (warm): {_ms(t0):.1f} ms")

    from services import (
        auth_service,
        decision_workflow_service,
        evidence_service,
        overview_dashboard_service,
        queue_service,
        purchase_order_service,
        recommendation_service,
        scheduler_service,
    )

    _step("topbar get_topbar_run_metrics", scheduler_service.get_topbar_run_metrics)
    _step("topbar get_topbar_run_metrics (cached path)", scheduler_service.get_topbar_run_metrics)
    _step("nav badges queue (cold cache)", lambda: queue_service.get_todays_queue(filter_key="all"))

    dash = _step(
        "overview dashboard (skipped on row-click callback path)",
        lambda: overview_dashboard_service.get_overview_dashboard(
            actor_role="store_manager",
            display_name="Alex",
        ),
    )
    rows = dash.get("all_rows") or []
    rid = next((row["recommendation_id"] for row in rows if row.get("recommendation_id")), None)
    if not rid:
        print("No recommendation_id found — seed demo data first.")
        return
    print(f"  sample recommendation_id: {rid}")

    user = auth_service.get_demo_user("alex.store")
    actor = user.user_id
    role = user.role

    rec = _step(
        "get_recommendation",
        lambda: recommendation_service.get_recommendation(
            rid, user_id=actor, role=role, check_access=True
        ),
    )
    _step(
        "get_recommendation_evidence (shared rec)",
        lambda: evidence_service.get_recommendation_evidence(
            rid, rec=rec, user_id=actor, role=role, check_access=True
        ),
    )
    _step(
        "decision_workflow get_available_actions",
        lambda: decision_workflow_service.get_available_actions(
            rid, actor_role=role
        ),
    )


if __name__ == "__main__":
    main()
