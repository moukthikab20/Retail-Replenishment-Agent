"""Shared Streamlit UI helpers — Infolob application shell + auth gate."""

from __future__ import annotations

from typing import Any

import streamlit as st

from database.connection import init_db
from services import auth_service
from styles import inject_styles
from ui_components import initials, role_label

# Navigation targets (custom rail replaces Streamlit multipage nav).
_NAV_WORK = [
    ("Overview", "pages/0_Overview.py", "overview"),
    ("Today's Decisions", "pages/1_Todays_Queue.py", "todays_queue"),
    ("Approved for Purchase", "pages/2_Approved_Today.py", "approved_today"),
    ("Purchase Orders", "pages/3_Orders.py", "orders"),
]
_NAV_REFERENCE = [
    ("Summary", "pages/15_Summary.py", "summary"),
    ("Inventory", "pages/5_Inventory.py", "inventory"),
    ("Policies", "pages/6_Policy.py", "policy"),
    ("History", "pages/4_History.py", "history"),
]
_NAV_ADMIN = [
    ("Administration", "pages/9_Administration.py", "administration"),
    ("Agent Operations", "pages/10_Agent_Operations.py", "agent_operations"),
    ("System Health", "pages/7_Health.py", "health"),
]

_SESSION_TOKEN_KEY = "app_session_token"
_IDENTITY_CACHE_KEYS = (
    "authenticated",
    "user_id",
    "actor",
    "actor_display",
    "actor_role",
    "session_id",
    "authentication_source",
)


def _inject_shell_styles() -> None:
    """First UI operation on every page: hide default nav, then full design system."""
    st.markdown(f"<style>{inject_styles()}</style>", unsafe_allow_html=True)


def bootstrap_app(
    page_title: str,
    *,
    require_auth: bool = True,
    active_nav: str | None = None,
) -> dict[str, Any] | None:
    from services.perf_timing import perf_step

    with perf_step("bootstrap.page_config"):
        st.set_page_config(
            page_title=page_title,
            page_icon="📦",
            layout="wide",
            initial_sidebar_state="expanded",
        )
    with perf_step("bootstrap.inject_styles"):
        _inject_shell_styles()

    with perf_step("bootstrap.auth.resolve_user"):
        existing = get_current_user()
    shell_rendered = False
    if existing and existing.get("user_id"):
        with perf_step("bootstrap.render_topbar"):
            render_topbar(existing)
        with perf_step("bootstrap.render_left_nav"):
            render_left_nav(existing, active_nav=active_nav)
        shell_rendered = True
    elif not require_auth:
        render_topbar(existing)
        shell_rendered = True

    with perf_step("bootstrap.init_db"):
        init_db()

    if require_auth:
        with perf_step("bootstrap.require_login"):
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


def _clear_local_identity() -> None:
    st.session_state.pop(_SESSION_TOKEN_KEY, None)
    for key in _IDENTITY_CACHE_KEYS:
        st.session_state.pop(key, None)


def get_current_user() -> dict[str, Any] | None:
    """Return validated identity from the signed application session.

    Client-supplied actor_role is never trusted. If only legacy Streamlit keys
    are present (AppTests), role is re-bound from DEMO_USERS by user_id.
    """
    token = st.session_state.get(_SESSION_TOKEN_KEY)
    if token:
        try:
            identity = auth_service.validate_session(token)
        except auth_service.AuthError:
            # In-memory session registry may have been reset (server reload).
            # Keep authenticated + user_id so we can re-issue a session below.
            st.session_state.pop(_SESSION_TOKEN_KEY, None)
        else:
            st.session_state["authenticated"] = True
            st.session_state["user_id"] = identity.user_id
            st.session_state["actor"] = identity.user_id
            st.session_state["actor_display"] = identity.display_name
            st.session_state["actor_role"] = identity.role
            st.session_state["session_id"] = identity.session_id
            st.session_state["authentication_source"] = identity.authentication_source
            return identity.to_legacy_user_dict()

    # AppTest / recovery path: authenticated flag + user_id — rebind from catalog.
    if st.session_state.get("authenticated") and st.session_state.get("user_id"):
        user_id = str(st.session_state.get("user_id"))
        try:
            demo = auth_service.get_demo_user(user_id)
        except auth_service.AuthError:
            _clear_local_identity()
            return None
        identity = auth_service.identity_from_role(
            user_id=demo.user_id,
            display_name=demo.display_name,
            role=demo.role,
            session_id=str(st.session_state.get("session_id") or "SESS-test"),
            authentication_source="demo",
        )
        from integrations.auth.session_store import get_session_store

        new_token, record = get_session_store().create(identity)
        st.session_state[_SESSION_TOKEN_KEY] = new_token
        st.session_state["actor_role"] = record.identity.role
        st.session_state["actor_display"] = record.identity.display_name
        st.session_state["session_id"] = record.identity.session_id
        st.session_state["authentication_source"] = "demo"
        return record.identity.to_legacy_user_dict()
    return None


def establish_test_session(
    *,
    user_id: str,
    role: str | None = None,
    display_name: str | None = None,
) -> dict[str, Any]:
    """AppTest helper — issues a real signed session. Role is taken from DEMO_USERS."""
    demo = auth_service.get_demo_user(user_id)
    # Ignore client-provided role; DEMO_USERS is authoritative.
    _ = role
    identity = auth_service.identity_from_role(
        user_id=demo.user_id,
        display_name=display_name or demo.display_name,
        role=demo.role,
        authentication_source="demo",
    )
    from integrations.auth.session_store import get_session_store

    token, record = get_session_store().create(identity)
    st.session_state[_SESSION_TOKEN_KEY] = token
    st.session_state["authenticated"] = True
    st.session_state["user_id"] = record.identity.user_id
    st.session_state["actor"] = record.identity.user_id
    st.session_state["actor_display"] = record.identity.display_name
    st.session_state["actor_role"] = record.identity.role
    st.session_state["session_id"] = record.identity.session_id
    st.session_state["authentication_source"] = record.identity.authentication_source
    return record.identity.to_legacy_user_dict()


def _topbar_status_pill_html() -> str:
    from html import escape

    try:
        from services import scheduler_service

        cached_run_id = st.session_state.get("_topbar_metrics_run_id")
        cached_html = st.session_state.get("_topbar_status_pill_html")
        metrics = scheduler_service.get_topbar_run_metrics()
        run_id = metrics.get("run_id")
        if isinstance(cached_html, str) and cached_run_id == run_id:
            return cached_html
        text = str(
            metrics.get("status_pill")
            or scheduler_service.format_topbar_status_pill()
        )
    except Exception:  # noqa: BLE001
        text = "Monitoring inventory · First analysis in progress"
        run_id = None
    html = (
        '<div class="il-status-pill" role="status">'
        '<span class="il-status-dot" aria-hidden="true"></span>'
        f'<span class="il-status-text">{escape(text)}</span>'
        "</div>"
    )
    st.session_state["_topbar_metrics_run_id"] = run_id
    st.session_state["_topbar_status_pill_html"] = html
    return html


def _topbar_now_html() -> str:
    """Current Central Time clock for the fixed top bar (presentation only)."""
    from datetime import datetime, timezone
    from html import escape

    from services.schedule_time import resolve_timezone

    local = datetime.now(timezone.utc).astimezone(resolve_timezone("America/Chicago"))
    text = f"{local.strftime('%A, %B')} {local.day} · {local.strftime('%H:%M')} CT"
    return f'<div class="il-topbar-now">{escape(text)}</div>'


def render_topbar(user: dict[str, Any] | None = None) -> None:
    from html import escape

    avatar = initials(user.get("display_name") if user else None) if user else "IL"
    status_pill = _topbar_status_pill_html()
    now_clock = _topbar_now_html()
    right = now_clock
    if user and user.get("user_id"):
        display = escape(str(user.get("display_name") or ""))
        right = (
            f"{now_clock}"
            '<div class="il-demo-pill"><i></i> Demonstration Environment</div>'
            f'<div class="il-topbar-user">'
            f'<div class="il-avatar">{escape(avatar)}</div>'
            f'<div class="il-topbar-user-name">{display}</div>'
            f"</div>"
        )
    st.markdown(
        f"""
        <div class="il-topbar">
            <div class="il-brand">
                <div class="il-mark"><span>I</span></div>
                <div class="il-wm">INFOLOB<small>Retail Replenishment Agent</small></div>
            </div>
            {status_pill}
            <div class="il-spacer"></div>
            {right}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_left_nav(user: dict[str, Any], *, active_nav: str | None) -> None:
    """Custom left rail: nav + bottom-anchored account footer.

    Streamlit wraps every widget in its own DOM containers, so open/close
    HTML tags cannot create a flex parent. Use real ``st.container`` blocks:

    - ``il_rail_nav`` holds navigation only (flex: 0 0 auto)
    - ``il_rail_footer`` is a sibling of nav (margin-top: auto / flex-shrink: 0)

    Both containers are direct ``st.sidebar.container`` siblings. The rail
    column flex parent is the top-level ``stVerticalBlock`` inside
    ``stSidebarUserContent`` (styled in ``styles.py``).
    """
    from html import escape

    badges = _nav_badges()

    with st.sidebar.container(key="il_rail_nav", border=False, gap=None):
        st.markdown(
            '<div class="il-rail-group">Operations</div>',
            unsafe_allow_html=True,
        )
        for label, path, key in _NAV_WORK:
            _nav_button(
                label, path, key == active_nav, badge=badges.get(key)
            )

        st.markdown(
            '<div class="il-rail-group">Reference</div>',
            unsafe_allow_html=True,
        )
        for label, path, key in _NAV_REFERENCE:
            _nav_button(
                label, path, key == active_nav, badge=badges.get(key)
            )

        # Admin destinations remain available only for roles that can
        # view administration. Preserve existing RBAC exactly.
        if auth_service.can_view_administration(user["role"]):
            st.markdown(
                '<div class="il-rail-group">Administration</div>',
                unsafe_allow_html=True,
            )
            for label, path, key in _NAV_ADMIN:
                _nav_button(
                    label, path, key == active_nav, badge=badges.get(key)
                )

    with st.sidebar.container(key="il_rail_footer", border=False, gap=None):
        avatar = initials(user.get("display_name"))
        email = user.get("email")
        email_html = (
            f'<div class="email">{escape(str(email))}</div>' if email else ""
        )
        st.markdown(
            f'<div class="il-rail-footer"><div class="il-rail-user">'
            f'<div class="il-rail-user-main">'
            f'<div class="il-avatar-sm">{escape(avatar)}</div>'
            f'<div class="il-rail-user-text">'
            f'<div class="name">{escape(str(user.get("display_name") or ""))}</div>'
            f"{email_html}"
            f"</div></div></div></div>",
            unsafe_allow_html=True,
        )
        if st.button("Sign Out", key="il_sign_out"):
            auth_service.logout(
                session_token=st.session_state.get(_SESSION_TOKEN_KEY),
                session_id=user.get("session_id"),
            )
            _clear_local_identity()
            st.rerun()


def _nav_badges() -> dict[str, int]:
    """Lightweight counts for sidebar badges — existing read models only."""
    cached = st.session_state.get("_nav_badge_cache")
    if isinstance(cached, dict):
        return cached
    badges: dict[str, int] = {}
    try:
        from services import queue_service, purchase_order_service

        queue = queue_service.get_todays_queue(filter_key="all")
        summary = queue.get("summary") or {}
        needs = int(summary.get("needs_review") or 0)
        if needs:
            badges["todays_queue"] = needs
            badges["overview"] = needs
        approved = queue_service.get_approved_today(
            run_id=(queue.get("run") or {}).get("run_id")
        )
        approved_n = int((approved.get("summary") or {}).get("total") or 0)
        if approved_n:
            badges["approved_today"] = approved_n
        try:
            orders = purchase_order_service.get_orders_workbench()
            ready = int((orders.get("summary") or {}).get("ready_to_send") or 0)
            if ready:
                badges["orders"] = ready
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001
        badges = {}
    st.session_state["_nav_badge_cache"] = badges
    return badges


def _nav_button(
    label: str,
    path: str,
    active: bool,
    badge: int | None = None,
) -> None:
    # Must use st.* (active container context), not st.sidebar.*, so buttons
    # stay inside the nav container when render_left_nav nests them.
    if active:
        st.markdown(
            '<div class="il-nav-active-flag" style="display:none"></div>',
            unsafe_allow_html=True,
        )
    display = label
    clicked = st.button(display, key=f"il_nav_{path}", use_container_width=True)
    if badge:
        hot_cls = " hot" if path.endswith(("0_Overview.py", "1_Todays_Queue.py")) else ""
        st.markdown(
            f'<div class="il-nav-badge-slot" aria-hidden="true">'
            f'<span class="il-nav-badge{hot_cls}">{int(badge)}</span></div>',
            unsafe_allow_html=True,
        )
    if clicked:
        st.session_state.pop("_nav_badge_cache", None)
        st.switch_page(path)


def _commit_demo_session(identity: dict[str, Any]) -> None:
    """Apply a select_demo_user / authenticate payload to Streamlit session state."""
    st.session_state[_SESSION_TOKEN_KEY] = identity["session_token"]
    st.session_state["authenticated"] = True
    st.session_state["user_id"] = identity["user_id"]
    st.session_state["actor"] = identity["user_id"]
    st.session_state["actor_display"] = identity["display_name"]
    st.session_state["actor_role"] = identity["role"]
    st.session_state["session_id"] = identity["session_id"]
    st.session_state["authentication_source"] = identity.get(
        "authentication_source", "demo"
    )


def require_login() -> dict[str, Any]:
    """Block page content until a demo workspace user is selected."""
    user = get_current_user()
    if user and user.get("user_id"):
        return user

    # Pre-login: header only (logo, status pill, clock) — no avatar / demo user chrome.
    render_topbar(None)
    st.markdown(
        """
        <style>
        /* Login page chrome only — centering comes from Streamlit columns, not offsets */
        section[data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="collapsedControl"],
        [data-testid="stExpandSidebarButton"],
        button[data-testid="stExpandSidebarButton"] {
            display: none !important;
        }
        .stApp [data-testid="stAppViewContainer"] > .main,
        section.main {
            margin-top: var(--topbar-h, 64px) !important;
            background: #F7F9FB !important;
        }
        /* Fill usable viewport below header; vertically center the WHOLE login unit */
        .main .block-container {
            min-height: calc(100vh - var(--topbar-h, 64px)) !important;
            height: calc(100vh - var(--topbar-h, 64px)) !important;
            max-width: 100% !important;
            width: 100% !important;
            margin: 0 !important;
            padding: 0 20px !important;
            box-sizing: border-box !important;
            display: flex !important;
            flex-direction: column !important;
            justify-content: center !important;
            align-items: stretch !important;
        }
        .main .block-container > div[data-testid="stVerticalBlock"] {
            width: 100% !important;
            flex: 1 1 auto !important;
            min-height: 100% !important;
            display: flex !important;
            flex-direction: column !important;
            justify-content: center !important;
            align-items: stretch !important;
            gap: 0 !important;
        }
        /* Hide injected <style> row so it does not affect vertical centering */
        .main .block-container [data-testid="stElementContainer"]:has(style),
        .main .block-container [data-testid="element-container"]:has(style) {
            display: none !important;
            height: 0 !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
        }
        .il-login-module {
            width: 100%;
            text-align: center;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .il-user-login-icon {
            width: 96px;
            height: 96px;
            border-radius: 50%;
            background: #EEF2F5;
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 0 0 26px 0;
            flex-shrink: 0;
        }
        .il-user-login-icon svg {
            width: 48px;
            height: 48px;
            display: block;
        }
        .il-user-login-title {
            width: 100%;
            margin: 0 0 30px 0 !important;
            padding: 0 !important;
            font-size: 22px !important;
            font-weight: 700 !important;
            line-height: 1.25 !important;
            color: #1F2B3D !important;
            text-align: center !important;
        }
        /* Soften select look inside the login column only — no width/position overrides */
        [data-testid="stHorizontalBlock"] div[data-testid="stSelectbox"] label {
            display: none !important;
        }
        [data-testid="stHorizontalBlock"] div[data-testid="stSelectbox"] [data-baseweb="select"] > div {
            min-height: 52px !important;
            height: 52px !important;
            background-color: #FFFFFF !important;
            border: 1px solid #D9E1EA !important;
            border-radius: 12px !important;
            box-shadow: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    cfg = auth_service.public_auth_config()
    if not cfg.get("demo_mode"):
        st.error("This authentication provider is not available. Contact an administrator.")
        st.stop()
        return {}

    users = auth_service.list_demo_users()
    by_id = {u.user_id: u for u in users}

    def _format_user(uid: str) -> str:
        demo = by_id.get(uid)
        if demo is None:
            return str(uid)
        first = str(demo.display_name or "").split()[0] or demo.user_id
        return f"{first} — {role_label(demo.role)}"

    # STRUCTURAL centering: icon + title + selectbox share ONE Streamlit column.
    _left, login_col, _right = st.columns([1, 1.1, 1])
    with login_col:
        st.markdown(
            """
            <div class="il-login-module">
              <div class="il-user-login-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <circle cx="12" cy="8" r="3.25" stroke="#1C2B3A" stroke-width="1.55"/>
                  <path d="M5.5 19.25c.7-3.35 3.1-5 6.5-5s5.8 1.65 6.5 5"
                        stroke="#1C2B3A" stroke-width="1.55" stroke-linecap="round"/>
                </svg>
              </div>
              <div class="il-user-login-title">User Login</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        selected = st.selectbox(
            "Select a user",
            options=[u.user_id for u in users],
            format_func=_format_user,
            index=None,
            placeholder="Select a user",
            label_visibility="collapsed",
            key="il_user_login_select",
        )

    if selected:
        try:
            identity = auth_service.select_demo_user(str(selected))
            _commit_demo_session(identity)
            st.rerun()
        except auth_service.AuthError as exc:
            st.error(str(exc))

    st.stop()
    return {}  # pragma: no cover


def render_header(subtitle: str | None = None) -> None:
    from ui_components import page_heading

    page_heading("Retail Replenishment Agent", subtitle)


def render_card_header(title: str) -> None:
    from ui_components import card_title

    card_title(title)


def render_footer() -> None:
    return


def risk_badge_html(risk: str) -> str:
    from ui_components import risk_pill

    return risk_pill(risk)
