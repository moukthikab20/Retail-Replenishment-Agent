"""Administration — demo data reset for administrators only."""

from __future__ import annotations

import streamlit as st

from services import auth_service
from services.errors import user_facing_error
from ui_common import bootstrap_app
from ui_components import page_heading, panel_title


def main() -> None:
    user = bootstrap_app(
        "Administration | Retail Replenishment Agent",
        active_nav="administration",
    )
    page_heading("Administration", "Environment maintenance")

    if not auth_service.can_reset_demo(user["role"]):
        st.warning("Administration is available only to administrators.")
        return

    with st.container(border=True):
        panel_title("Demo Data")
        st.markdown(
            '<p class="secondary-text">Reset clears transactional demo records and reseeds sample data. '
            "This does not change authentication configuration.</p>",
            unsafe_allow_html=True,
        )
        if st.button("Reset Demo Data", type="primary"):
            try:
                from services.demo_data_service import reset_and_seed

                result = reset_and_seed(actor=user["user_id"], actor_role=user["role"])
                for key in (
                    "analysis_decision",
                    "recommendation_id",
                    "nav_recommendation_id",
                    "approval_id",
                    "order_flow",
                ):
                    st.session_state.pop(key, None)
                st.success("Demo data reset and reseeded.")
                with st.expander("View technical details", expanded=False):
                    st.json(
                        {
                            "deleted": result.get("reset", {}).get("deleted"),
                            "seed": result.get("seed", {}).get("status"),
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                st.error(user_facing_error(exc))


main()
