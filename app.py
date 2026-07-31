"""Retail replenishment agent — Streamlit home entry point."""

from __future__ import annotations

import streamlit as st

from ui_common import bootstrap_app, render_dev_identity, render_footer, render_header


def main() -> None:
    bootstrap_app("Retail Replenishment Agent | Infolob")
    render_header("Agentic AI POC · OpenAI Agents SDK · Human-in-the-loop approval")
    render_dev_identity()

    st.markdown(
        """
        <div class="card"><div class="card-body">
        <p class="secondary-text">
        This application uses a single <strong>Retail Replenishment Agent</strong>
        with deterministic Python services for forecasting, replenishment, risk,
        human review validation, approval, and mock purchase orders.
        </p>
        <p class="secondary-text">
        Workflow: <strong>Analysis</strong> → <strong>Human Review</strong> →
        formal approval → mock purchase order.
        </p>
        </div></div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Start Analysis", type="primary", use_container_width=True):
            st.switch_page("pages/1_Analysis.py")
    with col2:
        if st.button("Open Human Review", type="secondary", use_container_width=True):
            st.switch_page("pages/2_Human_Review.py")

    render_footer()


if __name__ == "__main__":
    main()
