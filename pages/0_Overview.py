"""Replenishment Overview — primary business landing page."""

from __future__ import annotations

from ui_common import bootstrap_app
from ui_overview import render_replenishment_overview


def main() -> None:
    user = bootstrap_app(
        "Overview | Retail Replenishment Agent",
        active_nav="overview",
    )
    render_replenishment_overview(
        actor=user["user_id"],
        actor_role=user["role"],
        session_id=user.get("session_id"),
        display_name=user.get("display_name"),
    )


if __name__ == "__main__":
    main()
