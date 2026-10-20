"""Policy & Guardrails — read-only for business users; versioned edit for admins."""

from __future__ import annotations

from decimal import Decimal
from html import escape

import streamlit as st

from services import auth_service, policy_service
from services.errors import user_facing_error
from ui_common import bootstrap_app
from ui_components import page_heading, panel_title, status_pill


def _render_rules_table(rules: list[dict[str, str]]) -> None:
    header = (
        "<div class='il-queue-table il-policy-table'>"
        "<div class='il-queue-head'>"
        "<div>Business Name</div><div>Explanation</div>"
        "<div>Configured Value</div><div>Internal Key</div>"
        "</div>"
    )
    parts = [header]
    for row in rules:
        parts.append(
            "<div class='il-queue-row'>"
            f"<div><strong>{escape(str(row['business_name']))}</strong></div>"
            f"<div class='il-policy-explain'>{escape(str(row['explanation']))}</div>"
            f"<div>{escape(str(row['configured_value']))}</div>"
            f"<div><code>{escape(str(row['internal_key']))}</code></div>"
            "</div>"
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def main() -> None:
    user = bootstrap_app(
        "Policy & Guardrails | Retail Replenishment Agent",
        active_nav="policy",
    )
    page_heading(
        "Policy & Guardrails",
        "The rules that decide auto-release, review, blocked, and no-order outcomes.",
    )

    view = policy_service.get_policy_guardrails_view()
    policy = view["policy"]
    can_edit = auth_service.can_edit_policy(user["role"])

    with st.container(border=True):
        panel_title(
            "Active policy",
            hint=f"Version {view['policy_version']}",
        )
        st.markdown(
            status_pill("ok" if view.get("active") else "neutral", "Active"),
            unsafe_allow_html=True,
        )
        st.caption(
            f"Policy ID {view['policy_id']} · created by {view.get('created_by') or '—'} · "
            f"effective from {view.get('effective_from') or '—'} · "
            "Historical recommendations keep the policy version they were evaluated under."
        )
        _render_rules_table(view["rules"])

    if can_edit:
        with st.container(border=True):
            panel_title(
                "Publish new policy version",
                hint="Administrator only — never rewrites prior versions",
            )
            st.caption(
                "Saving creates a new version, closes the current one, records you as "
                "the actor, and writes an audit event. Past decisions are not changed."
            )
            with st.form("policy_publish_form"):
                c1, c2 = st.columns(2)
                with c1:
                    auto_ceiling = st.number_input(
                        "Auto-release ceiling ($)",
                        min_value=0.0,
                        value=float(policy["auto_release_max_value"]),
                        step=50.0,
                    )
                    min_conf = st.number_input(
                        "Minimum confidence",
                        min_value=0.0,
                        max_value=1.0,
                        value=float(policy["minimum_confidence"]),
                        step=0.01,
                        format="%.2f",
                    )
                    max_age = st.number_input(
                        "Maximum inventory-feed age (hours)",
                        min_value=1,
                        value=int(policy["maximum_inventory_age_hours"]),
                        step=1,
                    )
                    max_dos = st.number_input(
                        "Maximum days of supply",
                        min_value=0.0,
                        value=float(policy["maximum_days_of_supply"]),
                        step=0.5,
                    )
                    min_history = st.number_input(
                        "Minimum historical demand (days)",
                        min_value=0,
                        value=int(policy["minimum_history_days"]),
                        step=1,
                    )
                with c2:
                    override_pct = st.number_input(
                        "Manual override threshold (%)",
                        min_value=0.0,
                        value=float(policy["maximum_override_percent"]),
                        step=1.0,
                    )
                    formal_above = st.number_input(
                        "Formal approval threshold ($)",
                        min_value=0.0,
                        value=float(policy["require_formal_approval_above_value"]),
                        step=100.0,
                    )
                    stockout_review = st.checkbox(
                        "Route stockout exceptions to human review",
                        value=bool(policy["require_review_for_stockout"]),
                    )
                    overstock_review = st.checkbox(
                        "Route overstock exceptions to human review",
                        value=bool(policy["require_review_for_overstock"]),
                    )
                    promo_review = st.checkbox(
                        "Promotion overlap requires human review",
                        value=bool(policy["require_review_for_promotion_overlap"]),
                    )

                submitted = st.form_submit_button(
                    "Publish new version",
                    type="primary",
                    use_container_width=True,
                )

            if submitted:
                changes = {
                    "auto_release_max_value": Decimal(str(auto_ceiling)),
                    "minimum_confidence": Decimal(str(min_conf)),
                    "maximum_inventory_age_hours": int(max_age),
                    "maximum_days_of_supply": Decimal(str(max_dos)),
                    "minimum_history_days": int(min_history),
                    "maximum_override_percent": Decimal(str(override_pct)),
                    "require_formal_approval_above_value": Decimal(str(formal_above)),
                    "require_review_for_stockout": bool(stockout_review),
                    "require_review_for_overstock": bool(overstock_review),
                    "require_review_for_promotion_overlap": bool(promo_review),
                }
                # Only send fields that actually changed.
                delta = {}
                for key, value in changes.items():
                    prior = policy.get(key)
                    if key.startswith("require_"):
                        if bool(prior) != bool(value):
                            delta[key] = value
                    else:
                        if Decimal(str(prior)) != Decimal(str(value)):
                            delta[key] = value
                if not delta:
                    st.info("No changes detected — active version left unchanged.")
                else:
                    try:
                        result = policy_service.publish_policy_version(
                            actor=user["user_id"],
                            actor_role=user["role"],
                            changes=delta,
                        )
                        st.session_state["policy_publish_result"] = result
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(user_facing_error(exc))

            if "policy_publish_result" in st.session_state:
                result = st.session_state.pop("policy_publish_result")
                st.success(
                    f"Published {result['policy_version']} "
                    f"(supersedes {result['supersedes_policy_version']})."
                )
                with st.expander("Technical details", expanded=False):
                    st.json(result)

        with st.expander("Policy version history", expanded=False):
            versions = view.get("versions") or []
            if not versions:
                st.caption("No versions recorded yet.")
            else:
                st.dataframe(
                    [
                        {
                            "Version": v["policy_version"],
                            "Active": "Yes" if v["active"] else "No",
                            "Created by": v["created_by"],
                            "Created at": v["created_at"],
                            "Effective from": v["effective_from"],
                            "Effective to": v["effective_to"] or "—",
                        }
                        for v in versions
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
    else:
        st.caption(
            "This page is read-only for your role. "
            "Administrators can publish a new policy version without altering history."
        )
        with st.expander("Policy version history", expanded=False):
            versions = view.get("versions") or []
            if versions:
                st.dataframe(
                    [
                        {
                            "Version": v["policy_version"],
                            "Active": "Yes" if v["active"] else "No",
                            "Created by": v["created_by"],
                            "Created at": v["created_at"],
                        }
                        for v in versions
                    ],
                    use_container_width=True,
                    hide_index=True,
                )


if __name__ == "__main__":
    main()
