"""Today's Queue — primary exception-management workbench."""

from __future__ import annotations

from ui_common import bootstrap_app
from ui_queue import render_todays_queue


def main() -> None:
    user = bootstrap_app(
        "Today's Decisions | Retail Replenishment Agent",
        active_nav="todays_queue",
    )
    render_todays_queue(
        actor=user["user_id"],
        actor_role=user["role"],
        session_id=user["session_id"],
    )


if __name__ == "__main__":
    main()
