"""History — recent recommendations for the signed-in user."""

from __future__ import annotations

import streamlit as st

from services import recommendation_service
from services.errors import user_facing_error
from ui_common import bootstrap_app
from ui_components import page_heading, panel_title


def main() -> None:
    user = bootstrap_app("History | Retail Replenishment Agent", active_nav="history")
    page_heading("History", "Recent recommendations for your account")

    with st.container(border=True):
        panel_title("Recommendations")
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
                        "Store": r.get("store_id"),
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
