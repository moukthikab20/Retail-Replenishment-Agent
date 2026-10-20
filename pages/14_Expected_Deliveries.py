"""Expected deliveries — Overview tile drill-down."""

from __future__ import annotations

from ui_common import bootstrap_app
from ui_tile_detail import render_deliveries_detail


def main() -> None:
    bootstrap_app(
        "Expected deliveries | Retail Replenishment Agent",
        active_nav="overview",
    )
    render_deliveries_detail()


if __name__ == "__main__":
    main()
