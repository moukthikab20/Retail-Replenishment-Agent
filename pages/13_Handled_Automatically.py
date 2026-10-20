"""Handled automatically — Overview tile drill-down."""

from __future__ import annotations

from ui_common import bootstrap_app
from ui_tile_detail import render_automated_detail


def main() -> None:
    bootstrap_app(
        "Handled automatically | Retail Replenishment Agent",
        active_nav="overview",
    )
    render_automated_detail()


if __name__ == "__main__":
    main()
