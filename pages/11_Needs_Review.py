"""Needs your review — Overview tile drill-down."""

from __future__ import annotations

from ui_common import bootstrap_app
from ui_tile_detail import render_needs_review_detail


def main() -> None:
    user = bootstrap_app(
        "Needs your review | Retail Replenishment Agent",
        active_nav="overview",
    )
    render_needs_review_detail(
        actor=user["user_id"],
        actor_role=user["role"],
        session_id=user.get("session_id"),
    )


if __name__ == "__main__":
    main()
