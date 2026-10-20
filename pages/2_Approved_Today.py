"""Approved for Purchase — business lifecycle after replenishment approval."""

from __future__ import annotations

from ui_common import bootstrap_app
from ui_orders import render_approved_page


def main() -> None:
    bootstrap_app(
        "Approved for Purchase | Retail Replenishment Agent",
        active_nav="approved_today",
    )
    render_approved_page()


if __name__ == "__main__":
    main()
