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
TRACE_SENSITIVE_DATA = os.getenv("TRACE_SENSITIVE_DATA", "false").lower() in {
    "1",
    "true",
    "yes",
}

AS_OF_DATE = "2026-07-27"
FORECAST_LOOKBACK_DAYS = 7
FORECAST_HORIZON_DAYS = 7
AGENT_MAX_TURNS = 12

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

# Approval roles (development-only simulated identities)
ROLE_STORE_MANAGER = "store_manager"
ROLE_INVENTORY_PLANNER = "inventory_planner"
ROLE_CATEGORY_MANAGER = "category_manager"

DEV_USERS = {
    "alex.store": {"display_name": "Alex Store Manager", "role": ROLE_STORE_MANAGER},
    "jamie.planner": {"display_name": "Jamie Inventory Planner", "role": ROLE_INVENTORY_PLANNER},
    "casey.category": {"display_name": "Casey Category Manager", "role": ROLE_CATEGORY_MANAGER},
}

# Roles allowed for normal vs elevated approval
NORMAL_APPROVAL_ROLES = {ROLE_STORE_MANAGER, ROLE_INVENTORY_PLANNER, ROLE_CATEGORY_MANAGER}
ELEVATED_APPROVAL_ROLES = {ROLE_INVENTORY_PLANNER, ROLE_CATEGORY_MANAGER}
