"""Shared Streamlit UI helpers — Infolob application shell + auth gate."""

from __future__ import annotations

from typing import Any

import streamlit as st

from database.connection import init_db
from services import auth_service
from styles import inject_styles
from ui_components import initials, role_label

# Navigation targets (custom rail replaces Streamlit multipage nav).
_NAV_OPERATIONS = [
    ("Analysis", "pages/1_Analysis.py", "analysis"),
    ("Review", "pages/2_Review.py", "review"),
    ("Orders", "pages/3_Orders.py", "orders"),
    ("History", "pages/4_History.py", "history"),
]
_NAV_SYSTEM = [
    ("Health", "pages/5_Health.py", "health"),
    ("Administration", "pages/6_Administration.py", "administration"),
]


def _inject_shell_styles() -> None:
    """First UI operation on every page: hide default nav, then full design system."""
    # inject_styles() already prefixes CRITICAL_SHELL_CSS.
    st.markdown(f"<style>{inject_styles()}</style>", unsafe_allow_html=True)


def bootstrap_app(
    page_title: str,
    *,
    require_auth: bool = True,
    active_nav: str | None = None,  # left-rail highlight key; optional for all pages
) -> dict[str, Any] | None:
    st.set_page_config(
        page_title=page_title,
        page_icon="📦",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    # Must run before auth / DB / page work so default multipage links never flash.
    _inject_shell_styles()

    existing = get_current_user()
    shell_rendered = False
    if existing and existing.get("user_id"):
        # Paint custom rail immediately for authenticated sessions (before DB/auth work).
        render_topbar(existing)
        render_left_nav(existing, active_nav=active_nav)
        shell_rendered = True
    elif not require_auth:
        render_topbar(existing)
        shell_rendered = True

    init_db()

    if require_auth:
        user = require_login()
        if not shell_rendered and user and user.get("user_id"):
            render_topbar(user)
            render_left_nav(user, active_nav=active_nav)
        return user

    user = get_current_user()
    if not shell_rendered:
        render_topbar(user)
        if user and user.get("user_id"):
            render_left_nav(user, active_nav=active_nav)
    return user


def get_current_user() -> dict[str, Any] | None:
    if not st.session_state.get("authenticated"):
        return None
    return {
        "user_id": st.session_state.get("user_id"),
        "display_name": st.session_state.get("actor_display"),
        "role": st.session_state.get("actor_role"),
        "session_id": st.session_state.get("session_id"),
    }


def render_topbar(user: dict[str, Any] | None = None) -> None:
    avatar = initials(user.get("display_name") if user else None) if user else "IL"
    pill = ""
    if user and user.get("user_id"):
        pill = (
            '<div class="il-demo-pill"><i></i> Demonstration Environment</div>'
            f'<div class="il-avatar">{avatar}</div>'
        )
    st.markdown(
        f"""
        <div class="il-topbar">
            <div class="il-brand">
                <div class="il-mark"><span>I</span></div>
                <div class="il-wm">INFOLOB<small>Retail Replenishment Agent</small></div>
            </div>
            <div class="il-spacer"></div>
            {pill}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_left_nav(user: dict[str, Any], *, active_nav: str | None) -> None:
    st.sidebar.markdown('<div class="il-rail-group">Operations</div>', unsafe_allow_html=True)
    for label, path, key in _NAV_OPERATIONS:
        _nav_button(label, path, key == active_nav)

    st.sidebar.markdown('<div class="il-rail-group">System</div>', unsafe_allow_html=True)
    for label, path, key in _NAV_SYSTEM:
        if key == "administration" and not auth_service.can_reset_demo(user["role"]):
            continue
        _nav_button(label, path, key == active_nav)

    st.sidebar.markdown(
        f"""
        <div class="il-rail-user">
            <div class="name">{user.get("display_name") or ""}</div>
            <div class="role">{role_label(user.get("role"))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.sidebar.button("Sign Out", key="il_sign_out"):
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


def _nav_button(label: str, path: str, active: bool) -> None:
    if active:
        st.sidebar.markdown(
            '<div class="il-nav-active-flag" style="display:none"></div>',
            unsafe_allow_html=True,
        )
    if st.sidebar.button(label, key=f"il_nav_{path}", use_container_width=True):
        st.switch_page(path)


def require_login() -> dict[str, Any]:
    """Block page content until a valid access code + named user are selected."""
    user = get_current_user()
    if user and user.get("user_id"):
        return user

    render_topbar(None)
    st.markdown(
        """
        <style>
        /* Hide empty login rail only — keep reopen control available */
        section[data-testid="stSidebar"] { display: none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="il-login-wrap">', unsafe_allow_html=True)
    st.markdown(
        """
        <div class="il-page-head"><h1>Retail Replenishment Agent</h1></div>
        <div class="il-panel">
        <p class="secondary-text" style="margin:0">
        Enter the demo code and select a user.
        </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    users = auth_service.list_demo_users()
    with st.form("demo_login_form"):
        access_code = st.text_input("Demo access code", type="password")
        selected = st.selectbox(
            "User",
            options=[u.user_id for u in users],
            format_func=lambda uid: next(
                f"{u.display_name} ({role_label(u.role)})" for u in users if u.user_id == uid
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

    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()
    return {}  # pragma: no cover


# Backwards-compatible helpers used by older call sites.
def render_header(subtitle: str | None = None) -> None:
    from ui_components import page_heading

    page_heading("Retail Replenishment Agent", subtitle)


def render_card_header(title: str) -> None:
    st.markdown(f"<h3 style='margin:0 0 12px 0;font-size:14px'>{title}</h3>", unsafe_allow_html=True)


def render_footer() -> None:
    """Footer intentionally omitted — brand lives in the top bar / rail."""
    return


def risk_badge_html(risk: str) -> str:
    from ui_components import risk_pill

    return risk_pill(risk)
