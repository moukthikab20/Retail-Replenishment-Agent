"""Purchase Orders — operational purchasing lifecycle (queue ≠ transmit)."""

from __future__ import annotations

from ui_common import bootstrap_app
from ui_orders import render_orders_page


def main() -> None:
    user = bootstrap_app(
        "Purchase Orders | Retail Replenishment Agent",
        active_nav="orders",
    )
    render_orders_page(user)


main()
