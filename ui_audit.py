"""Shared audit-trail UI helpers — summaries first; raw JSON only when expanded."""

from __future__ import annotations

import json
from typing import Any

import streamlit as st

from services import product_service
from ui_components import panel_title


def render_audit_events(
    events: list[dict[str, Any]],
    *,
    title: str = "Audit trail",
    empty_message: str = "No audit events for the current filters.",
    show_technical_toggle: bool = True,
) -> None:
    with st.container(border=True):
        panel_title(title)
        if not events:
            st.markdown(
                f'<p class="secondary-text">{empty_message}</p>',
                unsafe_allow_html=True,
            )
            return

        show_raw = False
        if show_technical_toggle:
            show_raw = st.checkbox(
                "Show technical details",
                value=False,
                key=f"audit_tech_{title}_{len(events)}",
                help="Expands stored details_json for support / debugging.",
            )

        rows = []
        for event in events:
            rows.append(
                {
                    "When": event.get("timestamp") or "—",
                    "Event": event.get("event_label") or event.get("event_type"),
                    "Summary": event.get("summary") or "—",
                    "Actor": event.get("actor_id") or event.get("actor") or "—",
                    "Role": event.get("actor_role") or "—",
                    "Store": product_service.store_display_name(event.get("store_id")),
                    "SKU": event.get("sku") or "—",
                    "Run": event.get("run_id") or "—",
                    "Recommendation": event.get("recommendation_id") or "—",
                }
            )
        st.dataframe(rows, use_container_width=True, hide_index=True)

        if show_raw:
            with st.expander("Raw event payloads", expanded=False):
                for event in events:
                    st.markdown(
                        f"**{event.get('event_id')}** · `{event.get('event_type')}`"
                    )
                    details = event.get("details")
                    if details is None and event.get("details_json"):
                        try:
                            details = json.loads(event["details_json"])
                        except (TypeError, json.JSONDecodeError):
                            details = event.get("details_json")
                    st.json(
                        {
                            "event_id": event.get("event_id"),
                            "event_type": event.get("event_type"),
                            "timestamp": event.get("timestamp"),
                            "actor_type": event.get("actor_type"),
                            "actor_id": event.get("actor_id"),
                            "actor_role": event.get("actor_role"),
                            "run_id": event.get("run_id"),
                            "recommendation_id": event.get("recommendation_id"),
                            "approval_id": event.get("approval_id"),
                            "purchase_order_id": event.get("purchase_order_id"),
                            "correlation_id": event.get("correlation_id"),
                            "details": details or {},
                        }
                    )
