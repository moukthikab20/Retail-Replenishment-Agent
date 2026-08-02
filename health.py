"""Application and database health checks (no secrets in responses)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from config import APP_ENV, OPENAI_MODEL
from database.connection import database_healthcheck, redact_database_url


def check_health() -> dict[str, Any]:
    """
    Return a JSON-serializable health payload safe for browsers and probes.

    Never includes API keys, access codes, or raw DATABASE_URL credentials.
    """
    db = database_healthcheck()
    status = "ok" if db.get("ok") else "degraded"
    return {
        "status": status,
        "service": "retail-replenishment-poc",
        "app_env": APP_ENV,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": {
            "ok": bool(db.get("ok")),
            "dialect": db.get("dialect"),
            "url": redact_database_url(),
            "error": db.get("error") if not db.get("ok") else None,
        },
        "openai": {
            "model_configured": bool(OPENAI_MODEL),
            "api_key_present": _api_key_present(),
        },
        "demo": {
            "banner": "Demonstration Environment — sample data — no real supplier orders.",
            "real_erp": False,
        },
    }


def is_healthy() -> bool:
    return check_health()["status"] == "ok"


def _api_key_present() -> bool:
    from config import OPENAI_API_KEY

    return bool(OPENAI_API_KEY and OPENAI_API_KEY.strip())
