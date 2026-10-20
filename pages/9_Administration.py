"""Administration — batch Run now, schedule status, retry, and demo reset."""

from __future__ import annotations

import streamlit as st

from services import auth_service, scheduler_service
from services.errors import user_facing_error
from ui_common import bootstrap_app
from ui_components import kpi_row, page_heading, panel_title, status_pill


def _run_status_kind(status: str | None) -> str:
    return {
        "completed": "ok",
        "completed_with_errors": "warn",
        "failed": "danger",
        "running": "warn",
        "pending": "neutral",
        "idle": "neutral",
    }.get(status or "", "neutral")


def main() -> None:
    user = bootstrap_app(
        "Administration | Retail Replenishment Agent",
        active_nav="administration",
    )
    page_heading("Administration", "Batch runs and environment maintenance")

    is_admin = auth_service.can_reset_demo(user["role"])
    can_run = auth_service.can_trigger_batch_run(user["role"])
    if not is_admin and not can_run:
        st.warning("Administration is available only to administrators.")
        return
    try:
        auth_service.authorize_administration(user["role"])
    except auth_service.AuthError as exc:
        st.error(str(exc))
        return

    # Read-only status — opening this page never starts a batch.
    status = scheduler_service.get_run_trigger_status()
    latest = status.get("latest_run")
    active = status.get("active_run")
    schedule = status.get("schedule") or {}
    health = status.get("scheduler_health") or scheduler_service.get_scheduler_health()

    with st.container(border=True):
        panel_title("Scheduler", hint="Environment-configured; UI does not toggle enablement")
        kpi_row(
            [
                {
                    "label": "Scheduler",
                    "value": "Enabled" if schedule.get("enabled") else "Disabled",
                    "sub": health.get("status") or "—",
                },
                {
                    "label": "Schedule",
                    "value": schedule.get("schedule_display")
                    or f"Every {schedule.get('interval_hours', 6)}h",
                    "sub": schedule.get("cron") or "",
                },
                {
                    "label": "Timezone",
                    "value": schedule.get("timezone") or "UTC",
                    "sub": f"Stale +{schedule.get('stale_tolerance_minutes', 90)}m",
                },
                {
                    "label": "Next run",
                    "value": status.get("next_run_display") or "—",
                    "sub": "Due now" if status.get("next_run_due") else "Cron-aligned",
                    "accent": bool(status.get("next_run_due")),
                },
            ],
            columns=4,
        )
        last_sched = health.get("last_scheduled_run") or {}
        last_ok = health.get("last_successful_run") or {}
        st.caption(
            f"Health: {health.get('status')} — {health.get('message') or ''} · "
            f"Last scheduled: {last_sched.get('run_id') or '—'} "
            f"({last_sched.get('status') or 'n/a'}) · "
            f"Last successful scheduled: {last_ok.get('run_id') or '—'}"
        )

    from integrations.factory import get_provider_summary

    with st.container(border=True):
        panel_title(
            "Integration providers",
            hint="Read-only — change via environment / deployment config",
        )
        try:
            providers = get_provider_summary().get("providers") or {}
        except Exception as exc:  # noqa: BLE001
            providers = {}
            st.warning(f"Provider configuration error: {exc}")
        if providers:
            st.write(
                {
                    "Inventory": f"{(providers.get('inventory') or {}).get('provider_name')} "
                    f"[{(providers.get('inventory') or {}).get('config')}]",
                    "Sales": f"{(providers.get('sales') or {}).get('provider_name')} "
                    f"[{(providers.get('sales') or {}).get('config')}]",
                    "Product": f"{(providers.get('product') or {}).get('provider_name')} "
                    f"[{(providers.get('product') or {}).get('config')}]",
                    "Supplier": f"{(providers.get('supplier') or {}).get('provider_name')} "
                    f"[{(providers.get('supplier') or {}).get('config')}]",
                    "ERP": f"{(providers.get('erp') or {}).get('provider_name')} "
                    f"[{(providers.get('erp') or {}).get('config')}]",
                }
            )

    with st.container(border=True):
        panel_title("Replenishment batch", hint="Scores the full store/SKU catalog")
        kpi_row(
            [
                {
                    "label": "Catalog size",
                    "value": status.get("eligible_pair_count", 0),
                    "sub": "Store × SKU pairs",
                },
                {
                    "label": "Interval",
                    "value": f"{schedule.get('interval_hours', 6)}h",
                    "sub": schedule.get("cron") or "scheduled CLI",
                },
                {
                    "label": "Last run",
                    "value": status.get("last_run_display") or "—",
                    "sub": (latest or {}).get("status") or "No completed run yet",
                },
                {
                    "label": "Next run",
                    "value": status.get("next_run_display") or "—",
                    "sub": "Due now" if status.get("next_run_due") else (schedule.get("timezone") or "UTC"),
                    "accent": bool(status.get("next_run_due")),
                },
            ],
            columns=4,
        )

        st.markdown(
            status_pill(
                _run_status_kind(status.get("current_status")),
                f"Status: {status.get('current_status') or 'idle'}",
            ),
            unsafe_allow_html=True,
        )

        if latest:
            st.caption(
                f"Latest run {latest.get('run_id')} · trigger={latest.get('trigger_type')} · "
                f"by {latest.get('initiated_by')} · "
                f"SKUs scored {latest.get('scored_items')}/{latest.get('total_items')} · "
                f"review={latest.get('review_items')} blocked={latest.get('blocked_items')} "
                f"auto={latest.get('auto_released_items')}"
            )
        else:
            st.info("No replenishment run has completed yet. Use Run now or the scheduled job.")

        if active:
            st.warning(
                f"Run {active.get('run_id')} is {active.get('status')}. "
                "A new Run now is blocked until it finishes."
            )

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            run_now = st.button(
                "Run now",
                type="primary",
                use_container_width=True,
                disabled=not can_run or not status.get("can_start_new_run", True),
            )
        with c2:
            retry = st.button(
                "Retry failed run",
                use_container_width=True,
                disabled=not can_run or not status.get("can_retry_failed", False),
            )
        with c3:
            if st.button("Open Today's Queue", use_container_width=True):
                st.switch_page("pages/1_Todays_Queue.py")
        with c4:
            if st.button("Refresh status", use_container_width=True):
                st.rerun()

        st.caption(
            "Scheduled runs use "
            f"`{schedule.get('entry_point') or 'python -m jobs.run_replenishment'}` "
            f"every {schedule.get('interval_hours', 6)} hours "
            f"(cron `{schedule.get('cron')}`). "
            "Opening this page never starts a batch. "
            f"Cron secret configured: {'yes' if schedule.get('cron_secret_configured') else 'no (local)'}."
        )

        if run_now:
            try:
                outcome = scheduler_service.run_now(
                    actor=user["user_id"],
                    actor_role=user["role"],
                    session_id=user["session_id"],
                )
                st.session_state["admin_run_outcome"] = outcome
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(user_facing_error(exc))

        if retry:
            try:
                outcome = scheduler_service.retry_failed_run(
                    actor=user["user_id"],
                    actor_role=user["role"],
                    session_id=user["session_id"],
                )
                st.session_state["admin_run_outcome"] = outcome
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(user_facing_error(exc))

        if "admin_run_outcome" in st.session_state:
            outcome = st.session_state.pop("admin_run_outcome")
            if not outcome.get("started"):
                st.warning(outcome.get("message") or "Run was not started.")
            else:
                run = outcome.get("run") or {}
                st.success(
                    f"Run {run.get('run_id')} finished with status={run.get('status')} "
                    f"({run.get('scored_items')}/{run.get('total_items')} scored)."
                )
                with st.expander("View run details", expanded=False):
                    st.json(run)

    with st.container(border=True):
        panel_title(
            "Diagnostic tools",
            hint="Secondary capabilities — not the planner workflow",
        )
        st.caption(
            "Manual Analysis lets administrators inspect a single store/SKU pair "
            "outside the batch queue. Day-to-day decisions stay on Today's Queue."
        )
        if st.button(
            "Manual Analysis / Diagnostic Analysis",
            use_container_width=True,
            key="admin_open_analysis",
        ):
            st.switch_page("pages/8_Analysis.py")

    if is_admin:
        with st.container(border=True):
            panel_title("Demo Data")
            st.markdown(
                '<p class="secondary-text">Reset clears transactional demo records and reseeds sample data. '
                "This does not change authentication configuration.</p>",
                unsafe_allow_html=True,
            )
            if st.button("Reset Demo Data", type="secondary"):
                try:
                    from services.demo_data_service import reset_and_seed

                    result = reset_and_seed(actor=user["user_id"], actor_role=user["role"])
                    for key in (
                        "analysis_decision",
                        "recommendation_id",
                        "nav_recommendation_id",
                        "approval_id",
                        "order_flow",
                        "erp_cutoff_result",
                        "queue_bulk_result",
                        "admin_run_outcome",
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
