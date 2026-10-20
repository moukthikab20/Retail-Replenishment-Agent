"""Today's Decisions — exception workbench (presentation only)."""

from __future__ import annotations

from html import escape
from typing import Any, Callable

import streamlit as st

from services import auth_service, disposition_service, product_service, queue_service, scheduler_service
from services.errors import user_facing_error
from ui_components import AGENT_LANGUAGE, empty_state, page_heading, status_pill

OUTCOME_OPTIONS = [
    ("needs_review", AGENT_LANGUAGE["needs_review"]),
    ("blocked", "Blocked by policy"),
    ("auto_released", AGENT_LANGUAGE["handled_automatically"]),
    ("no_order", "No order required"),
    ("all", "All decisions"),
]


def _risk_kind(risk: str | None) -> str:
    return {
        "stockout": "critical",
        "overstock": "attention",
        "balanced": "success",
        "manual_review": "attention",
        "insufficient_data": "attention",
    }.get(risk or "", "neutral")


def _priority_kind(priority: str) -> str:
    return {"High": "critical", "Medium": "attention", "Normal": "neutral"}.get(
        priority, "neutral"
    )


def _clear_filters() -> None:
    st.session_state["queue_filter"] = "needs_review"
    st.session_state["queue_status_key"] = "needs_review"
    st.session_state["queue_store_id"] = ""
    st.session_state["queue_search"] = ""
    st.session_state["queue_search_input"] = ""
    st.session_state["queue_risk_key"] = "all"


def _render_no_action_required_card() -> None:
    st.markdown(
        """
        <div class="il-queue-no-action">
          <div class="il-queue-no-action-kicker">NO ACTION REQUIRED</div>
          <div class="il-queue-no-action-title">You're caught up.</div>
          <p class="il-queue-no-action-body">There are currently no replenishment decisions waiting
          for your approval.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _handle_blocked_nav_query() -> None:
    raw = st.query_params.get("nav_blocked")
    if raw == "1" or raw == ["1"]:
        try:
            del st.query_params["nav_blocked"]
        except Exception:  # noqa: BLE001
            pass
        st.switch_page("pages/12_Blocked.py")


def _render_agent_activity(summary: dict[str, Any]) -> None:
    auto = int(summary.get("auto_released") or 0)
    blocked = int(summary.get("blocked") or 0)
    no_order = int(summary.get("no_order") or 0)

    st.markdown(
        '<div class="il-queue-activity-heading">AGENT ACTIVITY</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="agent-activity-list">
          <div class="agent-activity-row">
            <div class="activity-count is-auto">{auto}</div>
            <div class="activity-label">Handled automatically</div>
            <div></div>
          </div>
          <div class="agent-activity-row">
            <div class="activity-count is-blocked">{blocked}</div>
            <div class="activity-label">Blocked by policy</div>
            <div class="activity-action">
              <a class="activity-action-link" href="?nav_blocked=1">Review blocked →</a>
            </div>
          </div>
          <div class="agent-activity-row">
            <div class="activity-count is-no-order">{no_order}</div>
            <div class="activity-label">No order required</div>
            <div></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_prior_analyses(
    runs: list[dict[str, Any]],
    run: dict[str, Any],
    selected_run_id: str | None,
) -> None:
    if not runs:
        return
    with st.container(key="queue_prior_analyses"):
        with st.expander("Prior analyses →", expanded=False):
            labels = [r["label"] for r in runs]
            ids = [r["run_id"] for r in runs]
            try:
                current_index = ids.index(selected_run_id) if selected_run_id in ids else 0
            except ValueError:
                current_index = 0
            chosen = st.selectbox(
                "Analysis",
                options=labels,
                index=current_index,
                key="queue_run_selector",
            )
            chosen_id = ids[labels.index(chosen)]
            if chosen_id != selected_run_id:
                st.session_state["queue_selected_run_id"] = chosen_id
                st.rerun()
            st.caption(
                f"Policy {run.get('policy_version') or '—'} · "
                f"{run.get('scored_items') or 0}/{run.get('total_items') or 0} scored"
            )


def _navigate_to_decision(
    row: dict[str, Any],
    *,
    on_open_detail: Callable[[str], None] | None,
) -> None:
    """Session-safe row navigation — same mechanism as Overview decisions."""
    rid = str(row.get("recommendation_id") or "")
    if not rid:
        return
    st.session_state["nav_recommendation_id"] = rid
    st.session_state["recommendation_id"] = rid
    st.session_state["selected_decision_id"] = rid
    sku = str(row.get("sku") or "")
    store_id = str(row.get("store_id") or "")
    if sku:
        st.session_state["selected_sku"] = sku
    if store_id:
        st.session_state["selected_store_id"] = store_id
    if on_open_detail is not None:
        on_open_detail(rid)
    else:
        st.switch_page("pages/2_Review.py")


def _decision_row_cells(row: dict[str, Any]) -> str:
    store_display = row.get("store_name") or product_service.store_display_name(row.get("store_id"))
    product = row.get("item") or row.get("sku") or "—"
    why = str(row.get("why") or row.get("exception") or "—")
    return (
        f"<div>{status_pill(_priority_kind(row.get('priority') or 'Normal'), row.get('priority') or 'Normal')}</div>"
        f"<div>{escape(str(store_display))}</div>"
        f"<div>{escape(str(product))}</div>"
        f"<div>{escape(str(row.get('recommendation_display') or '—'))}</div>"
        f"<div class='il-decisions-why'>{escape(why)}</div>"
        f"<div class='il-decisions-badge'>{status_pill(_risk_kind(row.get('risk_level')), row.get('risk_label') or '—')}</div>"
        f"<div class='num'>{escape(str(row.get('order_value_display') or '—'))}</div>"
        f"<div class='il-decisions-badge'>{status_pill(row.get('status_kind') or 'neutral', row.get('status') or '—')}</div>"
    )


def _resolve_selected_run_id(runs: list[dict[str, Any]]) -> str | None:
    if not runs:
        st.session_state.pop("queue_selected_run_id", None)
        return None
    latest_id = runs[0]["run_id"]
    selected = st.session_state.get("queue_selected_run_id")
    valid_ids = {r["run_id"] for r in runs}
    if selected not in valid_ids:
        st.session_state["queue_selected_run_id"] = latest_id
        return latest_id
    return str(selected)


def render_todays_queue(
    *,
    filter_key: str | None = None,
    on_open_detail: Callable[[str], None] | None = None,
    show_heading: bool = True,
    actor: str | None = None,
    actor_role: str | None = None,
    session_id: str | None = None,
    enable_bulk: bool = True,
) -> dict[str, Any]:
    """
    Exception workbench for a selected persisted replenishment run.

    Changing filters reloads persisted data only — never scores.
    """
    _handle_blocked_nav_query()
    # Default to Needs review — this page is an exception inbox.
    # Status widget key (queue_status_key) is the interactive source of truth.
    valid_filters = {key for key, _ in OUTCOME_OPTIONS}
    if filter_key is not None:
        active_filter = filter_key
        st.session_state["queue_status_key"] = filter_key
    elif "queue_status_key" in st.session_state:
        active_filter = st.session_state["queue_status_key"]
    elif "queue_filter" in st.session_state:
        active_filter = st.session_state["queue_filter"]
        st.session_state["queue_status_key"] = active_filter
    else:
        active_filter = "needs_review"
        st.session_state["queue_status_key"] = active_filter
    if st.session_state.pop("queue_show_all_requested", False):
        active_filter = "all"
        st.session_state["queue_status_key"] = "all"
    if active_filter not in valid_filters:
        active_filter = "needs_review"
        st.session_state["queue_status_key"] = active_filter
    st.session_state["queue_filter"] = active_filter

    trigger = scheduler_service.get_run_trigger_status()
    active_run = trigger.get("active_run")
    running = bool(active_run) or str(trigger.get("current_status") or "").lower() == "running"

    runs = queue_service.list_replenishment_runs(limit=30, terminal_only=True)
    selected_run_id = _resolve_selected_run_id(runs)

    store_id = st.session_state.get("queue_store_id") or ""
    risk_key = st.session_state.get("queue_risk_key") or "all"

    payload = queue_service.get_todays_queue(
        filter_key=active_filter,  # type: ignore[arg-type]
        run_id=selected_run_id,
        store_id=store_id or None,
        search=None,
        risk_key=risk_key or "all",
    )
    run = payload.get("run")
    summary = payload["summary"]
    filter_options = payload.get("filter_options") or {}
    has_run = run is not None

    if show_heading:
        page_heading("Today's Decisions")

    # —— Empty: running with no completed run ——
    if running and not has_run:
        ar = active_run or {}
        scored = ar.get("scored_items")
        total = ar.get("total_items")
        progress = (
            f"Progress: {scored}/{total} positions scored."
            if scored is not None and total is not None
            else "Results will appear here when the analysis finishes."
        )
        empty_state(
            title="Analysis in progress",
            explanation="The agent is scoring today's inventory positions.",
            next_step="Exceptions will appear here when scoring finishes.",
            schedule_or_status=progress,
            secondary_label="Refresh",
            secondary_action=st.rerun,
            key_prefix="queue_running",
        )
        return payload

    # —— Empty: no run ——
    if not has_run:
        next_at = trigger.get("next_run_display") or "the next scheduled window"
        can_run = actor_role and auth_service.can_trigger_batch_run(actor_role)

        def _run_now() -> None:
            try:
                outcome = scheduler_service.run_now(
                    actor=actor or "system",
                    actor_role=actor_role,
                    session_id=session_id,
                )
                st.session_state["queue_run_outcome"] = outcome
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(user_facing_error(exc))

        empty_state(
            title="No analysis yet",
            explanation="The agent hasn't analyzed today's inventory yet.",
            next_step=(
                "Start analysis now, or wait for the scheduled window."
                if can_run
                else "An administrator can start analysis manually if needed."
            ),
            schedule_or_status=f"Next scheduled analysis: {next_at}",
            primary_label="Run replenishment now" if can_run else None,
            primary_action=_run_now if can_run else None,
            primary_disabled=not trigger.get("can_start_new_run", True),
            secondary_label="Refresh",
            secondary_action=st.rerun,
            key_prefix="queue_norun",
        )
        if "queue_run_outcome" in st.session_state:
            outcome = st.session_state.pop("queue_run_outcome")
            if outcome.get("started"):
                run_meta = outcome.get("run") or {}
                st.success(
                    f"Analysis finished ({run_meta.get('scored_items', 0)}/"
                    f"{run_meta.get('total_items', 0)} scored)."
                )
            else:
                st.warning(outcome.get("message") or "Run was not started.")
        return payload

    if int(summary.get("needs_review") or 0) == 0:
        _render_no_action_required_card()

    _render_agent_activity(summary)

    stores = filter_options.get("stores") or [{"store_id": "", "store_name": "All stores"}]
    risks = filter_options.get("risks") or [{"key": "all", "label": "All risks"}]
    store_labels = [s["store_name"] for s in stores]
    store_ids = [s["store_id"] for s in stores]
    risk_labels = [r["label"] for r in risks]
    risk_keys = [r["key"] for r in risks]
    outcome_keys = [key for key, _ in OUTCOME_OPTIONS]
    outcome_label_by_key = {k: lab for k, lab in OUTCOME_OPTIONS}

    can_bulk = (
        enable_bulk
        and actor
        and actor_role
        and auth_service.can_submit_human_review(actor_role)
        and summary["needs_review"] > 0
        and active_filter == "needs_review"
    )
    with st.container(key="queue_filter_row"):
        cols = st.columns(3, gap="small")
        with cols[0]:
            try:
                store_index = store_ids.index(store_id) if store_id in store_ids else 0
            except ValueError:
                store_index = 0
            picked_store = st.selectbox(
                "Store",
                options=store_labels,
                index=store_index,
                key="queue_store_select",
                label_visibility="collapsed",
            )
            new_store = store_ids[store_labels.index(picked_store)]
        with cols[1]:
            try:
                risk_index = risk_keys.index(risk_key) if risk_key in risk_keys else 0
            except ValueError:
                risk_index = 0
            picked_risk = st.selectbox(
                "Risk",
                options=risk_labels,
                index=risk_index,
                key="queue_risk_select",
                label_visibility="collapsed",
            )
            new_risk = risk_keys[risk_labels.index(picked_risk)]
        with cols[2]:
            try:
                outcome_index = outcome_keys.index(active_filter)
            except ValueError:
                outcome_index = 0
            new_status = st.selectbox(
                "Outcome",
                options=outcome_keys,
                index=outcome_index,
                format_func=lambda k: outcome_label_by_key.get(k, k),
                key="queue_status_key",
                label_visibility="collapsed",
            )

    _render_prior_analyses(runs, run, selected_run_id)

    if can_bulk:
        if st.button(
            "Approve within policy",
            type="primary",
            key="queue_bulk_approve",
        ):
            try:
                bulk = disposition_service.approve_all_within_policy(
                    actor=actor,
                    actor_role=actor_role,
                    run_id=run["run_id"] if run else None,
                    user_id=actor,
                    session_id=session_id,
                )
                st.session_state["queue_bulk_result"] = bulk
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(user_facing_error(exc))

    filters_changed = (
        new_store != store_id
        or new_risk != risk_key
        or new_status != active_filter
    )
    if filters_changed:
        st.session_state["queue_store_id"] = new_store
        st.session_state["queue_risk_key"] = new_risk
        st.session_state["queue_filter"] = new_status
        st.rerun()

    if "queue_bulk_result" in st.session_state:
        bulk = st.session_state.pop("queue_bulk_result")
        st.success(
            f"Bulk complete — approved {bulk['approved']}, "
            f"pending {bulk['pending_approval']}, "
            f"skipped {bulk['skipped']}, failed {bulk['failed']}."
        )

    rows = payload["rows"]
    has_extra = bool(
        (store_id and str(store_id).strip())
        or (risk_key and risk_key != "all")
    )

    # —— Filter empty ——
    if not rows:
        if (
            active_filter == "needs_review"
            and not has_extra
            and int(summary.get("needs_review") or 0) == 0
        ):
            return payload
        if has_extra or active_filter != "all":

            def _clear_and_rerun() -> None:
                _clear_filters()
                st.rerun()

            empty_state(
                title="No matching decisions",
                explanation="No decisions match these filters.",
                next_step="Clear filters to see the full workbench.",
                primary_label="Clear filters",
                primary_action=_clear_and_rerun,
                key_prefix="queue_filter_empty",
            )
        else:
            msg = payload.get("empty_message") or queue_service.empty_state_message(
                filter_key=active_filter, has_run=True
            )
            empty_state(
                title="No decisions",
                explanation=msg,
                next_step="Run or select another analysis if needed.",
                key_prefix="queue_empty",
            )
        return payload

    # —— Decision table (visual center); whole row is the click target ——
    selected_id = str(st.session_state.get("selected_decision_id") or "")
    st.markdown(
        "<div class='il-queue-table il-decisions-table'>"
        "<div class='il-queue-head'>"
        "<div>Priority</div><div>Store</div><div>Product</div>"
        f"<div>{AGENT_LANGUAGE['recommends']}</div><div>Why</div>"
        "<div>Risk</div><div class='num'>Order value</div><div>Status</div>"
        "</div></div>",
        unsafe_allow_html=True,
    )
    with st.container(key="queue_decisions_wrap"):
        for row in rows:
            rid = str(row.get("recommendation_id") or "")
            if not rid:
                continue
            selected = " is-selected" if rid == selected_id else ""
            with st.container(key=f"queue_row_hit_{rid}"):
                clicked = st.button(
                    " ",
                    key=f"queue_row_nav_{rid}",
                    use_container_width=True,
                    type="secondary",
                )
                st.markdown(
                    "<div class='il-queue-table il-decisions-table'>"
                    f"<div class='il-queue-row{selected}'>"
                    f"{_decision_row_cells(row)}"
                    "</div></div>",
                    unsafe_allow_html=True,
                )
                if clicked:
                    _navigate_to_decision(row, on_open_detail=on_open_detail)

    return payload
