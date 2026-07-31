"""Shared Streamlit UI helpers (Infolob design system)."""

from __future__ import annotations

import streamlit as st

from config import DEV_USERS
from database.connection import init_db
from styles import inject_styles


def bootstrap_app(page_title: str) -> None:
    st.set_page_config(
        page_title=page_title,
        page_icon="📦",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(f"<style>{inject_styles()}</style>", unsafe_allow_html=True)
    init_db()


def render_header(subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="page-title-wrap">
            <div class="title-stripe"></div>
            <h1 class="page-title">Retail Replenishment Agent</h1>
        </div>
        <p class="page-subtitle">{subtitle}</p>
        """,
        unsafe_allow_html=True,
    )


def render_card_header(title: str) -> None:
    st.markdown(f'<div class="card-header">{title}</div>', unsafe_allow_html=True)


def render_footer() -> None:
    st.markdown(
        """
        <div class="footer-bar">
            <span>© 2026 Infolob Solutions · Confidential</span>
            <span class="footer-brand">INFOLOB</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_dev_identity() -> tuple[str, str, str]:
    """Development-only simulated user identity and role selector."""
    st.sidebar.markdown("### Development identity")
    st.sidebar.caption("Simulated users for local POC only — not production auth.")
    options = list(DEV_USERS.keys())
    selected = st.sidebar.selectbox(
        "Acting as",
        options=options,
        format_func=lambda key: f"{DEV_USERS[key]['display_name']} ({DEV_USERS[key]['role']})",
        key="dev_user_key",
    )
    user = DEV_USERS[selected]
    st.session_state["actor"] = selected
    st.session_state["actor_role"] = user["role"]
    st.session_state["actor_display"] = user["display_name"]
    return selected, user["display_name"], user["role"]


def risk_badge_html(risk: str) -> str:
    mapping = {
        "stockout": ("risk-stockout", "Stockout Risk"),
        "overstock": ("risk-overstock", "Overstock Risk"),
        "balanced": ("risk-balanced", "Balanced"),
        "manual_review": ("risk-overstock", "Manual Review"),
        "insufficient_data": ("risk-overstock", "Insufficient Data"),
    }
    css, label = mapping.get(risk, ("risk-balanced", risk.title()))
    return f'<span class="risk-badge {css}">{label}</span>'
