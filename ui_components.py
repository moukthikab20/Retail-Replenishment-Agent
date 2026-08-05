"""Reusable Infolob UI building blocks (presentation only)."""

from __future__ import annotations

from html import escape
from typing import Any, Sequence

import streamlit as st

ROLE_LABELS = {
    "store_manager": "Store Manager",
    "inventory_planner": "Inventory Planner",
    "category_manager": "Category Manager",
    "administrator": "Administrator",
    "viewer": "Viewer",
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
    css = {
        "ok": "ok",
        "warn": "warn",
        "danger": "danger",
        "neutral": "neutral",
        "stockout": "danger",
        "overstock": "warn",
        "balanced": "ok",
        "manual_review": "warn",
        "insufficient_data": "warn",
        "pending": "warn",
        "approved": "ok",
        "rejected": "danger",
    }.get(kind, "neutral")
    return f'<span class="il-pill {css}">{escape(text)}</span>'


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
    sub = f"<p>{escape(subtitle)}</p>" if subtitle else ""
    st.markdown(
        f'<div class="il-page-head"><h1>{escape(title)}</h1>{sub}</div>',
        unsafe_allow_html=True,
    )


def kpi_row(items: Sequence[dict[str, Any]], *, columns: int | None = None) -> None:
    """Render a row of KPI cards. Each item: label, value, optional sub, optional accent."""
    n = columns or max(len(items), 1)
    style = f'style="grid-template-columns:repeat({n},1fr)"' if columns else ""
    cards = []
    for item in items:
        accent = " accent" if item.get("accent") else ""
        sub = (
            f'<div class="sub">{escape(str(item["sub"]))}</div>'
            if item.get("sub") is not None
            else ""
        )
        cards.append(
            f'<div class="il-kpi{accent}">'
            f'<div class="lab">{escape(str(item["label"]))}</div>'
            f'<div class="val">{escape(str(item["value"]))}</div>'
            f"{sub}</div>"
        )
    st.markdown(
        f'<div class="il-kpi-row" {style}>{"".join(cards)}</div>',
        unsafe_allow_html=True,
    )


def panel_title(title: str, hint: str | None = None) -> None:
    hint_html = f'<span class="hint">{escape(hint)}</span>' if hint else ""
    st.markdown(
        f'<h3 class="il-panel-title">{escape(title)}{hint_html}</h3>',
        unsafe_allow_html=True,
    )


def panel_open(title: str, hint: str | None = None) -> None:
    """Deprecated alias — prefer st.container(border=True) + panel_title."""
    panel_title(title, hint)


def panel_close() -> None:
    return


def info_grid(rows: Sequence[tuple[str, Any]]) -> None:
    cells = []
    for label, value in rows:
        cells.append(
            f'<div class="il-kpi" style="padding:12px 14px">'
            f'<div class="lab">{escape(str(label))}</div>'
            f'<div class="val" style="font-size:16px">{escape(str(value))}</div>'
            f"</div>"
        )
    st.markdown(
        f'<div class="il-kpi-row" style="grid-template-columns:repeat(3,1fr)">'
        f'{"".join(cells)}</div>',
        unsafe_allow_html=True,
    )
