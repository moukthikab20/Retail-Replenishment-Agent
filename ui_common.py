"""Shared Streamlit UI helpers (Infolob design system + demo auth gate)."""

from __future__ import annotations

from typing import Any

import streamlit as st

from database.connection import init_db
from services import auth_service
from styles import inject_styles


def bootstrap_app(page_title: str, *, require_auth: bool = True) -> dict[str, Any] | None:
    st.set_page_config(
        page_title=page_title,
        page_icon="📦",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(f"<style>{inject_styles()}</style>", unsafe_allow_html=True)
    render_demo_banner()
    init_db()
    if require_auth:
        return require_login()
    return get_current_user()


def render_demo_banner() -> None:
    st.markdown(
        '<div class="demo-banner">'
        "Demonstration Environment — sample data — no real supplier orders."
        "</div>",
        unsafe_allow_html=True,
    )


def get_current_user() -> dict[str, Any] | None:
    if not st.session_state.get("authenticated"):
        return None
    return {
        "user_id": st.session_state.get("user_id"),
        "display_name": st.session_state.get("actor_display"),
        "role": st.session_state.get("actor_role"),
        "session_id": st.session_state.get("session_id"),
    }


def require_login() -> dict[str, Any]:
    """Block page content until a valid access code + named user are selected."""
    user = get_current_user()
    if user and user.get("user_id"):
        _render_auth_sidebar(user)
        return user

    render_header("Demonstration login")
    st.markdown(
        """
        <div class="card"><div class="card-body">
        <p class="secondary-text">
        Enter the demo access code and select a named user.
        Authorization is enforced in Python services — not by the language model.
        </p>
        </div></div>
        """,
        unsafe_allow_html=True,
    )

    users = auth_service.list_demo_users()
    with st.form("demo_login_form"):
        access_code = st.text_input(
            "Demo access code",
            type="password",
            help="Provided by the demo host. Never commit real secrets.",
        )
        selected = st.selectbox(
            "Named demo user",
            options=[u.user_id for u in users],
            format_func=lambda uid: next(
                f"{u.display_name} ({u.role})" for u in users if u.user_id == uid
            ),
        )
        submitted = st.form_submit_button("Sign in", type="primary")

    if submitted:
        try:
            identity = auth_service.authenticate(access_code, selected)
            st.session_state["authenticated"] = True
            st.session_state["user_id"] = identity["user_id"]
            st.session_state["actor"] = identity["user_id"]
            st.session_state["actor_display"] = identity["display_name"]
            st.session_state["actor_role"] = identity["role"]
            st.session_state["session_id"] = identity["session_id"]
            st.rerun()
        except auth_service.AuthError as exc:
            st.error(str(exc))

    # Do not expose the actual access code value to the browser.
    cfg = auth_service.public_auth_config()
    st.caption(
        f"Environment: {cfg['app_env']} · "
        f"Access code configured: {'yes' if cfg['access_code_configured'] else 'no'}"
    )
    render_footer()
    st.stop()
    return {}  # pragma: no cover


def _render_auth_sidebar(user: dict[str, Any]) -> None:
    st.sidebar.markdown("### Signed in")
    st.sidebar.write(f"**{user['display_name']}**")
    st.sidebar.caption(f"Role: `{user['role']}`")
    st.sidebar.caption(f"User: `{user['user_id']}`")
    st.sidebar.caption(f"Session: `{user['session_id']}`")
    st.sidebar.caption("Demo authentication — not production SSO.")

    from services import rate_limit_service

    remaining = rate_limit_service.remaining_agent_runs(user["user_id"])
    if remaining is not None:
        st.sidebar.caption(f"Agent runs remaining (window): {remaining}")

    if auth_service.can_reset_demo(user["role"]):
        st.sidebar.markdown("### Administrator")
        if st.sidebar.button("Reset Demo Data", type="secondary"):
            try:
                from services.demo_data_service import reset_and_seed
                from services.errors import user_facing_error

                result = reset_and_seed(actor=user["user_id"], actor_role=user["role"])
                st.session_state.pop("analysis_decision", None)
                st.session_state.pop("recommendation_id", None)
                st.session_state.pop("nav_recommendation_id", None)
                st.session_state.pop("approval_id", None)
                st.session_state.pop("order_flow", None)
                st.sidebar.success("Demo data reset and reseeded.")
                st.sidebar.json(
                    {
                        "deleted": result.get("reset", {}).get("deleted"),
                        "seed": result.get("seed", {}).get("status"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                from services.errors import user_facing_error

                st.sidebar.error(user_facing_error(exc))

    if st.sidebar.button("Sign out"):
        for key in (
            "authenticated",
            "user_id",
            "actor",
            "actor_display",
            "actor_role",
            "session_id",
        ):
            st.session_state.pop(key, None)
        st.rerun()


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
