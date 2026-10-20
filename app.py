"""app.py — Retail replenishment agent landing redirects to Overview."""

from __future__ import annotations

import streamlit as st

from ui_common import bootstrap_app


def main() -> None:
    bootstrap_app(
        "Overview | Retail Replenishment Agent",
        active_nav="overview",
    )
    st.switch_page("pages/0_Overview.py")


if __name__ == "__main__":
    main()
