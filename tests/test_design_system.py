"""UI Step 6 — design system tokens, empty state, status semantics."""

from __future__ import annotations

import re
from pathlib import Path

from styles import inject_styles
from ui_components import (
    AGENT_LANGUAGE,
    STATUS_KINDS,
    empty_state,
    status_pill,
)


STYLES = Path(__file__).resolve().parents[1] / "styles.py"
UI_COMPONENTS = Path(__file__).resolve().parents[1] / "ui_components.py"


def test_typography_and_spacing_tokens_present():
    css = inject_styles()
    for token in (
        "--type-page: 28px",
        "--type-section: 20px",
        "--type-body: 15px",
        "--type-caption: 12px",
        "--type-kpi: 28px",
        "--type-kpi-label: 12px",
        "--space-1:",
        "--space-2:",
        "--space-3:",
        "--row-h:",
        "--weight-page: 600",
    ):
        assert token in css


def test_no_business_helper_text_below_12px():
    """Business content helpers must be >= 12px (dense topbar brand chrome excepted)."""
    css = inject_styles()
    # Strip fixed topbar brand chrome where density is intentional.
    business = re.sub(r"\.il-wm small\s*\{[\s\S]*?\}", "", business := css, count=1)
    business = re.sub(
        r"\.il-status-pill\s*\{[\s\S]*?\}",
        "",
        business,
        count=1,
    )
    tiny = re.findall(r"font-size:\s*(9|10|10\.5|11)px", business)
    assert tiny == [], f"Business CSS still uses sub-12px sizes: {tiny}"


def test_status_system_semantics():
    for kind in (
        "neutral",
        "success",
        "attention",
        "warning",
        "critical",
        "progress",
    ):
        assert kind in STATUS_KINDS.values() or kind in STATUS_KINDS
    html = status_pill("critical", "Send Failed")
    assert 'role="status"' in html
    assert "Send Failed" in html
    assert "critical" in html
    assert status_pill("ok", "Accepted").count("success") >= 1
    assert status_pill("warn", "Ready").count("attention") >= 1
    assert status_pill("progress", "Sending").count("progress") >= 1


def test_agent_language_standardized():
    required = {
        "Agent analyzed",
        "Agent recommends",
        "Handled automatically",
        "Needs your review",
        "Cannot proceed",
        "No order needed",
        "Ready to send",
        "Accepted",
        "Retry scheduled",
    }
    assert required == set(AGENT_LANGUAGE.values())


def test_empty_state_component_api():
    assert "def empty_state" in UI_COMPONENTS.read_text(encoding="utf-8")
    assert "il-empty" in inject_styles()
    assert "il-empty-title" in inject_styles()
    # Callable import smoke — Streamlit not required until render
    assert callable(empty_state)


def test_business_pages_use_empty_state():
    """Queue/Orders keep empty_state; Overview is a decision dashboard."""
    root = Path(__file__).resolve().parents[1]
    for rel in ("ui_queue.py", "ui_orders.py"):
        src = (root / rel).read_text(encoding="utf-8")
        assert "empty_state" in src, f"{rel} should use empty_state"
    overview = (root / "ui_overview.py").read_text(encoding="utf-8")
    assert "overview_dashboard_service" in overview
    styles = (root / "styles.py").read_text(encoding="utf-8")
    assert "il-overview-greeting" in styles
    assert "il-dash-tiles" in styles


def test_kpi_row_is_compact_strip():
    """Metrics use compact KPI strips, not a separate giant-card path."""
    src = UI_COMPONENTS.read_text(encoding="utf-8")
    assert "def kpi_row" in src
    assert "compact_kpi_row(items" in src
