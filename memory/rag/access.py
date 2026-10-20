"""Knowledge access-scope filtering — before content reaches the LLM."""

from __future__ import annotations

from config import ROLE_HIERARCHY, ROLE_ADMINISTRATOR, ROLE_INVENTORY_PLANNER, ROLE_VIEWER
from memory.rag.contracts import AccessScope


# Minimum role rank required to see each scope.
_SCOPE_MIN_RANK: dict[str, int] = {
    AccessScope.PUBLIC.value: ROLE_HIERARCHY.get(ROLE_VIEWER, 1),
    AccessScope.OPERATIONS.value: ROLE_HIERARCHY.get("store_manager", 2),
    AccessScope.PLANNER.value: ROLE_HIERARCHY.get(ROLE_INVENTORY_PLANNER, 3),
    AccessScope.ADMINISTRATOR.value: ROLE_HIERARCHY.get(ROLE_ADMINISTRATOR, 5),
}


def role_rank(actor_role: str | None) -> int:
    if not actor_role:
        return 0
    return int(ROLE_HIERARCHY.get(str(actor_role).strip().lower(), 0))


def allowed_scopes_for_role(actor_role: str | None) -> list[str]:
    rank = role_rank(actor_role)
    # Unauthenticated / unknown role: public only.
    if rank <= 0:
        return [AccessScope.PUBLIC.value]
    return [scope for scope, need in _SCOPE_MIN_RANK.items() if rank >= need]


def can_access_scope(actor_role: str | None, access_scope: str | None) -> bool:
    scope = (access_scope or AccessScope.PUBLIC.value).strip().lower()
    return scope in set(allowed_scopes_for_role(actor_role))
