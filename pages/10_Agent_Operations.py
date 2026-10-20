"""Agent Operations — durable execution monitoring (administrators)."""

from __future__ import annotations

from ui_agent_ops import render_agent_operations
from ui_common import bootstrap_app


def main() -> None:
    user = bootstrap_app(
        "Agent Operations | Retail Replenishment Agent",
        active_nav="agent_operations",
    )
    render_agent_operations(actor_role=user["role"])


if __name__ == "__main__":
    main()
