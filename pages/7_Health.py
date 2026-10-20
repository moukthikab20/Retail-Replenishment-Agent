"""System Health — operational dependency and data-freshness status."""

from __future__ import annotations

from html import escape

import streamlit as st

from health import check_health
from services import scheduler_service
from ui_common import bootstrap_app
from ui_components import page_heading, panel_title, status_pill


def _kind(status: str | None) -> str:
    return {
        "healthy": "ok",
        "degraded": "warn",
        "stale": "warn",
        "failed": "danger",
        "disabled": "neutral",
        "unavailable": "danger",
        "ok": "ok",
    }.get((status or "").lower(), "neutral")


def _label(status: str | None) -> str:
    raw = (status or "unknown").replace("_", " ")
    return raw[:1].upper() + raw[1:]


def main() -> None:
    bootstrap_app(
        "System Health | Retail Replenishment Agent",
        require_auth=False,
        active_nav="health",
    )
    page_heading(
        "System Health",
        "Operational dependencies and demo data freshness — not live POS/ERP.",
    )

    payload = check_health()
    overall = payload.get("overall_status") or payload.get("status")
    freshness = payload.get("data_freshness") or {}
    demo = payload.get("demo") or {}
    sched = scheduler_service.get_scheduler_health()

    with st.container(border=True):
        panel_title("Overall status")
        st.markdown(
            status_pill(_kind(str(overall)), _label(str(overall))),
            unsafe_allow_html=True,
        )

    with st.container(border=True):
        panel_title("Scheduler")
        st.markdown(
            status_pill(_kind(str(sched.get("status"))), _label(str(sched.get("status")))),
            unsafe_allow_html=True,
        )
        st.caption(sched.get("message") or "")
        last_sched = sched.get("last_scheduled_run") or {}
        last_ok = sched.get("last_successful_run") or {}
        st.write(
            {
                "Enabled": bool(sched.get("enabled")),
                "Last scheduled run": last_sched.get("run_id") or "—",
                "Last scheduled status": last_sched.get("status") or "—",
                "Last successful run": last_ok.get("run_id") or "—",
                "Next expected run": sched.get("next_scheduled_run_display") or "—",
                "Cron": sched.get("cron"),
                "Timezone": sched.get("timezone"),
                "Stale tolerance (min)": sched.get("stale_tolerance_minutes"),
            }
        )
        st.caption(demo.get("banner") or "")
        st.caption(
            f"Checked at {payload.get('timestamp') or '—'} · "
            f"Environment {payload.get('app_env') or '—'}"
        )

    providers = payload.get("providers") or {}
    provider_rows = (providers.get("providers") or {})
    with st.container(border=True):
        panel_title("Data Sources", hint="Configured integration providers")
        if not provider_rows:
            st.info("Provider summary unavailable.")
        else:
            order = [
                ("inventory", "Inventory"),
                ("sales", "Sales"),
                ("product", "Product"),
                ("supplier", "Supplier"),
                ("erp", "ERP"),
            ]
            header = (
                "<div class='il-queue-table il-health-table'>"
                "<div class='il-queue-head'>"
                "<div>Source</div><div>Provider</div><div>Status</div><div>Notes</div>"
                "</div>"
            )
            parts = [header]
            for key, label in order:
                row = provider_rows.get(key) or {}
                parts.append(
                    "<div class='il-queue-row'>"
                    f"<div>{escape(label)}</div>"
                    f"<div>{escape(str(row.get('provider_name') or row.get('config') or '—'))}"
                    f"<div class='il-health-sub'>{escape(str(row.get('source') or ''))}</div></div>"
                    f"<div>{status_pill(_kind(str(row.get('status'))), _label(str(row.get('status'))))}</div>"
                    f"<div>{escape(str(row.get('message') or ''))}</div>"
                    "</div>"
                )
            parts.append("</div>")
            st.markdown("".join(parts), unsafe_allow_html=True)
            st.caption("Provider selection is environment-configured; the UI does not change it.")

    auth = payload.get("authentication") or {}
    with st.container(border=True):
        panel_title("Authentication", hint="Provider + application sessions")
        st.markdown(
            status_pill(_kind(str(auth.get("status"))), _label(str(auth.get("status")))),
            unsafe_allow_html=True,
        )
        st.caption(auth.get("message") or "")
        sessions = auth.get("sessions") or {}
        st.write(
            {
                "Provider": auth.get("provider_name") or auth.get("config") or "—",
                "Source": auth.get("source") or "—",
                "Session TTL (minutes)": sessions.get("ttl_minutes") or "—",
                "Active sessions (this process)": sessions.get("active_sessions"),
            }
        )
        st.caption(
            "OIDC/Entra/Okta are not connected in this deployment. "
            "Demo access codes never appear in health payloads."
        )

    agent_dep = next(
        (d for d in (payload.get("dependencies") or []) if d.get("component") == "agent_runtime"),
        None,
    )
    with st.container(border=True):
        panel_title("Agent Runtime", hint="Durable execution engine")
        if agent_dep is None:
            st.info("Agent runtime probe unavailable.")
        else:
            st.markdown(
                status_pill(
                    _kind(str(agent_dep.get("status"))),
                    _label(str(agent_dep.get("status"))),
                ),
                unsafe_allow_html=True,
            )
            st.caption(agent_dep.get("message") or "")
            last_success = agent_dep.get("last_successful_execution") or {}
            last_failed = agent_dep.get("last_failed_execution") or {}
            st.write(
                {
                    "Active executions": agent_dep.get("active_executions"),
                    "Waiting executions": agent_dep.get("waiting_executions"),
                    "Failed (recent window)": agent_dep.get("failed_recent"),
                    "Retry pending": agent_dep.get("retry_pending"),
                    "Last successful execution": last_success.get("execution_id") or "—",
                    "Last failed execution": last_failed.get("execution_id") or "—",
                    "Thresholds": agent_dep.get("thresholds") or {},
                }
            )

    erp_panel = payload.get("erp") or {}
    order_lc = erp_panel.get("order_lifecycle") or {}
    with st.container(border=True):
        panel_title("ERP order pipeline", hint="Order-level counts — separate from provider health")
        st.markdown(
            status_pill(
                _kind("healthy" if erp_panel.get("ok") else "unavailable"),
                _label("healthy" if erp_panel.get("ok") else "unavailable"),
            ),
            unsafe_allow_html=True,
        )
        st.write(
            {
                "Provider": erp_panel.get("label") or erp_panel.get("provider_name") or "—",
                "Queued for ERP": order_lc.get("queued_for_erp", 0),
                "Transmission failures": order_lc.get("transmission_failed", 0),
                "Retry pending": order_lc.get("retry_pending", 0),
                "ERP rejections": order_lc.get("erp_rejected", 0),
                "Oldest queued order": order_lc.get("oldest_queued_order_at") or "—",
            }
        )
        st.caption(
            "Provider availability is independent of individual order rejections. "
            "QUEUE ≠ TRANSMIT — orders enqueue without auto-sending to ERP."
        )

    with st.container(border=True):
        panel_title("Data freshness", hint="Critical source feeds")
        feeds = [
            freshness.get("inventory") or {},
            freshness.get("sales") or {},
            freshness.get("products") or {},
        ]
        header = (
            "<div class='il-queue-table il-health-table'>"
            "<div class='il-queue-head'>"
            "<div>Source</div><div>Age</div><div>Status</div><div>Notes</div>"
            "</div>"
        )
        parts = [header]
        for feed in feeds:
            if not feed:
                continue
            age = (
                f"{feed.get('age_hours'):.1f}h"
                if feed.get("age_hours") is not None
                else (
                    f"{feed.get('age_days'):.1f}d"
                    if feed.get("age_days") is not None
                    else "—"
                )
            )
            status = feed.get("status") or "unknown"
            parts.append(
                "<div class='il-queue-row'>"
                f"<div>{escape(str(feed.get('label') or 'Source'))}</div>"
                f"<div>{escape(age)}</div>"
                f"<div>{status_pill(_kind(str(status)), _label(str(status)))}</div>"
                f"<div>{escape(str(feed.get('message') or ''))}</div>"
                "</div>"
            )
        parts.append("</div>")
        st.markdown("".join(parts), unsafe_allow_html=True)
        st.caption(
            "Stale required feeds block recommendations through the policy engine. "
            "This demo does not claim live POS or supplier ERP connectivity."
        )

    with st.container(border=True):
        panel_title("Dependencies", hint="Component probes")
        deps = payload.get("dependencies") or []
        if not deps:
            st.info("No dependency checks available.")
        else:
            dheader = (
                "<div class='il-queue-table il-health-deps'>"
                "<div class='il-queue-head'>"
                "<div>Component</div><div>Purpose</div><div>Status</div>"
                "<div>Latency</div><div>Message</div>"
                "</div>"
            )
            dparts = [dheader]
            for dep in deps:
                latency = dep.get("latency_ms")
                latency_s = f"{latency:.0f} ms" if latency is not None else "—"
                status = dep.get("status") or "unknown"
                dparts.append(
                    "<div class='il-queue-row'>"
                    f"<div><strong>{escape(str(dep.get('component')))}</strong>"
                    f"<div class='il-health-sub'>last ok: "
                    f"{escape(str(dep.get('last_success') or '—'))}</div></div>"
                    f"<div>{escape(str(dep.get('purpose') or ''))}</div>"
                    f"<div>{status_pill(_kind(str(status)), _label(str(status)))}</div>"
                    f"<div>{escape(latency_s)}</div>"
                    f"<div>{escape(str(dep.get('message') or ''))}</div>"
                    "</div>"
                )
            dparts.append("</div>")
            st.markdown("".join(dparts), unsafe_allow_html=True)

    with st.expander("Technical details", expanded=False):
        st.json(
            {
                "status": payload.get("status"),
                "overall_status": payload.get("overall_status"),
                "database": payload.get("database"),
                "openai": payload.get("openai"),
                "authentication": payload.get("authentication"),
                "erp": payload.get("erp"),
                "batch_schedule": payload.get("batch_schedule"),
                "demo": payload.get("demo"),
            }
        )


main()
