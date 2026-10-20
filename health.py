"""Application and operational dependency health checks (no secrets)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from config import (
    APP_ENV,
    BATCH_SCHEDULE_CRON,
    BATCH_SCHEDULE_TIMEZONE,
    CRON_SECRET,
    OPENAI_MODEL,
    REPLENISHMENT_CRON,
    REPLENISHMENT_RUN_INTERVAL_HOURS,
    REPLENISHMENT_SCHEDULE_ENABLED,
    REPLENISHMENT_STALE_TOLERANCE_MINUTES,
    REPLENISHMENT_TIMEZONE,
)
from database.connection import database_healthcheck, redact_database_url
from services import erp_service, ops_health_service
from services import auth_service as _auth_service


def check_health() -> dict[str, Any]:
    """
    Return a JSON-serializable health payload safe for browsers and probes.

    Includes operational dependency checks used by System Health. Never includes
    API keys, access codes, or raw DATABASE_URL credentials.
    """
    ops = ops_health_service.get_operational_health()
    db = database_healthcheck()
    erp = erp_service.adapter_health()
    auth = _auth_service.authentication_health()
    try:
        from services import order_lifecycle_service

        order_metrics = order_lifecycle_service.get_order_lifecycle_metrics()
    except Exception:  # noqa: BLE001
        order_metrics = {}

    # Keep probe-oriented coarse status for Render /Health.
    status = ops.get("status") or ("ok" if db.get("ok") else "degraded")

    openai_dep = next(
        (d for d in ops["dependencies"] if d["component"] == "openai_model_service"),
        None,
    )
    schedule_dep = next(
        (d for d in ops["dependencies"] if d["component"] == "scheduler_last_run"),
        None,
    )

    return {
        "status": status,
        "overall_status": ops.get("overall_status"),
        "service": "retail-replenishment-poc",
        "app_env": APP_ENV,
        "timestamp": ops.get("timestamp")
        or datetime.now(timezone.utc).isoformat(),
        "database": {
            "ok": bool(db.get("ok")),
            "dialect": db.get("dialect"),
            "url": redact_database_url(),
            "error": db.get("error") if not db.get("ok") else None,
        },
        "openai": {
            "model_configured": bool(OPENAI_MODEL),
            "api_key_present": _api_key_present(),
            "status": (openai_dep or {}).get("status"),
            "message": (openai_dep or {}).get("message"),
        },
        "authentication": {
            "ok": bool(auth.get("ok")),
            "status": auth.get("status"),
            "provider_name": auth.get("provider_name"),
            "source": auth.get("source"),
            "message": auth.get("message"),
            "config": auth.get("config"),
            "sessions": {
                "ok": bool((auth.get("sessions") or {}).get("ok", True)),
                "active_sessions": (auth.get("sessions") or {}).get("active_sessions"),
                "ttl_minutes": (auth.get("sessions") or {}).get("ttl_minutes"),
            },
        },
        "erp": {
            "ok": bool(erp.get("ok")),
            "adapter": erp.get("adapter"),
            "mode": erp.get("mode"),
            "real_erp": bool(erp.get("real_erp")),
            "detail": erp.get("detail"),
            "provider_name": erp.get("provider_name"),
            "source": erp.get("source"),
            "label": f"ERP — {erp.get('source') or erp.get('provider_name') or 'Mock ERP'}",
            "order_lifecycle": {
                "queued_for_erp": order_metrics.get("queued_for_erp", 0),
                "transmission_failed": order_metrics.get("transmission_failed", 0),
                "retry_pending": order_metrics.get("retry_pending", 0),
                "erp_rejected": order_metrics.get("erp_rejected", 0),
                "oldest_queued_order_at": order_metrics.get("oldest_queued_order_at"),
            },
        },
        "providers": ops.get("providers") or {},
        "batch_schedule": {
            "enabled": bool(REPLENISHMENT_SCHEDULE_ENABLED),
            "interval_hours": REPLENISHMENT_RUN_INTERVAL_HOURS,
            "cron": REPLENISHMENT_CRON or BATCH_SCHEDULE_CRON,
            "timezone": REPLENISHMENT_TIMEZONE or BATCH_SCHEDULE_TIMEZONE,
            "stale_tolerance_minutes": REPLENISHMENT_STALE_TOLERANCE_MINUTES,
            "cron_secret_configured": bool((CRON_SECRET or "").strip()),
            "entry_point": "python -m jobs.run_replenishment",
            "status": (schedule_dep or {}).get("status"),
            "scheduler_status": ((schedule_dep or {}).get("details") or {}).get(
                "scheduler_status"
            ),
            "message": (schedule_dep or {}).get("message"),
        },
        "dependencies": ops.get("dependencies") or [],
        "data_freshness": ops.get("data_freshness") or {},
        "demo": ops.get("demo")
        or {
            "banner": "Demonstration Environment — sample data — no real supplier orders.",
            "real_erp": False,
            "real_pos": False,
        },
    }


def is_healthy() -> bool:
    return check_health()["status"] == "ok"


def _api_key_present() -> bool:
    from config import OPENAI_API_KEY

    return bool(OPENAI_API_KEY and OPENAI_API_KEY.strip())
