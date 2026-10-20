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

# Authentication provider (demo only in this deployment; OIDC placeholders reserved).
AUTH_PROVIDER = os.getenv("AUTH_PROVIDER", "demo").strip().lower()
SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "480"))
SESSION_SECRET = os.getenv("SESSION_SECRET", "")
# Future OIDC placeholders — unused until an OIDC provider is registered.
OIDC_ISSUER = os.getenv("OIDC_ISSUER", "")
OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID", "")
OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET", "")
OIDC_REDIRECT_URI = os.getenv("OIDC_REDIRECT_URI", "")

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

# ERP adapter — mock only until a real connector is configured.
# Prefer ERP_PROVIDER; ERP_ADAPTER remains a legacy alias.
ERP_PROVIDER = (
    os.getenv("ERP_PROVIDER") or os.getenv("ERP_ADAPTER") or "mock"
).strip().lower()
ERP_ADAPTER = ERP_PROVIDER  # backward-compatible export
ERP_MOCK_FORCE_FAIL = os.getenv("ERP_MOCK_FORCE_FAIL", "false").lower() in {
    "1",
    "true",
    "yes",
}
ERP_AUTO_TRANSMIT = os.getenv("ERP_AUTO_TRANSMIT", "false").lower() in {"1","true","yes"}
ERP_MAX_RETRY_ATTEMPTS = int(os.getenv("ERP_MAX_RETRY_ATTEMPTS", "3"))
ERP_RETRY_DELAY_SECONDS = int(os.getenv("ERP_RETRY_DELAY_SECONDS", "60"))
ERP_MOCK_SCENARIO = os.getenv("ERP_MOCK_SCENARIO", "success").strip().lower()

# Enterprise integration providers (csv/demo/mock only in this deployment).
INVENTORY_PROVIDER = os.getenv("INVENTORY_PROVIDER", "csv").strip().lower()
SALES_PROVIDER = os.getenv("SALES_PROVIDER", "csv").strip().lower()
PRODUCT_PROVIDER = os.getenv("PRODUCT_PROVIDER", "csv").strip().lower()
SUPPLIER_PROVIDER = os.getenv("SUPPLIER_PROVIDER", "demo").strip().lower()

# Scheduled batch runs (Render cron / external cron → CLI job).
# When set, jobs/scripts require a matching --cron-secret.
CRON_SECRET = os.getenv("CRON_SECRET", "")
# Demo default: score the catalog every 6 hours.
REPLENISHMENT_RUN_INTERVAL_HOURS = int(
    os.getenv("REPLENISHMENT_RUN_INTERVAL_HOURS", "6")
)
# Cron expression for hosts that use crontab (Render cron service).
# Defaults to "every N hours" from REPLENISHMENT_RUN_INTERVAL_HOURS.
_DEFAULT_BATCH_CRON = (
    f"0 */{REPLENISHMENT_RUN_INTERVAL_HOURS} * * *"
    if REPLENISHMENT_RUN_INTERVAL_HOURS > 0
    else "0 */6 * * *"
)
# Canonical schedule config (new names) with backward-compatible BATCH_SCHEDULE_* aliases.
def _env_bool(name: str, default: str = "true") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


REPLENISHMENT_SCHEDULE_ENABLED = _env_bool("REPLENISHMENT_SCHEDULE_ENABLED", "true")
REPLENISHMENT_CRON = (
    os.getenv("REPLENISHMENT_CRON")
    or os.getenv("BATCH_SCHEDULE_CRON")
    or _DEFAULT_BATCH_CRON
)
REPLENISHMENT_TIMEZONE = (
    os.getenv("REPLENISHMENT_TIMEZONE")
    or os.getenv("BATCH_SCHEDULE_TIMEZONE")
    or "UTC"
)
REPLENISHMENT_STALE_TOLERANCE_MINUTES = int(
    os.getenv("REPLENISHMENT_STALE_TOLERANCE_MINUTES", "90")
)
# Legacy aliases — keep exporting for older imports/docs.
BATCH_SCHEDULE_CRON = REPLENISHMENT_CRON
BATCH_SCHEDULE_TIMEZONE = REPLENISHMENT_TIMEZONE
SCHEDULER_ACTOR = os.getenv("SCHEDULER_ACTOR", "replenishment_scheduler")

# Agent Operations / System Health — Agent Runtime thresholds (explicit, not silent).
AGENT_OPS_FAILED_WINDOW_HOURS = int(os.getenv("AGENT_OPS_FAILED_WINDOW_HOURS", "24"))
AGENT_OPS_FAILED_DEGRADED_THRESHOLD = int(
    os.getenv("AGENT_OPS_FAILED_DEGRADED_THRESHOLD", "5")
)
AGENT_OPS_WAITING_DEGRADED_THRESHOLD = int(
    os.getenv("AGENT_OPS_WAITING_DEGRADED_THRESHOLD", "20")
)
AGENT_OPS_LIST_DEFAULT_LIMIT = int(os.getenv("AGENT_OPS_LIST_DEFAULT_LIMIT", "100"))
AGENT_OPS_LIST_MAX_LIMIT = int(os.getenv("AGENT_OPS_LIST_MAX_LIMIT", "500"))
SCHEDULER_LOCK_TTL_MINUTES = int(os.getenv("SCHEDULER_LOCK_TTL_MINUTES", "180"))

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

# Batch replenishment release policy (config-driven; UI versioning comes later).
BATCH_POLICY_VERSION = os.getenv("BATCH_POLICY_VERSION", "v1")
DEFAULT_POLICY_AUTO_RELEASE_MAX_VALUE = Decimal(
    os.getenv("POLICY_AUTO_RELEASE_MAX_VALUE", "2500")
)
DEFAULT_POLICY_MINIMUM_CONFIDENCE = Decimal(
    os.getenv("POLICY_MINIMUM_CONFIDENCE", "0.75")
)
DEFAULT_POLICY_MAXIMUM_INVENTORY_AGE_HOURS = int(
    os.getenv("POLICY_MAXIMUM_INVENTORY_AGE_HOURS", "336")
)
DEFAULT_POLICY_MAXIMUM_DAYS_OF_SUPPLY = Decimal(
    os.getenv("POLICY_MAXIMUM_DAYS_OF_SUPPLY", "14")
)
DEFAULT_POLICY_MINIMUM_HISTORY_DAYS = int(os.getenv("POLICY_MINIMUM_HISTORY_DAYS", "7"))
DEFAULT_POLICY_REQUIRE_FORMAL_APPROVAL_ABOVE_VALUE = Decimal(
    os.getenv("POLICY_REQUIRE_FORMAL_APPROVAL_ABOVE_VALUE", "5000")
)


# Shared-demo rate limits (deterministic; not enforced by the model)
MAX_AGENT_RUNS_PER_USER_PER_HOUR = int(os.getenv("MAX_AGENT_RUNS_PER_USER_PER_HOUR", "20"))
RATE_LIMIT_WINDOW_MINUTES = int(os.getenv("RATE_LIMIT_WINDOW_MINUTES", "60"))

# Enterprise Memory & Knowledge Engine (SQL today; vector backends later)
MEMORY_PROVIDER = os.getenv("MEMORY_PROVIDER", "database").strip().lower()
MEMORY_RETRIEVAL_DEFAULT_LIMIT = int(os.getenv("MEMORY_RETRIEVAL_DEFAULT_LIMIT", "10"))
MEMORY_RETRIEVAL_MAX_LIMIT = int(os.getenv("MEMORY_RETRIEVAL_MAX_LIMIT", "50"))
MEMORY_AUDIT_PERSIST = os.getenv("MEMORY_AUDIT_PERSIST", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Enterprise LLM Orchestration Layer
# Supported: mock | openai — unknown values fail fast.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock").strip().lower()
LLM_MODEL = (os.getenv("LLM_MODEL") or OPENAI_MODEL or "gpt-4o-mini").strip()
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "4096"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.0"))
LLM_ENABLE_TOOL_CALLS = os.getenv("LLM_ENABLE_TOOL_CALLS", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Semantic Retrieval / RAG (extends Memory & Knowledge Engine)
RAG_ENABLED = os.getenv("RAG_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "mock").strip().lower()
RAG_MAX_RESULTS = int(os.getenv("RAG_MAX_RESULTS", "5"))
RAG_MAX_CONTEXT_CHARS = int(os.getenv("RAG_MAX_CONTEXT_CHARS", "4000"))
RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.15"))

# Enterprise Planning & Task Graph Engine
# Supported: mock | rules — unknown values fail fast.
PLANNER_PROVIDER = os.getenv("PLANNER_PROVIDER", "mock").strip().lower()
PLANNER_MAX_PARALLEL = int(os.getenv("PLANNER_MAX_PARALLEL", "4"))
PLANNER_MAX_DEPTH = int(os.getenv("PLANNER_MAX_DEPTH", "16"))
PLANNER_ENABLE_PARALLEL = os.getenv("PLANNER_ENABLE_PARALLEL", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Enterprise Decision Intelligence Engine
# Supported strategies: balanced | lowest_risk | lowest_cost | fastest_delivery |
# business_policy_first | mock — unknown values fail fast.
DECISION_ENABLED = os.getenv("DECISION_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DECISION_STRATEGY = os.getenv("DECISION_STRATEGY", "balanced").strip().lower()
DECISION_LLM_ADVISOR = os.getenv("DECISION_LLM_ADVISOR", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DECISION_CONFIDENCE_FLOOR = float(os.getenv("DECISION_CONFIDENCE_FLOOR", "0.45"))
DECISION_RISK_CEILING = float(os.getenv("DECISION_RISK_CEILING", "0.75"))

# Enterprise Tool Execution & Workflow Automation Engine
# Coordinates planner execution; checkpoints reuse AgentRunStateRow.state_json.
WORKFLOW_ENABLED = os.getenv("WORKFLOW_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
WORKFLOW_MAX_PARALLEL = int(os.getenv("WORKFLOW_MAX_PARALLEL", "4"))
WORKFLOW_DEFAULT_TIMEOUT_SECONDS = float(
    os.getenv("WORKFLOW_DEFAULT_TIMEOUT_SECONDS", "120")
)
WORKFLOW_RETRY_LIMIT = int(os.getenv("WORKFLOW_RETRY_LIMIT", "3"))
WORKFLOW_CHECKPOINTS_ENABLED = os.getenv(
    "WORKFLOW_CHECKPOINTS_ENABLED", "true"
).strip().lower() in {"1", "true", "yes", "on"}
WORKFLOW_COMPENSATION_ENABLED = os.getenv(
    "WORKFLOW_COMPENSATION_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}

# Enterprise Event Bus & Distributed Runtime (in-process today)
# Supported EVENT_PROVIDER: in_process | mock — unknown values fail fast.
# Kafka / RabbitMQ / Azure Service Bus / AWS SQS are NOT implemented yet.
EVENT_ENABLED = os.getenv("EVENT_ENABLED", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EVENT_PROVIDER = os.getenv("EVENT_PROVIDER", "in_process").strip().lower()
EVENT_RETRY_LIMIT = int(os.getenv("EVENT_RETRY_LIMIT", "3"))
EVENT_MAX_WORKERS = int(os.getenv("EVENT_MAX_WORKERS", "2"))
EVENT_ORDERING = os.getenv("EVENT_ORDERING", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EVENT_DEAD_LETTER = os.getenv("EVENT_DEAD_LETTER", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
EVENT_SYNC_DISPATCH = os.getenv("EVENT_SYNC_DISPATCH", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

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

# Human adjust / decline reason codes (controlled vocabulary).
ADJUST_REASON_CODES = (
    "local_demand_knowledge",
    "promotion_change",
    "store_closure",
    "supplier_constraint",
    "inventory_discrepancy",
    "merchandising_change",
    "seasonal_adjustment",
    "other",
)
DECLINE_REASON_CODES = ADJUST_REASON_CODES
REASON_CODE_LABELS = {
    "local_demand_knowledge": "Local demand knowledge",
    "promotion_change": "Promotion change",
    "store_closure": "Store closure",
    "supplier_constraint": "Supplier constraint",
    "inventory_discrepancy": "Inventory discrepancy",
    "merchandising_change": "Merchandising change",
    "seasonal_adjustment": "Seasonal adjustment",
    "other": "Other",
}

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
        "display_name": "Riley Smith",
        "role": ROLE_VIEWER,
    },
    "alex.store": {
        "display_name": "Alex Johnson",
        "role": ROLE_STORE_MANAGER,
    },
    "jamie.planner": {
        "display_name": "Jamie Richard",
        "role": ROLE_INVENTORY_PLANNER,
    },
    "casey.category": {
        "display_name": "Casey Adams",
        "role": ROLE_CATEGORY_MANAGER,
    },
    "admin.demo": {
        "display_name": "Dana Miller",
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
