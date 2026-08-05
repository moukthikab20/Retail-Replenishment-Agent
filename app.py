"""Retail replenishment agent — Streamlit home entry point."""

from __future__ import annotations

import streamlit as st

from ui_common import bootstrap_app
from ui_components import page_heading, role_label


def main() -> None:
    user = bootstrap_app("Retail Replenishment Agent | Infolob", active_nav=None)
    page_heading("Home")

    st.markdown(
        f"""
        <div class="il-welcome">
            <div class="lab">Signed In</div>
            <div class="val">{user['display_name']}</div>
            <div class="lab">Role</div>
            <div class="val">{role_label(user['role'])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Start Analysis", type="primary", use_container_width=True):
            st.switch_page("pages/1_Analysis.py")
    with col2:
        if st.button("Open Review", type="secondary", use_container_width=True):
            st.switch_page("pages/2_Review.py")


if __name__ == "__main__":
    main()
