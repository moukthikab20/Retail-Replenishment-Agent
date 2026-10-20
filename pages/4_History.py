"""History — unified business audit trail with filters."""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from services import audit_service, product_service, recommendation_service
from services.errors import user_facing_error
from ui_audit import render_audit_events
from ui_common import bootstrap_app
from ui_components import page_heading, panel_title


def main() -> None:
    user = bootstrap_app("History | Retail Replenishment Agent", active_nav="history")
    page_heading("History", "Business audit trail — append-only events")

    with st.container(border=True):
        panel_title("Filters")
        today = date.today()
        c1, c2, c3 = st.columns(3)
        with c1:
            date_from = st.date_input("From date", value=today - timedelta(days=14))
            date_to = st.date_input("To date", value=today)
        with c2:
            store_rows = product_service.list_stores()
            stores = ["(any)"] + [s["store_name"] for s in store_rows]
            store_pick = st.selectbox("Store", options=stores)
            sku_text = st.text_input("SKU", value="", placeholder="Exact SKU or leave blank")
        with c3:
            run_id = st.text_input("Run ID", value="", placeholder="e.g. RUN-…")
            event_options = ["(any)"] + list(audit_service.BUSINESS_EVENT_TYPES)
            event_pick = st.selectbox("Event", options=event_options)
            actor = st.text_input("Actor", value="", placeholder="user id / system / agent")

        apply = st.button("Apply filters", type="primary")

    store_id = (
        None
        if store_pick == "(any)"
        else product_service.store_id_for_display_name(store_pick)
    )
    event_type = None if event_pick == "(any)" else event_pick
    sku = sku_text.strip() or None
    run = run_id.strip() or None
    actor_filter = actor.strip() or None

    # Default load on first open; re-query when Apply is pressed or filters change via session.
    if "history_filters_ready" not in st.session_state or apply:
        st.session_state["history_filters_ready"] = True

    try:
        events = audit_service.list_business_events(
            date_from=date_from,
            date_to=date_to,
            store_id=store_id,
            sku=sku,
            run_id=run,
            event_type=event_type,
            actor=actor_filter,
            business_only=True,
            include_raw_details=True,
            limit=250,
        )
    except Exception as exc:  # noqa: BLE001
        st.error(user_facing_error(exc))
        return

    render_audit_events(
        events,
        title="Audit events",
        empty_message="No business audit events match these filters.",
    )

    with st.container(border=True):
        panel_title("Recent recommendations")
        try:
            rows = recommendation_service.list_recommendations_for_user(
                user["user_id"], limit=20
            )
        except Exception as exc:  # noqa: BLE001
            st.error(user_facing_error(exc))
            return

        if not rows:
            st.markdown(
                '<p class="secondary-text">No recommendations yet.</p>',
                unsafe_allow_html=True,
            )
        else:
            st.dataframe(
                [
                    {
                        "Recommendation ID": r.get("recommendation_id"),
                        "Store": product_service.store_display_name(r.get("store_id")),
                        "SKU": r.get("sku"),
                        "Agent Qty": r.get("agent_recommended_quantity"),
                        "Status": r.get("status"),
                    }
                    for r in rows
                ],
                use_container_width=True,
                hide_index=True,
            )
            selected = st.selectbox(
                "Open recommendation",
                options=[r.get("recommendation_id") for r in rows],
            )
            if st.button("Open in Review", type="primary", disabled=not selected):
                st.session_state["nav_recommendation_id"] = selected
                st.session_state["recommendation_id"] = selected
                st.switch_page("pages/2_Review.py")


main()
