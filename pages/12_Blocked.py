"""Blocked recommendations — Overview tile drill-down."""

from __future__ import annotations

from ui_common import bootstrap_app
from ui_tile_detail import render_blocked_detail


def main() -> None:
    user = bootstrap_app(
        "Blocked | Retail Replenishment Agent",
        active_nav="overview",
    )
    render_blocked_detail(actor=user["user_id"], actor_role=user["role"])


if __name__ == "__main__":
    main()
