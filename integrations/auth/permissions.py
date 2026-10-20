"""Explicit permission catalog mapped from the five-role hierarchy."""

from __future__ import annotations

from config import ROLE_HIERARCHY

# Canonical permission names (UI + services).
VIEW_ANALYSIS = "view_analysis"
VIEW_QUEUE = "view_queue"
VIEW_ORDERS = "view_orders"
VIEW_HISTORY = "view_history"
VIEW_HEALTH = "view_health"
VIEW_INVENTORY = "view_inventory"
VIEW_POLICY = "view_policy"
RUN_ANALYSIS = "run_analysis"
REVIEW_RECOMMENDATION = "review_recommendation"
ADJUST_QUANTITY = "adjust_quantity"
FORMAL_APPROVAL = "formal_approval"
CREATE_PURCHASE_ORDER = "create_purchase_order"
TRIGGER_MANUAL_BATCH = "trigger_manual_batch"
VIEW_AGENT_OPERATIONS = "view_agent_operations"
VIEW_ADMINISTRATION = "view_administration"
RESET_DEMO_DATA = "reset_demo_data"
EDIT_POLICY = "edit_policy"
RECALL_AUTO_RELEASE = "recall_auto_release"
MANUAL_QUANTITY_BLOCKED = "manual_quantity_blocked"
RETRY_BLOCKED = "retry_blocked"

_BASE_VIEWER = frozenset(
    {
        VIEW_ANALYSIS,
        VIEW_QUEUE,
        VIEW_ORDERS,
        VIEW_HISTORY,
        VIEW_HEALTH,
        VIEW_INVENTORY,
        VIEW_POLICY,
    }
)

_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "viewer": _BASE_VIEWER,
    "store_manager": _BASE_VIEWER
    | frozenset(
        {
            RUN_ANALYSIS,
            REVIEW_RECOMMENDATION,
            ADJUST_QUANTITY,
            FORMAL_APPROVAL,
            CREATE_PURCHASE_ORDER,
            RETRY_BLOCKED,
        }
    ),
    "inventory_planner": _BASE_VIEWER
    | frozenset(
        {
            RUN_ANALYSIS,
            REVIEW_RECOMMENDATION,
            ADJUST_QUANTITY,
            FORMAL_APPROVAL,
            CREATE_PURCHASE_ORDER,
            RETRY_BLOCKED,
            MANUAL_QUANTITY_BLOCKED,
        }
    ),
    "category_manager": _BASE_VIEWER
    | frozenset(
        {
            RUN_ANALYSIS,
            REVIEW_RECOMMENDATION,
            ADJUST_QUANTITY,
            FORMAL_APPROVAL,
            CREATE_PURCHASE_ORDER,
            RETRY_BLOCKED,
            MANUAL_QUANTITY_BLOCKED,
            RECALL_AUTO_RELEASE,
        }
    ),
    "administrator": _BASE_VIEWER
    | frozenset(
        {
            RUN_ANALYSIS,
            REVIEW_RECOMMENDATION,
            ADJUST_QUANTITY,
            FORMAL_APPROVAL,
            CREATE_PURCHASE_ORDER,
            RETRY_BLOCKED,
            MANUAL_QUANTITY_BLOCKED,
            RECALL_AUTO_RELEASE,
            TRIGGER_MANUAL_BATCH,
            VIEW_AGENT_OPERATIONS,
            VIEW_ADMINISTRATION,
            RESET_DEMO_DATA,
            EDIT_POLICY,
        }
    ),
}


def permissions_for_roles(roles: list[str] | tuple[str, ...]) -> frozenset[str]:
    granted: set[str] = set()
    for role in roles:
        granted |= set(_ROLE_PERMISSIONS.get(role, frozenset()))
    return frozenset(granted)


def primary_role(roles: list[str] | tuple[str, ...]) -> str:
    if not roles:
        return "viewer"
    return max(roles, key=lambda r: ROLE_HIERARCHY.get(r, 0))
