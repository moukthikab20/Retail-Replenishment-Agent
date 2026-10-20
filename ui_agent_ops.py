"""Agent Operations UI — administrator monitoring of durable executions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

import streamlit as st

from services import agent_ops_service, auth_service, scheduler_service
from ui_components import kpi_row, page_heading, panel_title, status_pill


def _status_kind(status: str | None) -> str:
    return {
        "completed": "ok",
        "running": "warn",
        "planning": "warn",
        "created": "neutral",
        "waiting_for_tool": "warn",
        "waiting_for_human": "warn",
        "paused": "warn",
        "retry_pending": "warn",
        "failed": "danger",
        "cancelled": "neutral",
        "rejected": "danger",
        "healthy": "ok",
        "degraded": "warn",
        "stale": "warn",
        "disabled": "neutral",
        "unavailable": "danger",
    }.get((status or "").lower(), "neutral")


def _fmt_ts(value: str | None) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return value[:19]


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = int(seconds // 60)
    rem = seconds % 60
    return f"{minutes}m {rem:.0f}s"


def _token_display(value: int | None) -> str:
    return "—" if value is None else str(value)


def render_agent_operations(*, actor_role: str) -> None:
    """Full Agent Operations page body. Read-only — no agent/batch/OpenAI side effects."""
    page_heading(
        "Agent Operations",
        "Durable execution monitoring — administrators only",
    )

    if not auth_service.can_view_agent_operations(actor_role):
        st.warning("Agent Operations is available only to administrators.")
        return

    # Enforce again at the service boundary (UI is supplemental).
    try:
        auth_service.authorize_agent_operations(actor_role)
    except auth_service.AuthError as exc:
        st.error(str(exc))
        return

    cols = st.columns([1, 5])
    with cols[0]:
        if st.button("Refresh", key="agent_ops_refresh"):
            st.rerun()
    with cols[1]:
        st.caption("Refresh reloads persisted execution state only — no agent, batch, or OpenAI calls.")

    metrics = agent_ops_service.get_operations_metrics(actor_role=actor_role)
    avg = metrics.get("average_execution_duration_seconds")
    kpi_row(
        [
            {
                "label": "Active Executions",
                "value": metrics.get("active_executions", 0),
                "sub": "In-flight (excl. HITL wait)",
            },
            {
                "label": "Waiting for Human",
                "value": metrics.get("waiting_for_human", 0),
                "sub": "HITL pause",
            },
            {
                "label": "Retry Pending",
                "value": metrics.get("retry_pending", 0),
            },
            {
                "label": "Failed",
                "value": metrics.get("failed_executions", 0),
            },
            {
                "label": "Completed Today",
                "value": metrics.get("completed_today", 0),
                "sub": metrics.get("timezone") or "UTC",
            },
            {
                "label": "Average Duration",
                "value": _fmt_duration(avg) if avg is not None else "—",
                "sub": "Completed only",
            },
            {
                "label": "Open HITL Requests",
                "value": metrics.get("open_hitl_requests", 0),
            },
        ],
        columns=4,
    )

    _render_scheduler_panel()
    _render_filters_and_table(actor_role=actor_role)
    _render_waiting_section(actor_role=actor_role)
    _render_failed_section(actor_role=actor_role)

    selected = st.session_state.get("agent_ops_selected_id")
    if selected:
        _render_execution_detail(selected, actor_role=actor_role)


def _render_scheduler_panel() -> None:
    with st.container(border=True):
        panel_title("Scheduler", hint="From scheduler_service (read-only)")
        health = scheduler_service.get_scheduler_health()
        status = scheduler_service.get_run_trigger_status()
        schedule = status.get("schedule") or {}
        st.markdown(
            status_pill(_status_kind(str(health.get("status"))), agent_ops_service.status_label(str(health.get("status")))),
            unsafe_allow_html=True,
        )
        last_sched = health.get("last_scheduled_run") or {}
        last_ok = health.get("last_successful_run") or {}
        st.write(
            {
                "Enabled": "Enabled" if schedule.get("enabled") else "Disabled",
                "Cron": schedule.get("cron") or health.get("cron") or "—",
                "Timezone": schedule.get("timezone") or health.get("timezone") or "—",
                "Last scheduled run": last_sched.get("run_id") or "—",
                "Last successful run": last_ok.get("run_id") or "—",
                "Next run": status.get("next_run_display")
                or health.get("next_scheduled_run_display")
                or "—",
            }
        )


def _render_filters_and_table(*, actor_role: str) -> None:
    with st.container(border=True):
        panel_title("Executions", hint="Persisted AgentRunStateRow — newest first")
        f1, f2, f3, f4 = st.columns(4)
        with f1:
            status_opts = [
                "(all)",
                "created",
                "planning",
                "running",
                "waiting_for_tool",
                "waiting_for_human",
                "retry_pending",
                "completed",
                "failed",
                "cancelled",
            ]
            status_sel = st.selectbox("Status", status_opts, key="agent_ops_status")
        with f2:
            type_opts = [
                "(all)",
                "recommendation_analysis",
                "follow_up",
                "scenario_analysis",
                "order_execution",
            ]
            type_sel = st.selectbox("Execution type", type_opts, key="agent_ops_type")
        with f3:
            window = st.selectbox(
                "Time window",
                ["Recent (7 days)", "Today", "Last 24 hours", "All"],
                key="agent_ops_window",
            )
        with f4:
            actor = st.text_input("User / Actor", key="agent_ops_actor").strip() or None

        r1, r2, r3 = st.columns(3)
        with r1:
            rec_id = st.text_input("Recommendation ID", key="agent_ops_rec").strip() or None
        with r2:
            run_filter = st.text_input("Run / Execution ID", key="agent_ops_run").strip() or None
        with r3:
            err_code = st.text_input("Failure code", key="agent_ops_err").strip() or None

        now = datetime.now(timezone.utc)
        started_after = None
        if window == "Today":
            started_after = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif window == "Last 24 hours":
            started_after = now - timedelta(hours=24)
        elif window == "Recent (7 days)":
            started_after = now - timedelta(days=7)

        statuses = None if status_sel == "(all)" else [status_sel]
        if status_sel == "waiting_for_human":
            statuses = ["waiting_for_human", "paused"]
        types = None if type_sel == "(all)" else [type_sel]

        page = int(st.session_state.get("agent_ops_page", 0) or 0)
        limit = 50
        rows = agent_ops_service.list_agent_executions(
            statuses=statuses,
            execution_types=types,
            recommendation_id=rec_id,
            run_id=run_filter,
            user_id=actor,
            last_error_code=err_code,
            started_after=started_after,
            limit=limit,
            offset=page * limit,
            actor_role=actor_role,
        )

        csv_data = agent_ops_service.export_execution_summary_csv(
            limit=100,
            statuses=statuses,
            actor_role=actor_role,
        )
        st.download_button(
            "Export Execution Summary CSV",
            data=csv_data,
            file_name="agent_execution_summary.csv",
            mime="text/csv",
            key="agent_ops_csv",
        )

        if not rows:
            st.info("No executions match the current filters.")
        else:
            header = (
                "<div class='il-queue-table'>"
                "<div class='il-queue-head'>"
                "<div>Execution</div><div>Type</div><div>Reference</div>"
                "<div>Status</div><div>Step</div><div>Next</div>"
                "<div>Started</div><div>Updated</div><div>Duration</div>"
                "<div>Attempts</div><div>Actor</div>"
                "</div>"
            )
            parts = [header]
            for row in rows:
                parts.append(
                    "<div class='il-queue-row'>"
                    f"<div><code>{escape(row.get('execution_id') or '')}</code></div>"
                    f"<div>{escape(agent_ops_service.type_label(row.get('execution_type')))}</div>"
                    f"<div>{escape(agent_ops_service.business_reference(row))}</div>"
                    f"<div>{status_pill(_status_kind(row.get('status')), agent_ops_service.status_label(row.get('status')))}</div>"
                    f"<div>{escape(agent_ops_service.display_value(row.get('current_step')))}</div>"
                    f"<div>{escape(agent_ops_service.display_value(row.get('next_action')))}</div>"
                    f"<div>{escape(_fmt_ts(row.get('created_at')))}</div>"
                    f"<div>{escape(_fmt_ts(row.get('updated_at')))}</div>"
                    f"<div>{escape(_fmt_duration(row.get('duration_seconds')))}</div>"
                    f"<div>{int(row.get('attempt_count') or 0)}/{int(row.get('max_attempts') or 3)}</div>"
                    f"<div>{escape(agent_ops_service.display_value(row.get('user_id')))}</div>"
                    "</div>"
                )
            parts.append("</div>")
            st.markdown("".join(parts), unsafe_allow_html=True)

            labels = [r["execution_id"] for r in rows]
            choice = st.selectbox(
                "Open execution detail",
                ["(none)"] + labels,
                key="agent_ops_detail_pick",
            )
            if choice and choice != "(none)":
                st.session_state["agent_ops_selected_id"] = choice

        c_prev, c_next, _ = st.columns([1, 1, 6])
        with c_prev:
            if st.button("Previous page", disabled=page <= 0, key="agent_ops_prev"):
                st.session_state["agent_ops_page"] = max(0, page - 1)
                st.rerun()
        with c_next:
            if st.button("Next page", disabled=len(rows) < limit, key="agent_ops_next"):
                st.session_state["agent_ops_page"] = page + 1
                st.rerun()


def _render_waiting_section(*, actor_role: str) -> None:
    waiting = agent_ops_service.list_waiting_for_human(limit=25, actor_role=actor_role)
    with st.container(border=True):
        panel_title("Waiting for Human", hint="Governed review — no approvals here")
        if not waiting:
            st.caption("No executions are waiting for human input.")
            return
        for row in waiting:
            cols = st.columns([2, 2, 2, 2, 2, 1])
            cols[0].markdown(f"`{row.get('execution_id')}`")
            cols[1].write(agent_ops_service.display_value(row.get("recommendation_id")))
            cols[2].write(agent_ops_service.display_value(row.get("approval_id")))
            cols[3].write(agent_ops_service.display_value(row.get("requested_action")))
            cols[4].write(
                f"{agent_ops_service.display_value(row.get('required_role'))}\n\n"
                f"{_fmt_ts(row.get('waiting_since'))}"
            )
            with cols[5]:
                if row.get("recommendation_id"):
                    if st.button(
                        "Open Review",
                        key=f"ops_review_{row['execution_id']}",
                    ):
                        st.session_state["queue_focus_recommendation_id"] = row[
                            "recommendation_id"
                        ]
                        if row.get("replenishment_run_id"):
                            st.session_state["queue_selected_run_id"] = row[
                                "replenishment_run_id"
                            ]
                        st.switch_page("pages/1_Todays_Queue.py")
                elif row.get("approval_id"):
                    if st.button(
                        "Open Approval",
                        key=f"ops_apr_{row['execution_id']}",
                    ):
                        st.session_state["agent_ops_selected_id"] = row["execution_id"]
                        st.info(
                            "Open Formal Approval from Today's Queue / Review "
                            f"for approval {row.get('approval_id')}."
                        )
            st.caption(
                agent_ops_service.display_value(row.get("waiting_reason"))
            )


def _render_failed_section(*, actor_role: str) -> None:
    failed = agent_ops_service.list_failed_or_retry(limit=25, actor_role=actor_role)
    with st.container(border=True):
        panel_title("Failed / Retry Pending", hint="No blind PO retries from this console")
        if not failed:
            st.caption("No failed or retry-pending executions.")
            return
        for row in failed:
            st.markdown(
                f"`{row.get('execution_id')}` · "
                f"{status_pill(_status_kind(row.get('status')), agent_ops_service.status_label(row.get('status')))} · "
                f"code `{agent_ops_service.display_value(row.get('last_error_code'))}` · "
                f"attempt {int(row.get('attempt_count') or 0)}/"
                f"{int(row.get('max_attempts') or 3)} · "
                f"updated {_fmt_ts(row.get('updated_at'))}",
                unsafe_allow_html=True,
            )
            st.caption(agent_ops_service.display_value(row.get("last_error_message")))
            if st.button("Open detail", key=f"ops_fail_{row['execution_id']}"):
                st.session_state["agent_ops_selected_id"] = row["execution_id"]
                st.rerun()


def _render_execution_detail(execution_id: str, *, actor_role: str) -> None:
    detail = agent_ops_service.get_agent_execution_detail(
        execution_id, actor_role=actor_role
    )
    with st.container(border=True):
        panel_title("Execution Detail", hint=execution_id)
        if detail is None:
            st.warning("Execution not found.")
            return

        st.markdown(
            status_pill(
                _status_kind(detail.get("status")),
                agent_ops_service.status_label(detail.get("status")),
            ),
            unsafe_allow_html=True,
        )
        info = {
            "Execution ID": detail.get("execution_id"),
            "Correlation ID": agent_ops_service.display_value(detail.get("correlation_id")),
            "Execution Type": agent_ops_service.type_label(detail.get("execution_type")),
            "Business Goal": agent_ops_service.display_value(detail.get("goal")),
            "Recommendation ID": agent_ops_service.display_value(
                detail.get("recommendation_id")
            ),
            "Approval ID": agent_ops_service.display_value(detail.get("approval_id")),
            "Replenishment Run": agent_ops_service.display_value(
                detail.get("replenishment_run_id")
            ),
            "User": agent_ops_service.display_value(detail.get("user_id")),
            "Session": agent_ops_service.display_value(detail.get("session_id")),
            "Status": agent_ops_service.status_label(detail.get("status")),
            "Current Step": agent_ops_service.display_value(detail.get("current_step")),
            "Next Action": agent_ops_service.display_value(detail.get("next_action")),
            "Attempts": f"{detail.get('attempt_count')}/{detail.get('max_attempts')}",
            "Version": detail.get("version"),
            "Created": _fmt_ts(detail.get("created_at")),
            "Updated": _fmt_ts(detail.get("updated_at")),
            "Completed": _fmt_ts(detail.get("completed_at")),
            "Duration": _fmt_duration(detail.get("duration_seconds")),
        }
        st.write(info)

        order_lc = detail.get("order_lifecycle") or {}
        if order_lc:
            st.subheader("Order / ERP Lifecycle")
            st.write(
                {
                    "Order Intent ID": agent_ops_service.display_value(
                        order_lc.get("order_intent_id")
                    ),
                    "Order Status": agent_ops_service.display_value(
                        order_lc.get("order_status_label") or order_lc.get("order_status")
                    ),
                    "ERP Provider": agent_ops_service.display_value(
                        order_lc.get("erp_provider")
                    ),
                    "ERP Transmission Status": agent_ops_service.display_value(
                        order_lc.get("erp_transmission_status")
                    ),
                    "Attempts": order_lc.get("attempts"),
                    "External Order ID": agent_ops_service.display_value(
                        order_lc.get("external_order_id")
                    ),
                    "Acknowledged At": _fmt_ts(order_lc.get("acknowledged_at")),
                    "Retry Pending": bool(order_lc.get("retry_pending")),
                    "Next Retry At": _fmt_ts(order_lc.get("next_retry_at")),
                    "Last Failure": agent_ops_service.display_value(
                        order_lc.get("last_failure")
                    ),
                }
            )

        memory = detail.get("memory") or {}
        if memory:
            st.subheader("Memory & Knowledge")
            st.write(
                {
                    "Memory retrieved": "Yes" if memory.get("memory_retrieved") else "No",
                    "Knowledge sources": ", ".join(memory.get("knowledge_sources") or [])
                    or "—",
                    "Retrieved records": memory.get("retrieved_records"),
                    "Records by type": memory.get("records_by_type") or {},
                    "Context size": f"{memory.get('context_size_chars') or 0} chars",
                    "Retrieval latency": (
                        f"{float(memory.get('retrieval_latency_ms') or 0):.2f} ms"
                    ),
                    "Provider": agent_ops_service.display_value(
                        memory.get("provider_name")
                    ),
                    "Citations": ", ".join(memory.get("citations") or []) or "—",
                }
            )
            kr = memory.get("knowledge_retrieval") or {}
            if kr:
                st.markdown("**Knowledge Retrieval**")
                score = kr.get("score_range") or {}
                st.write(
                    {
                        "Method": agent_ops_service.display_value(kr.get("method")),
                        "Results": kr.get("result_count"),
                        "Source IDs": ", ".join(kr.get("source_ids") or []) or "—",
                        "Latency": (
                            f"{float(kr.get('retrieval_latency_ms') or 0):.2f} ms"
                        ),
                        "Context size": f"{kr.get('context_size_chars') or 0} chars",
                        "Score range": (
                            f"{score.get('min')} – {score.get('max')}"
                            if score.get("min") is not None
                            else "—"
                        ),
                        "Degraded": "Yes" if kr.get("degraded") else "No",
                        "Degradation": agent_ops_service.display_value(
                            kr.get("degradation_reason")
                        ),
                        "Citations": ", ".join(kr.get("citations") or []) or "—",
                    }
                )
        else:
            st.subheader("Memory & Knowledge")
            st.caption("No memory context recorded for this execution.")

        llm = detail.get("llm") or {}
        if llm:
            st.subheader("LLM Orchestration")
            tokens = llm.get("usage") or llm.get("token_usage") or {}
            if not isinstance(tokens, dict):
                tokens = {}
            st.write(
                {
                    "Provider": agent_ops_service.display_value(llm.get("provider")),
                    "Model": agent_ops_service.display_value(llm.get("model")),
                    "Prompt size": f"{llm.get('prompt_size_chars') or 0} chars",
                    "Context size": f"{llm.get('context_size_chars') or 0} chars",
                    "Token usage": (
                        f"in={tokens.get('input') or 0} · "
                        f"out={tokens.get('output') or 0} · "
                        f"total={tokens.get('total') or 0}"
                    ),
                    "Latency": f"{float(llm.get('latency_ms') or 0):.2f} ms",
                    "Tool calls": ", ".join(llm.get("tool_calls") or []) or "—",
                    "Retries": llm.get("retries"),
                    "Finish reason": agent_ops_service.display_value(
                        llm.get("finish_reason")
                    ),
                    "Validation": (
                        "OK"
                        if llm.get("validation_ok")
                        else f"Failed: {', '.join(llm.get('validation_errors') or []) or 'unknown'}"
                    ),
                }
            )
        else:
            st.subheader("LLM Orchestration")
            st.caption("No LLM orchestration metadata recorded for this execution.")

        planning = detail.get("planning") or {}
        if planning:
            st.subheader("Planning & Task Graph")
            st.write(
                {
                    "Plan ID": agent_ops_service.display_value(planning.get("plan_id")),
                    "Status": agent_ops_service.display_value(planning.get("status")),
                    "Provider": agent_ops_service.display_value(planning.get("provider")),
                    "Current step": agent_ops_service.display_value(
                        planning.get("current_step")
                    ),
                    "Completed steps": ", ".join(planning.get("completed_steps") or [])
                    or "—",
                    "Blocked steps": ", ".join(planning.get("blocked_steps") or [])
                    or "—",
                    "Parallel branches": ", ".join(
                        planning.get("parallel_branches") or []
                    )
                    or "—",
                    "Resume state": planning.get("resume_state") or {},
                }
            )
            for step in planning.get("steps") or []:
                st.caption(
                    f"{step.get('id')} · {step.get('type')} · {step.get('status')}"
                    + (f" · {step.get('tool')}" if step.get("tool") else "")
                    + (
                        f" · branch={step.get('parallel_group')}"
                        if step.get("parallel_group")
                        else ""
                    )
                )
            timeline = planning.get("timeline") or []
            if timeline:
                st.markdown("**Execution timeline**")
                for item in timeline[-20:]:
                    st.caption(
                        f"{item.get('timestamp') or '—'} — {item.get('label')} "
                        f"({item.get('step_id') or '—'})"
                    )
        else:
            st.subheader("Planning & Task Graph")
            st.caption("No planning metadata recorded for this execution.")

        decision = detail.get("decision") or {}
        if decision:
            st.subheader("Decision Intelligence")
            conf = decision.get("confidence") or {}
            st.write(
                {
                    "Evaluation ID": agent_ops_service.display_value(
                        decision.get("evaluation_id")
                    ),
                    "Status": agent_ops_service.display_value(decision.get("status")),
                    "Strategy": agent_ops_service.display_value(decision.get("strategy")),
                    "Winning action": agent_ops_service.display_value(
                        decision.get("winning_label") or decision.get("winning_action")
                    ),
                    "Require human": "Yes" if decision.get("require_human") else "No",
                    "Confidence": (
                        f"{conf.get('level')} ({conf.get('score')})"
                        if conf
                        else "—"
                    ),
                    "LLM involved": "Yes" if decision.get("llm_involved") else "No",
                    "Duration": f"{float(decision.get('duration_ms') or 0):.2f} ms",
                    "Degraded": "Yes" if decision.get("degraded") else "No",
                    "Policy refs": ", ".join(decision.get("policy_references") or [])
                    or "—",
                    "Memory refs": ", ".join(decision.get("memory_references") or [])
                    or "—",
                    "Knowledge refs": ", ".join(
                        decision.get("knowledge_references") or []
                    )
                    or "—",
                }
            )
            if decision.get("narrative"):
                st.caption(decision["narrative"])
            risks = decision.get("risks") or []
            if risks:
                st.markdown("**Risks**")
                for risk in risks:
                    st.caption(
                        f"{risk.get('category')}: {risk.get('level')} — "
                        f"{risk.get('explanation') or ''}"
                    )
            alts = decision.get("alternatives") or []
            if alts:
                st.markdown("**Alternatives**")
                for alt in alts[:8]:
                    st.caption(
                        f"{alt.get('label') or alt.get('action')} "
                        f"(score={alt.get('total_score')}) — "
                        f"{alt.get('rejection_reason') or ''}"
                    )
            timeline = decision.get("timeline") or []
            if timeline:
                st.markdown("**Decision timeline**")
                for item in timeline[-12:]:
                    st.caption(
                        f"{item.get('timestamp') or '—'} — {item.get('event_type')}"
                    )
            if decision.get("llm_summary"):
                st.markdown("**LLM advisor summary**")
                st.caption(decision["llm_summary"])
        else:
            st.subheader("Decision Intelligence")
            st.caption("No decision evaluation recorded for this execution.")

        workflow = detail.get("workflow") or {}
        if workflow:
            st.subheader("Workflow Execution")
            ckp = workflow.get("checkpoint") or {}
            st.write(
                {
                    "Workflow ID": agent_ops_service.display_value(
                        workflow.get("workflow_id")
                    ),
                    "Plan ID": agent_ops_service.display_value(workflow.get("plan_id")),
                    "Status": agent_ops_service.display_value(workflow.get("status")),
                    "Current step": agent_ops_service.display_value(
                        workflow.get("current_step")
                    ),
                    "Completed": ", ".join(workflow.get("completed_steps") or [])
                    or "—",
                    "Waiting": ", ".join(workflow.get("waiting_steps") or []) or "—",
                    "Failed": ", ".join(workflow.get("failed_steps") or []) or "—",
                    "Parallel branches": ", ".join(
                        workflow.get("parallel_branches") or []
                    )
                    or "—",
                    "Checkpoint": agent_ops_service.display_value(
                        ckp.get("checkpoint_id")
                    ),
                    "Checkpoint version": ckp.get("version"),
                    "Resume": workflow.get("resume_state") or {},
                    "Duration": f"{float(workflow.get('duration_ms') or 0):.2f} ms",
                    "Business refs": workflow.get("business_refs") or {},
                    "Decision action": agent_ops_service.display_value(
                        workflow.get("decision_action")
                    ),
                }
            )
            timeline = workflow.get("timeline") or []
            if timeline:
                st.markdown("**Workflow timeline**")
                for item in timeline[-20:]:
                    st.caption(
                        f"{item.get('timestamp') or '—'} — {item.get('event_type')} "
                        f"({item.get('step_id') or '—'})"
                    )
        else:
            st.subheader("Workflow Execution")
            st.caption("No workflow metadata recorded for this execution.")

        eventbus = detail.get("eventbus") or {}
        if eventbus:
            st.subheader("Event Bus")
            worker = eventbus.get("worker") or {}
            st.write(
                {
                    "Provider": agent_ops_service.display_value(eventbus.get("provider")),
                    "Enabled": "Yes" if eventbus.get("enabled") else "No",
                    "Workers running": worker.get("running"),
                    "Queue size": worker.get("queue_size"),
                    "Dead letters": (eventbus.get("dead_letter_stats") or {}).get(
                        "pending"
                    ),
                    "Subscriptions": len(eventbus.get("subscriptions") or []),
                }
            )
            stream = eventbus.get("live_stream") or []
            if stream:
                st.markdown("**Live event stream**")
                for item in stream[-15:]:
                    st.caption(
                        f"{item.get('timestamp') or '—'} — {item.get('event_type')} "
                        f"({item.get('aggregate_id') or '—'})"
                    )
            dlq = eventbus.get("dead_letters") or []
            if dlq:
                st.markdown("**Dead letters**")
                for item in dlq[:10]:
                    ev = item.get("event") or {}
                    st.caption(
                        f"{item.get('dead_letter_id')} — {ev.get('event_type')} — "
                        f"{item.get('error')}"
                    )
        else:
            st.subheader("Event Bus")
            st.caption("No event bus metadata available.")

        link_cols = st.columns(3)
        with link_cols[0]:
            if detail.get("replenishment_run_id") and st.button(
                "Today's Queue (run)",
                key=f"ops_q_{execution_id}",
            ):
                st.session_state["queue_selected_run_id"] = detail["replenishment_run_id"]
                if detail.get("recommendation_id"):
                    st.session_state["queue_focus_recommendation_id"] = detail[
                        "recommendation_id"
                    ]
                st.switch_page("pages/1_Todays_Queue.py")
        with link_cols[1]:
            if detail.get("recommendation_id") and st.button(
                "Open Recommendation",
                key=f"ops_rec_{execution_id}",
            ):
                st.session_state["queue_focus_recommendation_id"] = detail[
                    "recommendation_id"
                ]
                st.switch_page("pages/1_Todays_Queue.py")

        plan = detail.get("plan")
        if plan:
            st.subheader("Operational Plan")
            st.write({"goal": plan.get("goal")})
            for step in plan.get("steps") or []:
                st.caption(
                    f"{step.get('step_id')} · {step.get('action')} · {step.get('status')}"
                    + (f" · {step.get('tool_name')}" if step.get("tool_name") else "")
                )

        st.subheader("Execution Timeline")
        timeline = detail.get("timeline") or []
        if not timeline:
            st.caption("No timeline events persisted for this execution.")
        else:
            for item in timeline:
                ts = _fmt_ts(item.get("timestamp"))
                # Show time-of-day when possible
                try:
                    raw = item.get("timestamp") or ""
                    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                    ts = dt.astimezone(timezone.utc).strftime("%H:%M:%S")
                except Exception:  # noqa: BLE001
                    pass
                detail_txt = item.get("detail")
                line = f"**{ts}** — {item.get('label')}"
                if detail_txt:
                    line += f"  \n{detail_txt}"
                st.markdown(line)

        st.subheader("Tool History")
        tools = detail.get("tool_history") or []
        if not tools:
            st.caption("No tool calls recorded.")
        for tool in tools:
            with st.expander(
                f"{tool.get('tool_name')} · {tool.get('status')} · "
                f"attempt {tool.get('attempt')} · {tool.get('tool_call_id')}",
                expanded=False,
            ):
                st.write(
                    {
                        "Tool Call ID": tool.get("tool_call_id"),
                        "Status": tool.get("status"),
                        "Attempt": tool.get("attempt"),
                        "Started": _fmt_ts(tool.get("started_at")),
                        "Completed": _fmt_ts(tool.get("completed_at")),
                        "Duration": (
                            f"{tool.get('duration_ms')} ms"
                            if tool.get("duration_ms") is not None
                            else "—"
                        ),
                        "Retryable": "Yes" if tool.get("retryable") else "No",
                        "Error code": agent_ops_service.display_value(
                            tool.get("error_code")
                        ),
                        "Error message": agent_ops_service.display_value(
                            tool.get("error_message")
                        ),
                    }
                )
                st.caption("Sanitized input summary")
                st.json(tool.get("input_summary") or {})
                st.caption("Sanitized output summary")
                st.json(tool.get("output_summary") or {})

        st.subheader("Model Turns")
        turns = detail.get("model_turns") or []
        if not turns:
            st.caption("No model-turn metadata recorded.")
        else:
            for turn in turns:
                st.write(
                    {
                        "Turn": turn.get("turn_id"),
                        "Model": agent_ops_service.display_value(turn.get("model_name")),
                        "Status": turn.get("status"),
                        "Started": _fmt_ts(turn.get("started_at")),
                        "Duration": (
                            f"{turn.get('duration_ms')} ms"
                            if turn.get("duration_ms") is not None
                            else "—"
                        ),
                        "Input Tokens": _token_display(turn.get("input_tokens")),
                        "Output Tokens": _token_display(turn.get("output_tokens")),
                        "Total Tokens": _token_display(turn.get("total_tokens")),
                    }
                )

        hitl = detail.get("hitl") or {}
        if hitl.get("waiting") or detail.get("status") in {
            "waiting_for_human",
            "paused",
        }:
            st.subheader("HITL Status")
            st.write(
                {
                    "Requested action": agent_ops_service.display_value(
                        hitl.get("requested_action")
                    ),
                    "Required role": agent_ops_service.display_value(
                        hitl.get("required_role")
                    ),
                    "Waiting reason": agent_ops_service.display_value(
                        hitl.get("waiting_reason")
                    ),
                    "Approval": agent_ops_service.display_value(hitl.get("approval_id")),
                }
            )

        if detail.get("last_error_code") or detail.get("status") in {
            "failed",
            "retry_pending",
        }:
            st.subheader("Errors / Retry Information")
            st.write(
                {
                    "Failure code": agent_ops_service.display_value(
                        detail.get("last_error_code")
                    ),
                    "Failure message": agent_ops_service.display_value(
                        detail.get("last_error_message")
                    ),
                    "Pending tool": agent_ops_service.display_value(
                        detail.get("pending_tool_name")
                    ),
                    "Attempts": f"{detail.get('attempt_count')}/{detail.get('max_attempts')}",
                }
            )

        st.subheader("Audit Timeline")
        audits = detail.get("audit_events") or []
        if not audits:
            st.caption("No agent audit events for this execution.")
        else:
            for ev in audits:
                st.caption(
                    f"{_fmt_ts(ev.get('timestamp'))} · {ev.get('event_type')} · "
                    f"{agent_ops_service.display_value(ev.get('actor'))}"
                )

        with st.expander("Technical JSON (sanitized)", expanded=False):
            st.json(
                {
                    "context": detail.get("context"),
                    "result": detail.get("result"),
                    "warnings": detail.get("warnings"),
                    "technical": detail.get("technical"),
                }
            )
