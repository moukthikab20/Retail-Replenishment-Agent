"""Decision Detail — business-first evidence storytelling (persisted data only)."""

from __future__ import annotations

import re
from datetime import datetime
from html import escape
from math import floor, log10
from typing import Any

import streamlit as st

from ui_components import panel_title, status_pill

# Display-only pack suffixes (e.g. "Sparkling Water 12pk" → "Sparkling Water").
_PACK_SUFFIX_RE = re.compile(r"\s+\d+\s*pk\b", re.IGNORECASE)

_SHIELD_CHECK_SVG = (
    '<svg class="il-dd-shield-svg" viewBox="0 0 24 24" width="26" height="26" '
    'aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M12 3.2 19 6.2v5.1c0 4.7-3.2 8.1-7 9.5-3.8-1.4-7-4.8-7-9.5V6.2L12 3.2z" '
    'fill="none" stroke="#1C2B3A" stroke-width="1.6" stroke-linejoin="round"/>'
    '<path d="M9.2 12.1 11 14l3.8-3.9" fill="none" stroke="#167A38" stroke-width="1.8" '
    'stroke-linecap="round" stroke-linejoin="round"/>'
    "</svg>"
)


_STAGE_WHY_UI = {
    "demand_signal": "Sets expected customer need over the planning horizon.",
    "inventory_coverage": "Checks what's available and what's coming.",
    "constraints": "Calculates the requirement and rounds to case packs.",
    "guardrail_check": "Validates against all applicable guardrails and risk controls.",
}


def _disp_kind(disposition: str | None) -> str:
    return {
        "human_review": "warn",
        "blocked": "danger",
        "auto_release": "ok",
        "no_order": "neutral",
    }.get(disposition or "", "neutral")


def _risk_kind(risk: str | None) -> str:
    return {
        "stockout": "danger",
        "overstock": "warn",
        "balanced": "ok",
        "manual_review": "warn",
        "insufficient_data": "warn",
    }.get(risk or "", "neutral")


def _store_display(store_id: str | None) -> str:
    from services import product_service

    return product_service.store_display_name(store_id)


def _fmt_decision_time(raw: Any) -> str:
    if raw is None or raw == "" or raw == "—":
        return "—"
    text = str(raw).strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return dt.strftime("%b %d, %Y %H:%M")
    except ValueError:
        return str(raw)


def _parse_order_action(action_label: str, qty: Any, case_pack: Any) -> tuple[str, str]:
    """Return (primary ORDER N UNITS line, secondary case line)."""
    label = str(action_label or "").strip()
    primary = label.upper() if label else "—"
    # Strip trailing case clause from primary for the hero right column.
    if " (" in label and label.lower().startswith("order "):
        primary = label.split(" (", 1)[0].upper()
    elif label.lower().startswith("order "):
        primary = label.upper()

    secondary = ""
    try:
        q = float(qty)
        pack = int(case_pack or 0)
    except (TypeError, ValueError):
        q, pack = None, 0
    if q is not None and pack > 1 and q > 0:
        cases = q / pack
        if abs(cases - round(cases)) < 1e-6:
            n = int(round(cases))
            secondary = f"≈ {n} CASE{'S' if n != 1 else ''} (Case pack {pack})"
        else:
            text = f"{cases:.1f}".rstrip("0").rstrip(".")
            secondary = f"≈ {text} CASES (Case pack {pack})"
    elif "≈" in label:
        # Fall back to portion after units if pack missing from fields.
        secondary = label.split("(", 1)[-1].rstrip(")").strip().upper()
        if pack > 1:
            secondary = f"{secondary} (Case pack {pack})"
    return primary, secondary


def _field_map(stage: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for label, value in stage.get("fields") or []:
        out[str(label).lower()] = str(value)
    return out


def _stage_card_body(stage: dict[str, Any], *, rec: dict[str, Any], evidence: dict[str, Any]) -> tuple[str, str]:
    key = stage.get("key")
    fields = _field_map(stage)
    if key == "demand_signal":
        forecast = fields.get("7-day forecast") or "—"
        return f"{forecast} units expected", "over next 7 days"
    if key == "inventory_coverage":
        on_hand = fields.get("on hand") or "—"
        in_transit = fields.get("in transit") or "—"
        return f"{on_hand} on hand", f"{in_transit} in transit"
    if key == "constraints":
        qty = evidence.get("hero", {}).get("recommended_quantity")
        qty = qty if qty is not None else rec.get("agent_recommended_quantity")
        try:
            q_disp = str(int(float(qty))) if qty is not None else "—"
        except (TypeError, ValueError):
            q_disp = str(qty or "—")
        pack = rec.get("case_pack") or (evidence.get("recommendation") or {}).get("case_pack")
        _, cases = _parse_order_action("", qty, pack)
        line2 = f"({cases.split(' (')[0].lower()})" if cases else ""
        return f"{q_disp}-unit requirement", line2 or "—"
    if key == "guardrail_check":
        status = stage.get("status")
        risk = (evidence.get("hero") or {}).get("risk_level") or ""
        risk_title = str(risk).replace("_", " ").title() if risk else "—"
        if status in {"pass", "ok"}:
            return "All guardrails passed", f"{risk_title} risk"
        if status == "stop":
            return "Guardrail blocked", f"{risk_title} risk"
        if status == "warn":
            return "Requires review", f"{risk_title} risk"
        return "Not evaluated", f"{risk_title} risk"
    summary = str(stage.get("outcome_summary") or "—")
    parts = summary.split("·")
    if len(parts) >= 2:
        return parts[0].strip(), parts[1].strip()
    return summary, ""


def _success_pill(text: str) -> str:
    return (
        f'<span class="il-dd-pill">{escape(text)}</span>'
    )


def _display_product_title(name: Any) -> str:
    """Visible product heading only — does not alter underlying product data."""
    text = str(name or "—").strip()
    cleaned = _PACK_SUFFIX_RE.sub("", text).strip()
    return cleaned or text


def render_decision_hero(
    hero: dict[str, Any],
    *,
    rec: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    rec = rec or {}
    disposition = hero.get("disposition")
    if disposition == "human_review":
        _render_split_summary_hero(hero, rec=rec, payload=payload or {}, mode="review")
        return
    if disposition == "auto_release":
        _render_split_summary_hero(hero, rec=rec, payload=payload or {}, mode="auto")
        return

    store = _store_display(hero.get("store_id"))
    risk_level = hero.get("risk_level")
    risk_title = str(risk_level or "—").replace("_", " ").title()
    primary, secondary = _parse_order_action(
        str(hero.get("action_label") or ""),
        hero.get("recommended_quantity") if hero.get("recommended_quantity") is not None else rec.get("agent_recommended_quantity"),
        rec.get("case_pack") or (hero.get("case_pack")),
    )
    order_value = hero.get("order_value_display") or "—"
    product_title = _display_product_title(hero.get("product_name"))
    st.markdown(
        f"""
        <div class="il-dd-summary">
          <div class="il-dd-summary-left">
            <div class="il-dd-product">{escape(product_title)}</div>
            <div class="il-dd-meta">
              <span><b>SKU</b> {escape(str(hero.get("sku") or "—"))}</span>
              <span class="dot">·</span>
              <span><b>Store</b> {escape(store)}</span>
              <span class="dot">·</span>
              <span><b>Vendor</b> {escape(str(hero.get("vendor") or "—"))}</span>
            </div>
            <div class="il-dd-status-row">
              <span>Risk: <b>{escape(str(hero.get("risk_label") or "—"))}</b></span>
              {_success_pill(risk_title) if risk_level == "balanced" else status_pill(_risk_kind(risk_level if isinstance(risk_level, str) else None), risk_title)}
              <span>Confidence: <b>{escape(str(hero.get("confidence_display") or "—"))}</b></span>
              <span>Status: {status_pill(_disp_kind(disposition if isinstance(disposition, str) else None), str(hero.get("status_label") or "—"))}
                <span class="il-dd-info" title="Status from persisted disposition">ⓘ</span>
              </span>
            </div>
            <p class="il-dd-sentence">{escape(str(hero.get("sentence") or ""))}</p>
          </div>
          <div class="il-dd-summary-right">
            <div class="il-dd-action-label">Recommended action</div>
            <div class="il-dd-action-primary">{escape(primary)}</div>
            <div class="il-dd-action-secondary">{escape(secondary)}</div>
            <div class="il-dd-value-card">
              <div class="lab">Estimated order value</div>
              <div class="val">{escape(str(order_value))}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_split_summary_hero(
    hero: dict[str, Any],
    *,
    rec: dict[str, Any],
    payload: dict[str, Any],
    mode: str,
) -> None:
    """Shared 3-column summary card — left column varies by review vs auto-release."""
    store = _store_display(hero.get("store_id"))
    primary, secondary = _parse_order_action(
        str(hero.get("action_label") or ""),
        hero.get("recommended_quantity")
        if hero.get("recommended_quantity") is not None
        else rec.get("agent_recommended_quantity"),
        rec.get("case_pack") or hero.get("case_pack"),
    )
    order_value = hero.get("order_value_display") or "—"
    product_title = _display_product_title(hero.get("product_name"))

    if mode == "auto":
        risk_level = hero.get("risk_level")
        risk_title = str(risk_level or "balanced").replace("_", " ").title()
        left_col = f"""
          <div class="il-dd-sum-col left">
            <div class="il-dd-attn-eyebrow">Handled automatically</div>
            <div class="il-dd-attn-title">Within Policy</div>
            <div class="il-dd-attn-pills">{_success_pill(risk_title)}</div>
            <div class="il-dd-attn-rule"></div>
            <div class="il-dd-attn-gap">No review required</div>
          </div>"""
        card_class = "il-dd-summary is-review is-auto"
    else:
        risk_level = hero.get("risk_level")
        risk_title = str(risk_level or "—").replace("_", " ").title()
        risk_label = str(hero.get("risk_label") or "").strip()
        high_risk_text = (
            f"{risk_label} Risk"
            if risk_label and not risk_label.lower().endswith("risk")
            else (risk_label or "High Risk")
        )
        status_label = str(hero.get("status_label") or "Needs your review")
        math = _inventory_math(payload if payload else {"hero": hero, "recommendation": rec})
        shortage = math.get("shortage")
        shortage_text = (
            f"{_as_qty_text(shortage)}-unit shortage"
            if shortage is not None
            else "Projected supply gap"
        )
        stockout_pill = status_pill(
            _risk_kind(risk_level if isinstance(risk_level, str) else None),
            risk_title,
        )
        high_risk_pill = status_pill("warn", high_risk_text)
        left_col = f"""
          <div class="il-dd-sum-col left">
            <div class="il-dd-attn-eyebrow">Attention required</div>
            <div class="il-dd-attn-title">{escape(status_label)}</div>
            <div class="il-dd-attn-pills">{stockout_pill}{high_risk_pill}</div>
            <div class="il-dd-attn-rule"></div>
            <div class="il-dd-attn-shortage">{escape(shortage_text)}</div>
            <div class="il-dd-attn-gap">Projected supply gap</div>
          </div>"""
        card_class = "il-dd-summary is-review"

    st.markdown(
        f"""
        <div class="{card_class}">
          {left_col}
          <div class="il-dd-sum-col center">
            <div class="il-dd-sum-product">{escape(product_title)}</div>
            <div class="il-dd-sum-sku">{escape(str(hero.get("sku") or "—"))}</div>
            <div class="il-dd-sum-store">Store {escape(store)}</div>
            <div class="il-dd-sum-vendor">Vendor {escape(str(hero.get("vendor") or "—"))}</div>
          </div>
          <div class="il-dd-sum-col right">
            <div class="il-dd-action-label">Recommended action</div>
            <div class="il-dd-action-primary">{escape(primary)}</div>
            <div class="il-dd-action-secondary">{escape(secondary)}</div>
            <div class="il-dd-value-card is-review">
              <div class="lab">Estimated order value</div>
              <div class="val">{escape(str(order_value))}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _policy_rule_map(governance: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for rule in governance.get("rules") or []:
        key = str(rule.get("rule_key") or "").strip()
        if key:
            out[key] = rule
    return out


def _fmt_policy_number(value: Any, *, digits: int = 1) -> str:
    if value is None or value == "":
        return "—"
    try:
        num = float(value)
        if abs(num - round(num)) < 1e-9:
            return str(int(round(num)))
        return f"{num:.{digits}f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _fmt_policy_money(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        num = float(value)
        if abs(num - round(num)) < 1e-9:
            return f"${int(round(num)):,}"
        return f"${num:,.2f}"
    except (TypeError, ValueError):
        text = str(value).strip()
        return text if text.startswith("$") else text


def _policy_detail_conditions(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """Compact auto-approval conditions from persisted hero / governance values only."""
    governance = payload.get("governance") or {}
    hero = payload.get("hero") or {}
    rules = _policy_rule_map(governance)

    conf_display = str(hero.get("confidence_display") or "").strip() or "—"

    dos_rule = rules.get("maximum_days_of_supply") or {}
    dos_obs = dos_rule.get("observed_value")
    if dos_obs is None:
        for item in payload.get("evidence_strip") or []:
            if str(item.get("label") or "").strip().lower() == "days of supply":
                dos_obs = item.get("value")
                break
    dos_thr = dos_rule.get("threshold")
    dos_value = (
        f"{_fmt_policy_number(dos_obs, digits=1)} / {_fmt_policy_number(dos_thr, digits=0)} max"
        if dos_obs is not None and dos_thr is not None
        else _fmt_policy_number(dos_obs, digits=1)
    )

    qty = hero.get("recommended_quantity")
    if qty is None:
        zero_rule = rules.get("zero_quantity") or {}
        qty = zero_rule.get("observed_value")
    qty_value = (
        f"{_fmt_policy_number(qty, digits=0)} units"
        if qty is not None and str(qty).strip() not in {"", "—"}
        else "—"
    )

    value_rule = rules.get("auto_release_max_value") or {}
    order_value = value_rule.get("observed_value")
    value_thr = value_rule.get("threshold")
    if order_value is None:
        # Fall back to display string already on the hero card.
        order_display = str(hero.get("order_value_display") or "").strip()
        left = order_display if order_display else "—"
    else:
        left = _fmt_policy_money(order_value)
    if value_thr is not None:
        value_display = f"{left} / {_fmt_policy_money(value_thr)} max"
    else:
        value_display = left

    return [
        ("Forecast confidence", conf_display),
        ("Days of supply", dos_value),
        ("Order quantity", qty_value),
        ("Auto-release value", value_display),
    ]


def render_auto_approval_policy(payload: dict[str, Any]) -> None:
    governance = payload.get("governance") or {}
    hero = payload.get("hero") or {}
    disposition = hero.get("disposition")
    policy_version = str(governance.get("policy_version") or "—").strip()
    policy_name = "Standard Replenishment Policy"

    if disposition == "auto_release":
        badge = "Within Policy"
        badge_class = "ok"
        body = (
            f'This decision was auto-approved because it met the conditions of the '
            f'“{policy_name}”.'
        )
    elif disposition == "blocked":
        badge = "Blocked"
        badge_class = "danger"
        body = str(governance.get("summary") or "This decision cannot proceed under current policy.")
    else:
        badge = "Needs review"
        badge_class = "warn"
        body = str(
            governance.get("summary")
            or "Policy requires a human decision before this order can proceed."
        )

    with st.container(key="dd_policy_card"):
        # Compact auto | 1fr | auto feel: content left, action tucked on the right.
        c1, c2 = st.columns([1.0, 0.18], gap="small")
        with c1:
            st.markdown(
                f"""
                <div class="il-dd-policy-inner">
                  <div class="il-dd-shield" aria-hidden="true">{_SHIELD_CHECK_SVG}</div>
                  <div class="il-dd-policy-copy">
                    <div class="il-dd-policy-title-row">
                      <span class="il-dd-policy-title">Auto-approval policy</span>
                      <span class="il-dd-policy-badge {badge_class}">{escape(badge)}</span>
                    </div>
                    <div class="il-dd-policy-body">{escape(body)}</div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with c2:
            # Popover overlays — does not expand the page and shift Business Evidence.
            with st.popover("View policy details"):
                _render_policy_popover_body(payload)


def render_evidence_strip(items: list[dict[str, Any]]) -> None:
    st.markdown('<h3 class="il-dd-section-title">Business evidence</h3>', unsafe_allow_html=True)
    cells = []
    for item in items:
        label = str(item.get("label") or "")
        if label.lower() == "order value":
            continue
        value = str(item.get("value") or "—")
        sub = ""
        if label.lower() == "demand forecast":
            sub = '<div class="sub">(7-day)</div>'
        cells.append(
            "<div class='il-dd-evidence-tile'>"
            f"<div class='lab'>{escape(label)}</div>"
            f"<div class='val'>{escape(value)}</div>"
            f"{sub}"
            "</div>"
        )
    st.markdown(
        f'<div class="il-dd-evidence-strip">{"".join(cells)}</div>',
        unsafe_allow_html=True,
    )


def _as_float(value: Any) -> float | None:
    if value is None or value == "" or value == "—":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        text = str(value).replace(",", "").replace("$", "").strip()
        try:
            return float(text)
        except (TypeError, ValueError):
            return None


def _as_qty_text(value: Any) -> str:
    num = _as_float(value)
    if num is None:
        return "—" if value in (None, "", "—") else str(value)
    if abs(num - round(num)) < 1e-9:
        return str(int(round(num)))
    return f"{num:.1f}".rstrip("0").rstrip(".")


def _fmt_axis_date(raw: Any) -> str:
    text = str(raw or "")[:10]
    parts = text.split("-")
    if len(parts) == 3 and all(parts):
        try:
            return f"{int(parts[1])}/{int(parts[2])}"
        except ValueError:
            pass
    return text or "—"


def _nice_axis_step(span: float, target_ticks: int = 4) -> float:
    if span <= 0:
        return 1.0
    rough = span / max(target_ticks - 1, 1)
    exp = floor(log10(rough))
    base = 10 ** exp
    fraction = rough / base
    if fraction <= 1:
        nice = 1
    elif fraction <= 2:
        nice = 2
    elif fraction <= 5:
        nice = 5
    else:
        nice = 10
    return nice * base


def _y_axis_ticks(values: list[float]) -> tuple[float, float, list[float]]:
    y_min = min(values)
    y_max = max(values)
    lo = 0.0 if y_min >= 0 else y_min
    hi = y_max if y_max > lo else lo + 1.0
    pad = max((hi - lo) * 0.08, 0.5)
    hi = hi + pad
    step = _nice_axis_step(hi - lo, target_ticks=4)
    start = 0.0 if lo >= 0 else floor(lo / step) * step
    ticks: list[float] = []
    t = start
    # Guard against float drift; keep chart compact with ~3–5 ticks.
    for _ in range(8):
        ticks.append(t)
        if t >= hi - step * 1e-9:
            break
        t = round(t + step, 10)
    if ticks[-1] < hi - step * 0.25:
        ticks.append(round(ticks[-1] + step, 10))
    return ticks[0], ticks[-1], ticks


def _demand_trend_svg(points: list[dict[str, Any]]) -> str:
    """Compact readable line chart from persisted sales points (no invented series)."""
    if len(points) < 2:
        return (
            '<div class="il-dd-trend-empty">'
            "Not enough recent sales history to chart."
            "</div>"
        )
    series = points[-7:]
    width, height = 420, 148
    pad_l, pad_r, pad_t, pad_b = 36, 10, 10, 28
    ys = [float(p.get("units_sold") or 0) for p in series]
    dates = [_fmt_axis_date(p.get("date")) for p in series]
    y_lo, y_hi, y_ticks = _y_axis_ticks(ys)
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    y_span = max(y_hi - y_lo, 1e-9)

    def _x(i: int) -> float:
        return pad_l + (i / max(len(series) - 1, 1)) * plot_w

    def _y(v: float) -> float:
        return pad_t + (1 - (v - y_lo) / y_span) * plot_h

    grid = "".join(
        f'<line x1="{pad_l}" y1="{_y(tick):.1f}" x2="{width - pad_r}" y2="{_y(tick):.1f}" '
        f'stroke="#E5E9EF" stroke-width="1" />'
        for tick in y_ticks
    )
    y_labels = "".join(
        f'<text x="{pad_l - 6}" y="{_y(tick) + 3.5:.1f}" text-anchor="end" '
        f'class="il-dd-trend-axis">{escape(_as_qty_text(tick))}</text>'
        for tick in y_ticks
    )
    x_labels = "".join(
        f'<text x="{_x(i):.1f}" y="{height - 6}" text-anchor="middle" '
        f'class="il-dd-trend-axis">{escape(label)}</text>'
        for i, label in enumerate(dates)
    )
    # Light bottom axis line
    axis = (
        f'<line x1="{pad_l}" y1="{pad_t + plot_h:.1f}" x2="{width - pad_r}" '
        f'y2="{pad_t + plot_h:.1f}" stroke="#DCE3EA" stroke-width="1" />'
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h:.1f}" '
        f'stroke="#DCE3EA" stroke-width="1" />'
    )
    coords = " ".join(f"{_x(i):.1f},{_y(v):.1f}" for i, v in enumerate(ys))
    point_groups: list[str] = []
    for i, v in enumerate(ys):
        cx = _x(i)
        cy = _y(v)
        date_label = dates[i]
        qty = _as_qty_text(v)
        sales_line = f"Sales: {qty} units"
        tip_w = max(len(date_label), len(sales_line)) * 7.2 + 18
        tip_h = 44.0
        tip_x = max(2.0, min(cx - tip_w / 2, width - tip_w - 2))
        tip_y = cy - tip_h - 8
        if tip_y < 2:
            tip_y = min(cy + 10, height - tip_h - 2)
        tip_cx = tip_x + tip_w / 2
        point_groups.append(
            f'<g class="il-dd-trend-point">'
            f'<circle class="il-dd-trend-dot" cx="{cx:.1f}" cy="{cy:.1f}" r="3.2" '
            f'fill="#1d4ed8" stroke="#fff" stroke-width="1" />'
            f'<circle class="il-dd-trend-hit" cx="{cx:.1f}" cy="{cy:.1f}" r="9" '
            f'fill="transparent" />'
            f'<g class="il-dd-trend-tip" pointer-events="none">'
            f'<rect class="il-dd-trend-tip-bg" x="{tip_x:.1f}" y="{tip_y:.1f}" '
            f'width="{tip_w:.1f}" height="{tip_h:.1f}" rx="6" ry="6" />'
            f'<text class="il-dd-trend-tip-text" x="{tip_cx:.1f}" y="{tip_y + 16:.1f}" '
            f'text-anchor="middle">{escape(date_label)}</text>'
            f'<text class="il-dd-trend-tip-text" x="{tip_cx:.1f}" y="{tip_y + 32:.1f}" '
            f'text-anchor="middle">{escape(sales_line)}</text>'
            f"</g></g>"
        )
    return (
        f'<svg class="il-dd-trend" viewBox="0 0 {width} {height}" '
        f'width="100%" height="{height}" aria-hidden="true" focusable="false">'
        f"{grid}{axis}{y_labels}{x_labels}"
        f'<polyline fill="none" stroke="#1d4ed8" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{coords}" />'
        f"{''.join(point_groups)}"
        "</svg>"
    )


def _sales_points_for_decision(payload: dict[str, Any]) -> list[dict[str, Any]]:
    hero = payload.get("hero") or {}
    header = payload.get("header") or {}
    store_id = hero.get("store_id") or header.get("store_id")
    sku = hero.get("sku") or header.get("sku")
    if not store_id or not sku:
        return []
    try:
        from services import overview_dashboard_service

        series = overview_dashboard_service.get_item_sales_series(
            str(store_id), str(sku), days=14
        )
    except Exception:  # noqa: BLE001
        return []
    if not series.get("ok"):
        return list(series.get("points") or [])
    return list(series.get("points") or [])


def _inventory_math(payload: dict[str, Any]) -> dict[str, Any]:
    stages = {s.get("key"): s for s in (payload.get("stages") or [])}
    demand = _field_map(stages.get("demand_signal") or {})
    inv = _field_map(stages.get("inventory_coverage") or {})
    hero = payload.get("hero") or {}
    rec = payload.get("recommendation") or {}
    quantities = payload.get("quantities") or {}

    forecast = _as_float(demand.get("7-day forecast"))
    if forecast is None:
        forecast = _as_float(quantities.get("forecast_units"))
    safety = _as_float(inv.get("safety stock"))
    if safety is None:
        safety = _as_float(rec.get("safety_stock"))
    on_hand = _as_float(inv.get("on hand"))
    if on_hand is None:
        on_hand = _as_float((payload.get("recommendation") or {}).get("usable_on_hand"))
    in_transit = _as_float(inv.get("in transit"))
    if in_transit is None:
        in_transit = _as_float(rec.get("in_transit"))

    required = None if forecast is None or safety is None else forecast + safety
    available = None if on_hand is None or in_transit is None else on_hand + in_transit
    shortage = None
    if required is not None and available is not None:
        shortage = max(0.0, required - available)

    qty = hero.get("recommended_quantity")
    if qty is None:
        qty = quantities.get("agent_recommended_quantity")
    if qty is None:
        qty = rec.get("agent_recommended_quantity")
    pack = rec.get("case_pack")
    cases = None
    qf = _as_float(qty)
    pf = _as_float(pack)
    if qf is not None and pf and pf > 1:
        cases = qf / pf

    return {
        "forecast": forecast,
        "safety": safety,
        "on_hand": on_hand,
        "in_transit": in_transit,
        "required": required,
        "available": available,
        "shortage": shortage,
        "recommended": qf,
        "case_pack": pf,
        "cases": cases,
        "dos": _as_float(inv.get("days of supply")) or _as_float(rec.get("days_of_supply")),
        "projected_stockout": inv.get("projected stockout") or "—",
    }


def _policy_outcome_label(disposition: str | None) -> tuple[str, str]:
    return {
        "auto_release": ("Within Policy", "ok"),
        "human_review": ("Requires Review", "warn"),
        "blocked": ("Blocked", "danger"),
        "no_order": ("No order", "ok"),
    }.get(disposition or "", ("—", ""))


def _risk_tone(risk_level: str | None, risk_label: str | None) -> str:
    level = str(risk_level or "").lower()
    label = str(risk_label or "").lower()
    if level in {"stockout"} or label in {"high"}:
        return "warn"
    if level in {"balanced"} or label in {"low"}:
        return "ok"
    if level in {"overstock", "manual_review", "insufficient_data"} or label in {"medium"}:
        return "warn"
    return ""


def _render_policy_popover_body(payload: dict[str, Any]) -> None:
    governance = payload.get("governance") or {}
    hero = payload.get("hero") or {}
    disposition = hero.get("disposition")
    policy_version = str(governance.get("policy_version") or "—").strip()
    policy_name = "Standard Replenishment Policy"
    version_label = (
        policy_version
        if policy_version.lower().startswith("v") or policy_version == "—"
        else f"v{policy_version}"
    )
    conditions = _policy_detail_conditions(payload)
    condition_rows = "".join(
        f'<div class="il-dd-policy-cond-row">'
        f'<span class="lab">{escape(label)}</span>'
        f'<span class="val">{escape(value)}</span>'
        f"</div>"
        for label, value in conditions
    )
    if disposition == "auto_release":
        footer = (
            '<div class="il-dd-policy-cond-footer">'
            '<div class="title">Eligible for automatic approval</div>'
            '<div class="sub">All required conditions were satisfied.</div>'
            "</div>"
        )
    else:
        footer = (
            f'<div class="il-dd-policy-cond-footer">'
            f'<div class="sub">{escape(str(governance.get("summary") or ""))}</div>'
            f"</div>"
        )
    st.markdown(
        f"""
        <div class="il-dd-policy-popover">
          <div class="il-dd-policy-popover-head">
            {escape(policy_name)} · {escape(version_label)}
          </div>
          <div class="il-dd-policy-cond-list">
            {condition_rows}
          </div>
          {footer}
        </div>
        """,
        unsafe_allow_html=True,
    )


def _audit_fields(stage: dict[str, Any], *, exclude: set[str]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for label, value in stage.get("fields") or []:
        key = str(label).strip().lower()
        if key in exclude:
            continue
        rows.append((str(label), str(value)))
    return rows


def render_agent_journey(payload: dict[str, Any]) -> None:
    """Decision Rationale — graphical meaning layer (not a second KPI strip)."""
    stages = {s.get("key"): s for s in (payload.get("stages") or [])}
    hero = payload.get("hero") or {}
    rec = payload.get("recommendation") or {}
    demand = stages.get("demand_signal") or {}
    inventory = stages.get("inventory_coverage") or {}
    constraints = stages.get("constraints") or {}
    guardrails = stages.get("guardrail_check") or {}
    demand_fields = _field_map(demand)
    math = _inventory_math(payload)
    rid = payload.get("recommendation_id") or rec.get("recommendation_id") or "x"

    st.markdown('<h3 class="il-dd-section-title">Decision Rationale</h3>', unsafe_allow_html=True)
    st.markdown('<div class="il-dd-rationale">', unsafe_allow_html=True)

    # —— 1 Demand ——
    trend_points = _sales_points_for_decision(payload)
    demand_support = [
        ("Historical period", demand_fields.get("historical demand period") or "—"),
        (
            "Forecast confidence",
            hero.get("confidence_display")
            or demand_fields.get("forecast confidence")
            or "—",
        ),
        (
            "Avg. daily sales",
            f"{demand_fields.get('average daily sales') or '—'} units"
            if demand_fields.get("average daily sales") not in (None, "", "—")
            else "—",
        ),
        ("Model / version", demand_fields.get("model / version") or "—"),
    ]
    demand_conclusion = (
        "Demand indicates replenishment is needed."
        if (math.get("recommended") or 0) > 0
        else "Demand was assessed for this planning horizon."
    )
    support_html = "".join(
        f'<div class="il-dd-support-item"><div class="lab">{escape(lab)}</div>'
        f'<div class="val">{escape(val)}</div></div>'
        for lab, val in demand_support
    )
    demand_open = bool(st.session_state.get(f"dd_stage_open_{rid}_demand_signal"))
    st.markdown(
        f"""
        <div class="il-dd-rat-row il-dd-rat-row-demand is-first">
          <div class="il-dd-rat-left">
            <div class="il-dd-step-num">1</div>
            <div>
              <div class="il-dd-rat-title">Demand</div>
              <p class="il-dd-rat-conclusion">{escape(demand_conclusion)}</p>
            </div>
          </div>
          <div class="il-dd-rat-center">
            <div class="il-dd-rat-panel-lab">7-DAY DEMAND TREND</div>
            {_demand_trend_svg(trend_points)}
          </div>
          <div class="il-dd-rat-right il-dd-rat-sep">
            <div class="il-dd-support-grid">{support_html}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("▾" if demand_open else "›", key=f"dd_row_toggle_{rid}_demand_signal"):
        st.session_state[f"dd_stage_open_{rid}_demand_signal"] = not demand_open
        st.rerun()
    if demand_open:
        audit = _audit_fields(
            demand,
            exclude={
                "7-day forecast",
                "historical demand period",
                "average daily sales",
                "forecast confidence",
                "model / version",
            },
        )
        if audit:
            rows = "".join(
                "<div class='il-evidence-row'>"
                f"<span class='lab'>{escape(lab)}</span>"
                f"<span class='val'>{escape(val)}</span>"
                "</div>"
                for lab, val in audit
            )
            st.markdown(
                f'<div class="il-dd-rat-expand"><div class="il-evidence-grid">{rows}</div></div>',
                unsafe_allow_html=True,
            )

    # —— 2 Inventory ——
    available = math.get("available")
    required = math.get("required")
    fill_pct = 0.0
    if available is not None and required is not None and required > 0:
        fill_pct = max(0.0, min(100.0, (available / required) * 100.0))
    midpoint = None if required is None else required / 2.0
    inv_conclusion = (
        "Available inventory is insufficient to cover projected need."
        if available is not None and required is not None and available < required
        else "Inventory coverage was assessed against projected need."
    )
    stockout = str(math.get("projected_stockout") or "—")
    show_stockout = stockout not in {"—", "", "None", "Not projected"} or (
        str(hero.get("risk_level") or "") == "stockout"
        and math.get("dos") is not None
    )
    stockout_html = (
        f"""
        <div class="il-dd-stockout-card">
          <div class="icon" aria-hidden="true">⚠</div>
          <div>
            <div class="title">Projected stockout</div>
            <div class="sub">{escape(stockout if "day" in stockout.lower() else f"~{_as_qty_text(math.get('dos'))} days of supply")}</div>
          </div>
        </div>
        """
        if show_stockout
        else ""
    )
    inv_open = bool(st.session_state.get(f"dd_stage_open_{rid}_inventory_coverage"))
    st.markdown(
        f"""
        <div class="il-dd-rat-row il-dd-rat-row-inventory">
          <div class="il-dd-rat-left">
            <div class="il-dd-step-num">2</div>
            <div>
              <div class="il-dd-rat-title">Inventory</div>
              <p class="il-dd-rat-conclusion">{escape(inv_conclusion)}</p>
            </div>
          </div>
          <div class="il-dd-rat-center">
            <div class="il-dd-rat-panel-lab">INVENTORY VS. REQUIRED</div>
            <div class="il-dd-inv-compare">
              <div class="il-dd-inv-side avail">
                <div class="qty">{escape(_as_qty_text(available))}</div>
                <div class="lab">Available</div>
                <div class="hint">(On hand + In transit)</div>
              </div>
              <div class="il-dd-inv-scale">
                <div class="il-dd-inv-track">
                  <div class="il-dd-inv-fill" style="width:{fill_pct:.1f}%"></div>
                  <div class="il-dd-inv-marker" style="left:{fill_pct:.1f}%"></div>
                </div>
                <div class="il-dd-inv-ticks">
                  <span class="tick start" style="left:0%"><i></i><b>0</b></span>
                  <span class="tick mid" style="left:50%"><i></i><b>{escape(_as_qty_text(midpoint))}</b></span>
                  <span class="tick end" style="left:100%"><i></i><b>{escape(_as_qty_text(required))}</b></span>
                </div>
              </div>
              <div class="il-dd-inv-side req">
                <div class="qty">{escape(_as_qty_text(required))}</div>
                <div class="lab">Required</div>
                <div class="hint">(7-day forecast + safety stock)</div>
              </div>
            </div>
          </div>
          <div class="il-dd-rat-right il-dd-rat-sep">{stockout_html}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.button("▾" if inv_open else "›", key=f"dd_row_toggle_{rid}_inventory_coverage"):
        st.session_state[f"dd_stage_open_{rid}_inventory_coverage"] = not inv_open
        st.rerun()
    if inv_open:
        audit = _audit_fields(
            inventory,
            exclude={
                "on hand",
                "in transit",
                "safety stock",
                "days of supply",
                "projected stockout",
            },
        )
        if audit:
            rows = "".join(
                "<div class='il-evidence-row'>"
                f"<span class='lab'>{escape(lab)}</span>"
                f"<span class='val'>{escape(val)}</span>"
                "</div>"
                for lab, val in audit
            )
            st.markdown(
                f'<div class="il-dd-rat-expand"><div class="il-evidence-grid">{rows}</div></div>',
                unsafe_allow_html=True,
            )

    # —— 3 Replenishment Calculation ——
    f_s = _as_qty_text(math.get("forecast"))
    s_s = _as_qty_text(math.get("safety"))
    oh_s = _as_qty_text(math.get("on_hand"))
    it_s = _as_qty_text(math.get("in_transit"))
    req_s = _as_qty_text(math.get("required"))
    avail_s = _as_qty_text(math.get("available"))
    short_s = _as_qty_text(math.get("shortage"))
    rec_s = _as_qty_text(math.get("recommended"))
    cases_s = _as_qty_text(math.get("cases"))
    pack_s = _as_qty_text(math.get("case_pack"))
    calc_conclusion = (
        "Recommended quantity derived from demand, supply and safety stock."
        if constraints.get("status") != "not_evaluated"
        else "Replenishment calculation was not evaluated."
    )
    st.markdown(
        f"""
        <div class="il-dd-rat-row il-dd-rat-row-calc">
          <div class="il-dd-rat-left">
            <div class="il-dd-step-num">3</div>
            <div>
              <div class="il-dd-rat-title">Replenishment Calculation</div>
              <p class="il-dd-rat-conclusion">{escape(calc_conclusion)}</p>
            </div>
          </div>
          <div class="il-dd-rat-center">
            <div class="il-dd-calc-flow">
              <div class="il-dd-calc-block">
                <div class="lab">Total required</div>
                <div class="val">{escape(req_s)}</div>
                <div class="hint">({escape(f_s)} + {escape(s_s)})</div>
              </div>
              <div class="il-dd-calc-op">−</div>
              <div class="il-dd-calc-block">
                <div class="lab">Total available</div>
                <div class="val">{escape(avail_s)}</div>
                <div class="hint">({escape(oh_s)} + {escape(it_s)})</div>
              </div>
              <div class="il-dd-calc-op">=</div>
              <div class="il-dd-calc-block shortage">
                <div class="lab">Shortage</div>
                <div class="val">{escape(short_s)}</div>
                <div class="hint">(Gap)</div>
              </div>
              <div class="il-dd-calc-op">→</div>
              <div class="il-dd-calc-block recommended">
                <div class="lab">Recommended order quantity</div>
                <div class="val">{escape(rec_s)} units</div>
              </div>
              <div class="il-dd-calc-op">→</div>
              <div class="il-dd-calc-block cases">
                <div class="lab">Rounded to case pack</div>
                <div class="val">{escape(cases_s)} cases</div>
                <div class="hint">Case pack {escape(pack_s)}</div>
              </div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # —— 4 Policy & Risk ——
    status = guardrails.get("status")
    guard_label = (
        "All passed"
        if status in {"pass", "ok"}
        else ("Not evaluated" if status == "not_evaluated" else "Needs attention")
    )
    guard_tone = "ok" if status in {"pass", "ok"} else ("warn" if status not in {None, "not_evaluated"} else "")
    risk_label = str(hero.get("risk_label") or str(hero.get("risk_level") or "—").replace("_", " ").title())
    risk_tone = _risk_tone(hero.get("risk_level") if isinstance(hero.get("risk_level"), str) else None, risk_label)
    outcome_label, outcome_tone = _policy_outcome_label(
        hero.get("disposition") if isinstance(hero.get("disposition"), str) else None
    )
    conf = str(hero.get("confidence_display") or "—")
    st.markdown(
        f"""
        <div class="il-dd-rat-row il-dd-rat-row-policy">
          <div class="il-dd-rat-left">
            <div class="il-dd-step-num">4</div>
            <div>
              <div class="il-dd-rat-title">Policy &amp; Risk</div>
              <p class="il-dd-rat-conclusion">Assessed against all applicable policies and risk controls.</p>
            </div>
          </div>
          <div class="il-dd-rat-center">
            <div class="il-dd-policy-metrics">
              <div class="il-dd-policy-metric">
                <div class="lab">Guardrails</div>
                <div class="val {guard_tone}">{escape(guard_label)}</div>
              </div>
              <div class="il-dd-policy-metric">
                <div class="lab">Risk level</div>
                <div class="val {risk_tone}">{escape(risk_label)}</div>
              </div>
              <div class="il-dd-policy-metric">
                <div class="lab">Confidence</div>
                <div class="val">{escape(conf)}</div>
              </div>
              <div class="il-dd-policy-metric">
                <div class="lab">Policy outcome</div>
                <div class="val {outcome_tone}">{escape(outcome_label)}</div>
              </div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("</div>", unsafe_allow_html=True)  # il-dd-rationale


def render_decision_committed(payload: dict[str, Any]) -> None:
    hero = payload.get("hero") or {}
    header = payload.get("header") or {}
    run = payload.get("run") or {}
    disposition = hero.get("disposition")
    if disposition != "auto_release":
        return

    when = _fmt_decision_time(
        run.get("completed_at")
        or header.get("decision_cutoff")
        or header.get("run_timestamp")
    )
    st.markdown(
        f"""
        <div class="il-dd-committed">
          <div class="il-dd-committed-left">
            <div class="il-dd-committed-check" aria-hidden="true">✓</div>
            <div>
              <div class="il-dd-committed-title">Decision committed</div>
              <div class="il-dd-committed-sub">This decision was handled automatically by the agent.</div>
            </div>
          </div>
          <div class="il-dd-committed-mid">
            <div class="lab">Decision time</div>
            <div class="val">{escape(when)}</div>
          </div>
          <div class="il-dd-committed-right">
            <div class="lab">Release source</div>
            <div class="val">Agent — Within Policy</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_decision_detail(payload: dict[str, Any]) -> None:
    """Full Decision Detail story from evidence_service payload."""
    hero = payload.get("hero") or {}
    rec = payload.get("recommendation") or {}
    render_decision_hero(hero, rec=rec, payload=payload)
    render_auto_approval_policy(payload)
    render_evidence_strip(payload.get("evidence_strip") or [])
    render_agent_journey(payload)
    render_decision_committed(payload)


# —— Backward-compatible wrappers (tests / older callers) ——


def render_decision_header(header: dict[str, Any]) -> None:
    st.markdown(
        f"""
        <div class="il-decision-header">
          <div class="il-decision-product">{escape(str(header.get('product_name')))}</div>
          <div class="il-decision-meta">
            <span><b>SKU</b> {escape(str(header.get('sku')))}</span>
            <span><b>Store</b> {escape(_store_display(header.get('store_id')))}</span>
            <span><b>Vendor</b> {escape(str(header.get('vendor')))}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_decision_card(card: dict[str, Any]) -> None:
    with st.container(border=True):
        panel_title("Decision record")
        st.caption(
            f"Recommended order {card.get('recommended_order')} · "
            f"Value {card.get('order_value_display')} · "
            f"Confidence {card.get('confidence_display')}"
        )


def render_evidence_stages(payload: dict[str, Any]) -> None:
    render_agent_journey(payload)


def render_policy_governance(governance: dict[str, Any]) -> None:
    """Kept for callers; Decision Detail embeds policy in the auto-approval card."""
    with st.container(border=True):
        st.markdown(f"**{escape(str(governance.get('summary') or '—'))}**")


def render_agent_intelligence(intelligence: dict[str, Any]) -> None:
    return


def render_alternatives(alternatives: list[dict[str, Any]], *, recommended_label: str) -> None:
    return


def render_what_happens_next(text: str) -> None:
    return


def render_secondary_explanation(explanation: dict[str, Any]) -> None:
    text = (explanation or {}).get("text") or ""
    if not text.strip():
        return
    with st.expander("Persisted rationale (secondary)", expanded=False):
        st.markdown(f'<p class="agent-explanation">{escape(text)}</p>', unsafe_allow_html=True)
