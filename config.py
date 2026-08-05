"""Application configuration constants and environment helpers."""

from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

APP_ENV = os.getenv("APP_ENV", "development")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///retail_agent.db")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
DEMO_ACCESS_CODE = os.getenv("DEMO_ACCESS_CODE", "")

# Tracing — sensitive payloads off by default (Agents SDK RunConfig flag).
_TRACE_SENSITIVE_RAW = os.getenv(
    "TRACE_INCLUDE_SENSITIVE_DATA",
    os.getenv("TRACE_SENSITIVE_DATA", "false"),
).lower()
TRACE_INCLUDE_SENSITIVE_DATA = _TRACE_SENSITIVE_RAW in {"1", "true", "yes"}
# Backward-compatible alias used by older docs/tests.
TRACE_SENSITIVE_DATA = TRACE_INCLUDE_SENSITIVE_DATA
AGENT_TRACING_DISABLED = os.getenv("AGENT_TRACING_DISABLED", "false").lower() in {
    "1",
    "true",
    "yes",
}

AS_OF_DATE = "2026-07-27"
FORECAST_LOOKBACK_DAYS = 7
FORECAST_HORIZON_DAYS = 7
AGENT_MAX_TURNS = int(os.getenv("AGENT_MAX_TURNS", "12"))
# Follow-up Q&A uses a tighter turn budget than full analysis.
FOLLOW_UP_MAX_TURNS = int(os.getenv("FOLLOW_UP_MAX_TURNS", "8"))
# Inventory older than this many days vs AS_OF_DATE is treated as stale for the agent.
INVENTORY_STALE_DAYS = int(os.getenv("INVENTORY_STALE_DAYS", "14"))

# Persistent Agents SDK session store for follow-up conversation history.
AGENT_SESSION_DB_PATH = os.getenv(
    "AGENT_SESSION_DB_PATH",
    str(BASE_DIR / "data" / "agent_sessions.sqlite"),
)

WORKFLOW_ANALYSIS = "retail_replenishment_analysis"
WORKFLOW_FOLLOW_UP = "retail_replenishment_follow_up"
WORKFLOW_ORDER = "retail_replenishment_order"

# Pending sensitive-tool HITL resume window (browser refresh safe via DB state).
HITL_RESUME_TTL_MINUTES = int(os.getenv("HITL_RESUME_TTL_MINUTES", "120"))
AGENT_RUN_STATE_VERSION = 1


# Shared-demo rate limits (deterministic; not enforced by the model)
MAX_AGENT_RUNS_PER_USER_PER_HOUR = int(os.getenv("MAX_AGENT_RUNS_PER_USER_PER_HOUR", "20"))
RATE_LIMIT_WINDOW_MINUTES = int(os.getenv("RATE_LIMIT_WINDOW_MINUTES", "60"))

# Product defaults when CSV lacks newer master-data columns
DEFAULT_UNIT_COST = Decimal("0.00")
DEFAULT_MINIMUM_ORDER_QUANTITY = 0
DEFAULT_MAXIMUM_ORDER_QUANTITY = 9999
DEFAULT_RESERVED_UNITS = 0

# Risk thresholds (days of supply)
RISK_STOCKOUT_DOS_THRESHOLD = 3.0
RISK_OVERSTOCK_DOS_THRESHOLD = 14.0
RISK_ON_HAND_FORECAST_RATIO = 0.3

# Human override escalation thresholds (absolute percent difference)
ESCALATION_WARNING_PERCENT = Decimal("10")
ESCALATION_REQUIRED_PERCENT = Decimal("25")

# Demo authentication roles (authorization is deterministic Python, not the model)
ROLE_VIEWER = "viewer"
ROLE_STORE_MANAGER = "store_manager"
ROLE_INVENTORY_PLANNER = "inventory_planner"
ROLE_CATEGORY_MANAGER = "category_manager"
ROLE_ADMINISTRATOR = "administrator"

ROLE_HIERARCHY = {
    ROLE_VIEWER: 1,
    ROLE_STORE_MANAGER: 2,
    ROLE_INVENTORY_PLANNER: 3,
    ROLE_CATEGORY_MANAGER: 4,
    ROLE_ADMINISTRATOR: 5,
}

DEMO_USERS = {
    "riley.viewer": {
        "display_name": "Riley Viewer",
        "role": ROLE_VIEWER,
    },
    "alex.store": {
        "display_name": "Alex Store Manager",
        "role": ROLE_STORE_MANAGER,
    },
    "jamie.planner": {
        "display_name": "Jamie Inventory Planner",
        "role": ROLE_INVENTORY_PLANNER,
    },
    "casey.category": {
        "display_name": "Casey Category Manager",
        "role": ROLE_CATEGORY_MANAGER,
    },
    "admin.demo": {
        "display_name": "Dana Administrator",
        "role": ROLE_ADMINISTRATOR,
    },
}

# Backward-compatible alias used by older UI helpers/tests
DEV_USERS = DEMO_USERS

# Roles allowed for normal vs elevated approval
NORMAL_APPROVAL_ROLES = {
    ROLE_STORE_MANAGER,
    ROLE_INVENTORY_PLANNER,
    ROLE_CATEGORY_MANAGER,
    ROLE_ADMINISTRATOR,
}
ELEVATED_APPROVAL_ROLES = {
    ROLE_INVENTORY_PLANNER,
    ROLE_CATEGORY_MANAGER,
    ROLE_ADMINISTRATOR,
}
