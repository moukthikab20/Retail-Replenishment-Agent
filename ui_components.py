"""Reusable Infolob UI building blocks (presentation only)."""

from __future__ import annotations

from html import escape
from typing import Any, Callable, Sequence

import streamlit as st

ROLE_LABELS = {
    "store_manager": "Store Manager",
    "inventory_planner": "Inventory Planner",
    "category_manager": "Category Manager",
    "administrator": "Administrator",
    "viewer": "Viewer",
}

# Shared agent / lifecycle language for business pages.
AGENT_LANGUAGE = {
    "analyzed": "Agent analyzed",
    "recommends": "Agent recommends",
    "handled_automatically": "Handled automatically",
    "needs_review": "Needs your review",
    "cannot_proceed": "Cannot proceed",
    "no_order": "No order needed",
    "ready_to_send": "Ready to send",
    "accepted": "Accepted",
    "retry_scheduled": "Retry scheduled",
}

# Status semantics — prefer these kinds; aliases map for backward compatibility.
STATUS_KINDS = {
    "neutral": "neutral",
    "success": "success",
    "ok": "success",
    "attention": "attention",
    "warn": "attention",
    "warning": "warning",
    "critical": "critical",
    "danger": "critical",
    "progress": "progress",
    "info": "progress",
    "in_progress": "progress",
    "stockout": "critical",
    "overstock": "attention",
    "balanced": "success",
    "manual_review": "attention",
    "insufficient_data": "attention",
    "pending": "progress",
    "approved": "success",
    "rejected": "critical",
}


def role_label(role: str | None) -> str:
    if not role:
        return ""
    return ROLE_LABELS.get(role, str(role).replace("_", " ").title())


def initials(name: str | None) -> str:
    parts = [p for p in str(name or "").split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def status_pill(kind: str, text: str) -> str:
    """Status chip with text label (color is never the only cue)."""
    css = STATUS_KINDS.get((kind or "").strip().lower(), "neutral")
    label = escape(str(text or "—"))
    return (
        f'<span class="il-pill {css}" role="status" '
        f'title="{label}" aria-label="{label}">{label}</span>'
    )


def risk_pill(risk: str) -> str:
    labels = {
        "stockout": "Stockout Risk",
        "overstock": "Overstock Risk",
        "balanced": "Balanced",
        "manual_review": "Manual Review",
        "insufficient_data": "Insufficient Data",
    }
    return status_pill(risk, labels.get(risk, risk.replace("_", " ").title()))


def page_heading(title: str, subtitle: str | None = None) -> None:
    sub = f"<p class='il-page-sub'>{escape(subtitle)}</p>" if subtitle else ""
    st.markdown(
        f'<div class="il-page-head"><h1 class="il-type-page">{escape(title)}</h1>{sub}</div>',
        unsafe_allow_html=True,
    )


def section_heading(title: str, hint: str | None = None) -> None:
    hint_html = (
        f'<span class="il-type-caption hint">{escape(hint)}</span>' if hint else ""
    )
    st.markdown(
        f'<h2 class="il-section-title il-type-section">{escape(title)}{hint_html}</h2>',
        unsafe_allow_html=True,
    )


def card_title(title: str, hint: str | None = None) -> None:
    """Card / panel title — 13px medium uppercase (not a section heading)."""
    hint_html = f'<span class="hint">{escape(hint)}</span>' if hint else ""
    st.markdown(
        f'<h3 class="il-panel-title il-type-card">{escape(title)}{hint_html}</h3>',
        unsafe_allow_html=True,
    )


def kpi_row(items: Sequence[dict[str, Any]], *, columns: int | None = None) -> None:
    """Compact metric strip. Prefer this (or compact_kpi_row) over giant metric cards."""
    compact_kpi_row(items, columns=columns)


def compact_kpi_row(
    items: Sequence[dict[str, Any]],
    *,
    columns: int | None = None,
    column_template: str | None = None,
    row_class: str = "",
) -> None:
    """Dense KPI strip for Overview and workbenches."""
    n = columns or max(len(items), 1)
    template = column_template or f"repeat({n},minmax(0,1fr))"
    style = f'style="grid-template-columns:{template}"'
    extra = f" {row_class.strip()}" if row_class.strip() else ""
    cards = []
    for item in items:
        accent = " accent" if item.get("accent") else ""
        textish = " il-kpi-text" if item.get("text_value") else ""
        sub = item.get("sub")
        sub_html = (
            f'<div class="sub">{escape(str(sub))}</div>' if sub else ""
        )
        cards.append(
            f'<div class="il-kpi il-kpi-compact{accent}{textish}">'
            f'<div class="lab">{escape(str(item["label"]))}</div>'
            f'<div class="val">{escape(str(item["value"]))}</div>'
            f"{sub_html}"
            f"</div>"
        )
    st.markdown(
        f'<div class="il-kpi-row il-kpi-row-compact{extra}" {style}>{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def panel_title(title: str, hint: str | None = None) -> None:
    card_title(title, hint)


def panel_open(title: str, hint: str | None = None) -> None:
    """Deprecated alias — prefer st.container(border=True) + panel_title."""
    panel_title(title, hint)


def panel_close() -> None:
    return


def empty_state(
    *,
    title: str,
    explanation: str,
    next_step: str | None = None,
    primary_label: str | None = None,
    primary_action: Callable[[], None] | None = None,
    primary_disabled: bool = False,
    secondary_label: str | None = None,
    secondary_action: Callable[[], None] | None = None,
    schedule_or_status: str | None = None,
    key_prefix: str = "empty",
    bordered: bool = True,
) -> None:
    """
    Reusable business empty state:
    title, explanation, next step, primary/secondary CTAs, optional schedule/status.
    """
    def _e(value: str) -> str:
        # Escape markup only — keep apostrophes readable in AppTests / a11y text.
        return escape(value, quote=False)

    meta = (
        f'<p class="il-empty-meta">{_e(schedule_or_status)}</p>'
        if schedule_or_status
        else ""
    )
    next_html = f'<p class="il-empty-next">{_e(next_step)}</p>' if next_step else ""
    html = (
        f'<div class="il-empty" role="status">'
        f'<h2 class="il-empty-title">{_e(title)}</h2>'
        f'<p class="il-empty-body">{_e(explanation)}</p>'
        f"{next_html}{meta}</div>"
    )
    if bordered:
        with st.container(border=True):
            st.markdown(html, unsafe_allow_html=True)
            _empty_actions(
                primary_label=primary_label,
                primary_action=primary_action,
                primary_disabled=primary_disabled,
                secondary_label=secondary_label,
                secondary_action=secondary_action,
                key_prefix=key_prefix,
            )
    else:
        st.markdown(html, unsafe_allow_html=True)
        _empty_actions(
            primary_label=primary_label,
            primary_action=primary_action,
            primary_disabled=primary_disabled,
            secondary_label=secondary_label,
            secondary_action=secondary_action,
            key_prefix=key_prefix,
        )


def _empty_actions(
    *,
    primary_label: str | None,
    primary_action: Callable[[], None] | None,
    primary_disabled: bool,
    secondary_label: str | None,
    secondary_action: Callable[[], None] | None,
    key_prefix: str,
) -> None:
    if not primary_label and not secondary_label:
        return
    cols = st.columns([1, 1, 2] if secondary_label else [1, 3])
    if primary_label:
        with cols[0]:
            if st.button(
                primary_label,
                type="primary",
                use_container_width=True,
                disabled=primary_disabled,
                key=f"{key_prefix}_primary",
            ):
                if primary_action:
                    primary_action()
    if secondary_label:
        with cols[1]:
            if st.button(
                secondary_label,
                use_container_width=True,
                key=f"{key_prefix}_secondary",
            ):
                if secondary_action:
                    secondary_action()


def info_grid(rows: Sequence[tuple[str, Any]]) -> None:
    cells = []
    for label, value in rows:
        cells.append(
            f'<div class="il-kpi il-kpi-compact">'
            f'<div class="lab">{escape(str(label))}</div>'
            f'<div class="val" style="font-size:var(--type-body)">'
            f"{escape(str(value))}</div>"
            f"</div>"
        )
    st.markdown(
        f'<div class="il-kpi-row il-kpi-row-compact" '
        f'style="grid-template-columns:repeat(3,minmax(0,1fr))">'
        f'{"".join(cells)}</div>',
        unsafe_allow_html=True,
    )
