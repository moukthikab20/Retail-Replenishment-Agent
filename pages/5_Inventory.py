"""Inventory on Hand — current stock position by store and product."""

from __future__ import annotations

import streamlit as st

from ui_common import bootstrap_app
from ui_components import page_heading
from ui_inventory import render_inventory_on_hand


def main() -> None:
    bootstrap_app(
        "Inventory | Retail Replenishment Agent",
        active_nav="inventory",
    )
    page_heading(
        "Inventory on Hand",
        "Current stock position by store and product, including inbound inventory and replenishment risk.",
    )
    render_inventory_on_hand()


if __name__ == "__main__":
    main()
