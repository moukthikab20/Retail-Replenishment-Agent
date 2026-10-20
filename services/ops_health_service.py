"""Operational dependency health checks for System Health.

Truthful about demo CSV / mock ERP. Feed staleness is also consumed by the
policy engine so status is not merely decorative.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config import (
    AS_OF_DATE,
    DATABASE_URL,
    DATA_DIR,
    INVENTORY_STALE_DAYS,
    OPENAI_MODEL,
    REPLENISHMENT_RUN_INTERVAL_HOURS,
)
from database.connection import database_healthcheck, get_session, init_db, is_sqlite_url
from repositories import csv_repository, recommendation_repository, run_repository
from services import erp_service, forecast_service, policy_service
from integrations.factory import (
    get_inventory_provider,
    get_product_provider,
    get_provider_summary,
    get_sales_provider,
    get_supplier_provider,
    provider_health_checks,
)

STATUS_HEALTHY = "healthy"
STATUS_DEGRADED = "degraded"
STATUS_STALE = "stale"
STATUS_UNAVAILABLE = "unavailable"

# In-process last-success stamps (demo-friendly; reset on process restart).
_LAST_SUCCESS: dict[str, str] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _as_of_dt() -> datetime:
    raw = datetime.fromisoformat(AS_OF_DATE)
    if raw.tzinfo is None:
        return raw.replace(tzinfo=timezone.utc)
    return raw.astimezone(timezone.utc)


def _record_success(component: str, checked_at: str, status: str) -> str | None:
    if status == STATUS_HEALTHY:
        _LAST_SUCCESS[component] = checked_at
    return _LAST_SUCCESS.get(component)


def _check(
    *,
    component: str,
    purpose: str,
    fn: Callable[[], tuple[str, str, dict[str, Any] | None]],
) -> dict[str, Any]:
    started = time.perf_counter()
    checked_at = _iso(_now()) or ""
    try:
        status, message, extras = fn()
    except Exception as exc:  # noqa: BLE001 — surfaced as unavailable
        status, message, extras = STATUS_UNAVAILABLE, str(exc), None
    latency_ms = round((time.perf_counter() - started) * 1000.0, 2)
    last_success = _record_success(component, checked_at, status)
    payload: dict[str, Any] = {
        "component": component,
        "purpose": purpose,
        "checked_at": checked_at,
        "last_success": last_success if status != STATUS_HEALTHY else checked_at,
        "status": status,
        "message": message,
        "latency_ms": latency_ms,
    }
    if extras:
        payload.update(extras)
    return payload


def inventory_feed_watermark(data_dir: Path | None = None) -> datetime | None:
    """Newest inventory updated_at in the demo CSV, if the column exists."""
    _, inventory, _ = csv_repository.get_frames(data_dir)
    if "updated_at" not in inventory.columns or inventory.empty:
        return None
    series = pd_to_datetime_safe(inventory["updated_at"])
    if series is None or series.empty:
        return None
    value = series.max()
    if value is None or (hasattr(value, "year") and int(value.year) < 1971):
        return None
    dt = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    if getattr(dt, "tzinfo", None) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sales_feed_watermark(data_dir: Path | None = None) -> datetime | None:
    _, _, sales = csv_repository.get_frames(data_dir)
    if sales.empty or "date" not in sales.columns:
        return None
    value = sales["date"].max()
    dt = value.to_pydatetime() if hasattr(value, "to_pydatetime") else value
    if getattr(dt, "tzinfo", None) is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def pd_to_datetime_safe(series):
    import pandas as pd

    try:
        return pd.to_datetime(series, errors="coerce").dropna()
    except Exception:  # noqa: BLE001
        return None


def get_feed_freshness(
    *,
    as_of: datetime | None = None,
    inventory_max_age_hours: float | None = None,
    sales_max_age_days: float | None = None,
) -> dict[str, Any]:
    """
    Feed-level freshness for critical demo sources.

    Used by System Health and by the policy engine (stale → blocked).
    """
    ref = as_of or _as_of_dt()
    policy = policy_service.get_active_policy()
    inv_limit = (
        float(inventory_max_age_hours)
        if inventory_max_age_hours is not None
        else float(policy.maximum_inventory_age_hours)
    )
    sales_limit = (
        float(sales_max_age_days)
        if sales_max_age_days is not None
        else float(INVENTORY_STALE_DAYS)
    )

    inv_wm = inventory_feed_watermark()
    if inv_wm is None:
        # Demo inventory.csv has no updated_at — freshness is per-SKU at evaluate time.
        # Feed-level status stays healthy unless a test/ops override marks it stale.
        inv_status = STATUS_HEALTHY
        inv_age_hours = 0.0
        inv_message = (
            "Demo CSV inventory feed is readable; row-level updated_at is not present, "
            "so SKU freshness is enforced by the inventory_freshness policy rule."
        )
    else:
        inv_age_hours = max(0.0, (ref - inv_wm).total_seconds() / 3600.0)
        if inv_age_hours > inv_limit:
            inv_status = STATUS_STALE
            inv_message = (
                f"Inventory feed age {inv_age_hours:.1f}h exceeds "
                f"{inv_limit:.0f}h policy limit (watermark {_iso(inv_wm)})."
            )
        else:
            inv_status = STATUS_HEALTHY
            inv_message = (
                f"Inventory feed age {inv_age_hours:.1f}h within "
                f"{inv_limit:.0f}h limit (Demo CSV)."
            )

    sales_wm = sales_feed_watermark()
    if sales_wm is None:
        sales_status = STATUS_UNAVAILABLE
        sales_age_days = None
        sales_message = "Sales CSV has no usable date watermark."
    else:
        sales_age_days = max(0.0, (ref - sales_wm).total_seconds() / 86400.0)
        if sales_age_days > sales_limit:
            sales_status = STATUS_STALE
            sales_message = (
                f"Sales feed age {sales_age_days:.1f}d exceeds "
                f"{sales_limit:.0f}d limit (watermark {_iso(sales_wm)})."
            )
        else:
            sales_status = STATUS_HEALTHY
            sales_message = (
                f"Sales feed age {sales_age_days:.1f}d within "
                f"{sales_limit:.0f}d limit (Demo CSV)."
            )

    return {
        "as_of": _iso(ref),
        "inventory": {
            "label": "Inventory Data Source — Demo CSV",
            "source_type": "demo_csv",
            "path": str(Path(DATA_DIR) / "inventory.csv"),
            "watermark": _iso(inv_wm),
            "age_hours": inv_age_hours,
            "max_age_hours": inv_limit,
            "status": inv_status,
            "message": inv_message,
            "blocks_recommendations": inv_status in {STATUS_STALE, STATUS_UNAVAILABLE},
        },
        "sales": {
            "label": "Sales Data Source — Demo CSV",
            "source_type": "demo_csv",
            "path": str(Path(DATA_DIR) / "sales.csv"),
            "watermark": _iso(sales_wm),
            "age_days": sales_age_days,
            "max_age_days": sales_limit,
            "status": sales_status,
            "message": sales_message,
            "blocks_recommendations": sales_status in {STATUS_STALE, STATUS_UNAVAILABLE},
        },
        "products": {
            "label": "Product Master — Demo CSV",
            "source_type": "demo_csv",
            "path": str(Path(DATA_DIR) / "products.csv"),
            "status": STATUS_HEALTHY
            if (Path(DATA_DIR) / "products.csv").is_file()
            else STATUS_UNAVAILABLE,
            "message": "Demo product master CSV"
            if (Path(DATA_DIR) / "products.csv").is_file()
            else "products.csv missing",
            "blocks_recommendations": not (Path(DATA_DIR) / "products.csv").is_file(),
        },
    }


def required_sources_blocking_reason(
    *,
    as_of: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return feed-level failures that must block recommendations via policy."""
    freshness = get_feed_freshness(as_of=as_of)
    blocked: list[dict[str, Any]] = []
    for key in ("inventory", "sales", "products"):
        feed = freshness[key]
        if feed.get("blocks_recommendations"):
            blocked.append(
                {
                    "source": key,
                    "rule_name": f"{key}_data_source",
                    "status": feed.get("status"),
                    "message": feed.get("message"),
                    "label": feed.get("label"),
                }
            )
    return blocked


def run_dependency_checks() -> list[dict[str, Any]]:
    """Execute all operational dependency checks."""
    freshness = get_feed_freshness()

    def app_check():
        return (
            STATUS_HEALTHY,
            "Streamlit application process is serving requests.",
            {"source_type": "application"},
        )

    def db_check():
        db = database_healthcheck()
        if not db.get("ok"):
            return (
                STATUS_UNAVAILABLE,
                f"Database connectivity failed: {db.get('error') or 'unknown'}",
                {"dialect": db.get("dialect"), "source_type": "postgresql_or_sqlite"},
            )
        dialect = str(db.get("dialect") or "")
        label = "PostgreSQL" if "postgres" in dialect else dialect or "database"
        # SQLite is fine locally; still truthful.
        msg = f"{label} accepted a connectivity probe."
        if is_sqlite_url(DATABASE_URL):
            msg = "SQLite test/dev database accepted a connectivity probe (not hosted Postgres)."
        return STATUS_HEALTHY, msg, {"dialect": dialect, "source_type": "database"}

    def recommendation_repo_check():
        init_db()
        with get_session() as session:
            # Lightweight repository round-trip.
            _ = recommendation_repository  # noqa: F841
            from sqlalchemy import text

            session.execute(text("SELECT 1"))
            # Touch recommendations table metadata via a bounded list if present.
            try:
                from database.models import RecommendationRow
                from sqlalchemy import select

                session.scalars(select(RecommendationRow.recommendation_id).limit(1)).first()
            except Exception as exc:  # noqa: BLE001
                return STATUS_DEGRADED, f"Recommendations table probe issue: {exc}", None
        return (
            STATUS_HEALTHY,
            "Recommendation repository accepts read queries.",
            {"source_type": "postgres_table"},
        )

    def forecast_check():
        stores = get_product_provider().list_stores()
        if not stores:
            return STATUS_UNAVAILABLE, "No stores available for forecast probe.", None
        store_id = stores[0]["store_id"]
        skus = get_product_provider().list_skus_for_store(store_id)
        if not skus:
            return STATUS_UNAVAILABLE, "No SKUs available for forecast probe.", None
        result = forecast_service.get_demand_forecast(store_id, skus[0])
        sales_health = get_sales_provider().health_check()
        return (
            STATUS_HEALTHY,
            f"Forecast service produced {result.method} for {store_id}/{skus[0]}.",
            {
                "source_type": "deterministic_service",
                "real_external_api": False,
                "sales_provider": sales_health.provider_name,
                "sales_source": sales_health.source,
            },
        )

    def inventory_source_check():
        health = get_inventory_provider().health_check()
        feed = freshness["inventory"]
        status = health.status if health.ok else STATUS_UNAVAILABLE
        if health.ok and feed.get("status") == STATUS_STALE:
            status = STATUS_STALE
        return status, health.message or feed.get("message") or "", {
            "label": f"Inventory — {health.source}",
            "provider_name": health.provider_name,
            "source": health.source,
            "source_type": "provider",
            "feed_age_hours": feed.get("age_hours"),
            "watermark": feed.get("watermark"),
            "real_pos": False,
        }

    def sales_source_check():
        health = get_sales_provider().health_check()
        feed = freshness["sales"]
        status = health.status if health.ok else STATUS_UNAVAILABLE
        if health.ok and feed.get("status") == STATUS_STALE:
            status = STATUS_STALE
        return status, health.message or feed.get("message") or "", {
            "label": f"Sales — {health.source}",
            "provider_name": health.provider_name,
            "source": health.source,
            "source_type": "provider",
            "feed_age_days": feed.get("age_days"),
            "watermark": feed.get("watermark"),
            "real_pos": False,
        }

    def product_provider_check():
        health = get_product_provider().health_check()
        mapped = {
            "healthy": STATUS_HEALTHY,
            "degraded": STATUS_DEGRADED,
            "unavailable": STATUS_UNAVAILABLE,
        }.get(health.status, STATUS_DEGRADED)
        return mapped, health.message, {
            "label": f"Product — {health.source}",
            "provider_name": health.provider_name,
            "source": health.source,
            "real_master": False,
        }

    def supplier_provider_check():
        health = get_supplier_provider().health_check()
        mapped = {
            "healthy": STATUS_HEALTHY,
            "degraded": STATUS_DEGRADED,
            "unavailable": STATUS_UNAVAILABLE,
        }.get(health.status, STATUS_DEGRADED)
        return mapped, health.message, {
            "label": f"Supplier — {health.source}",
            "provider_name": health.provider_name,
            "source": health.source,
            "real_supplier_api": False,
        }

    def openai_check():
        from config import OPENAI_API_KEY

        present = bool(OPENAI_API_KEY and OPENAI_API_KEY.strip())
        model = OPENAI_MODEL or ""
        if not model:
            return STATUS_DEGRADED, "OPENAI_MODEL is not configured.", {
                "api_key_present": present,
                "model_configured": False,
            }
        if not present:
            # Deterministic batch scoring still works without the model.
            return (
                STATUS_DEGRADED,
                "OpenAI API key absent — chat/agent features unavailable; "
                "deterministic scoring continues.",
                {"api_key_present": False, "model_configured": True, "model": model},
            )
        return (
            STATUS_HEALTHY,
            f"OpenAI model '{model}' is configured (key present; not pinged).",
            {"api_key_present": True, "model_configured": True, "model": model},
        )

    def scheduler_check():
        from services import scheduler_service

        health = scheduler_service.get_scheduler_health()
        status = health.get("status") or "degraded"
        # Map taxonomy onto existing health statuses used by the page.
        mapped = {
            "healthy": STATUS_HEALTHY,
            "stale": STATUS_STALE,
            "failed": STATUS_DEGRADED,
            "disabled": STATUS_HEALTHY,  # disabled is intentional, not an outage
        }.get(status, STATUS_DEGRADED)
        # Expose canonical status in details; component status uses mapped rollup.
        return (
            mapped,
            health.get("message") or f"Scheduler status={status}.",
            {
                "scheduler_status": status,
                "enabled": health.get("enabled"),
                "last_scheduled_run": health.get("last_scheduled_run"),
                "last_successful_run": health.get("last_successful_run"),
                "next_scheduled_run": health.get("next_scheduled_run"),
                "expected_interval_hours": health.get("expected_interval_hours"),
                "stale_tolerance_minutes": health.get("stale_tolerance_minutes"),
                "cron": health.get("cron"),
                "timezone": health.get("timezone"),
            },
        )

    def agent_runtime_check():
        from services import agent_ops_service

        runtime = agent_ops_service.get_agent_runtime_health()
        status = runtime.get("status") or STATUS_DEGRADED
        mapped = {
            "healthy": STATUS_HEALTHY,
            "degraded": STATUS_DEGRADED,
            "unavailable": STATUS_UNAVAILABLE,
        }.get(status, STATUS_DEGRADED)
        return (
            mapped,
            runtime.get("message") or f"Agent runtime status={status}.",
            {
                "agent_runtime_status": status,
                "active_executions": runtime.get("active_executions"),
                "waiting_executions": runtime.get("waiting_executions"),
                "failed_recent": runtime.get("failed_recent"),
                "retry_pending": runtime.get("retry_pending"),
                "last_successful_execution": runtime.get("last_successful_execution"),
                "last_failed_execution": runtime.get("last_failed_execution"),
                "thresholds": runtime.get("thresholds"),
            },
        )

    def embedding_provider_check():
        from config import EMBEDDING_PROVIDER, RAG_ENABLED
        from memory.rag.embeddings import get_embedding_provider

        if not RAG_ENABLED:
            return STATUS_DEGRADED, "RAG disabled — embeddings not required.", {
                "rag_enabled": False,
                "provider": EMBEDDING_PROVIDER,
            }
        try:
            provider = get_embedding_provider()
            health = provider.health_check()
            if health.get("ok"):
                return STATUS_HEALTHY, health.get("message") or "Embedding provider healthy.", {
                    "provider": health.get("provider") or EMBEDDING_PROVIDER,
                    "rag_enabled": True,
                }
            return STATUS_DEGRADED, health.get("message") or "Embedding provider degraded.", {
                "provider": EMBEDDING_PROVIDER,
                "rag_enabled": True,
            }
        except Exception as exc:  # noqa: BLE001
            return STATUS_UNAVAILABLE, f"Embedding provider unavailable: {type(exc).__name__}", {
                "provider": EMBEDDING_PROVIDER,
                "rag_enabled": True,
            }

    def vector_store_check():
        from config import RAG_ENABLED
        from memory.rag.vector_store import get_vector_store

        if not RAG_ENABLED:
            return STATUS_DEGRADED, "RAG disabled — vector store idle.", {
                "rag_enabled": False,
            }
        try:
            health = get_vector_store().health_check()
            if health.get("ok"):
                return STATUS_HEALTHY, health.get("message") or "Vector store healthy.", health
            return STATUS_UNAVAILABLE, health.get("message") or "Vector store unavailable.", health
        except Exception as exc:  # noqa: BLE001
            return STATUS_UNAVAILABLE, f"Vector store unavailable: {type(exc).__name__}", {
                "rag_enabled": True,
            }

    def knowledge_retrieval_check():
        from config import RAG_ENABLED
        from memory.rag.embeddings import get_embedding_provider
        from memory.rag.vector_store import get_vector_store

        if not RAG_ENABLED:
            return (
                STATUS_DEGRADED,
                "Semantic knowledge retrieval disabled; structured memory continues.",
                {"rag_enabled": False, "structured_memory": "healthy"},
            )
        try:
            emb = get_embedding_provider().health_check()
            store = get_vector_store().health_check()
            if emb.get("ok") and store.get("ok"):
                return STATUS_HEALTHY, "Knowledge retrieval ready.", {
                    "rag_enabled": True,
                    "embedding_ok": True,
                    "vector_store_ok": True,
                    "structured_memory": "healthy",
                }
            return STATUS_DEGRADED, "Knowledge retrieval degraded; structured memory continues.", {
                "rag_enabled": True,
                "embedding_ok": bool(emb.get("ok")),
                "vector_store_ok": bool(store.get("ok")),
                "structured_memory": "healthy",
            }
        except Exception as exc:  # noqa: BLE001
            return (
                STATUS_DEGRADED,
                f"Knowledge retrieval unavailable ({type(exc).__name__}); structured memory continues.",
                {"rag_enabled": True, "structured_memory": "healthy"},
            )

    def decision_engine_check():
        from config import DECISION_ENABLED
        from decision.factory import decision_health

        if not DECISION_ENABLED:
            return STATUS_DEGRADED, "Decision engine disabled; planner default path continues.", {
                "enabled": False,
            }
        health = decision_health()
        if health.get("ok"):
            return STATUS_HEALTHY, health.get("message") or "Decision engine healthy.", health
        return STATUS_UNAVAILABLE, health.get("message") or "Decision engine unavailable.", health

    def decision_strategy_check():
        from config import DECISION_STRATEGY
        from decision.factory import validate_decision_strategy_configuration

        try:
            key = validate_decision_strategy_configuration()
            return STATUS_HEALTHY, f"Strategy '{key}' ready.", {"strategy": key}
        except Exception as exc:  # noqa: BLE001
            return STATUS_UNAVAILABLE, f"Strategy unavailable: {type(exc).__name__}", {
                "strategy": DECISION_STRATEGY,
            }

    def scoring_engine_check():
        from decision.candidates import generate_candidates
        from decision.context import assemble_decision_context
        from decision.scoring import score_candidate

        try:
            ctx = assemble_decision_context(store_id="ST001", sku="SKU-1001")
            cands = generate_candidates(ctx)
            score_candidate(cands[0], ctx)
            return STATUS_HEALTHY, "Scoring engine ready.", {"dimensions": 10}
        except Exception as exc:  # noqa: BLE001
            return STATUS_DEGRADED, f"Scoring engine degraded: {type(exc).__name__}", {}

    def decision_explainer_check():
        from decision.confidence import compute_confidence
        from decision.contracts import DecisionCandidate
        from decision.context import assemble_decision_context
        from decision.explainer import build_explanation
        from decision.types import DecisionAction

        try:
            ctx = assemble_decision_context(goal="health-check")
            win = DecisionCandidate(
                candidate_id="CAND-HC",
                action=DecisionAction.NO_ACTION,
                label="No Action",
            )
            conf = compute_confidence(ctx, win)
            build_explanation(context=ctx, winning=win, candidates=[win], confidence=conf)
            return STATUS_HEALTHY, "Decision explainer ready.", {}
        except Exception as exc:  # noqa: BLE001
            return STATUS_DEGRADED, f"Explainer degraded: {type(exc).__name__}", {}

    def workflow_engine_check():
        from config import WORKFLOW_ENABLED
        from workflow.factory import workflow_health

        if not WORKFLOW_ENABLED:
            return STATUS_DEGRADED, "Workflow engine disabled; planner path continues.", {
                "enabled": False,
            }
        health = workflow_health()
        if health.get("ok"):
            return STATUS_HEALTHY, health.get("message") or "Workflow engine healthy.", health
        return STATUS_UNAVAILABLE, health.get("message") or "Workflow engine unavailable.", health

    def workflow_checkpoint_store_check():
        from config import WORKFLOW_CHECKPOINTS_ENABLED

        if not WORKFLOW_CHECKPOINTS_ENABLED:
            return STATUS_DEGRADED, "Workflow checkpoints disabled.", {
                "persistence": "disabled",
            }
        return STATUS_HEALTHY, "Checkpoints stored in AgentRunStateRow.state_json.", {
            "persistence": "agent_run_states.state_json",
        }

    def workflow_executor_check():
        try:
            from planner.executor import TaskExecutor
            from workflow.factory import get_workflow_engine

            get_workflow_engine()
            TaskExecutor()
            return STATUS_HEALTHY, "Workflow executor (planner TaskExecutor) ready.", {}
        except Exception as exc:  # noqa: BLE001
            return STATUS_DEGRADED, f"Executor degraded: {type(exc).__name__}", {}

    def resume_engine_check():
        try:
            from planner.resume import ResumeManager

            ResumeManager()
            return STATUS_HEALTHY, "Resume engine ready.", {}
        except Exception as exc:  # noqa: BLE001
            return STATUS_DEGRADED, f"Resume engine degraded: {type(exc).__name__}", {}

    def event_bus_check():
        from config import EVENT_ENABLED
        from eventbus.factory import event_bus_health

        if not EVENT_ENABLED:
            return STATUS_DEGRADED, "Event bus disabled; synchronous paths remain.", {
                "enabled": False,
            }
        health = event_bus_health()
        if health.get("ok"):
            return STATUS_HEALTHY, health.get("message") or "Event bus healthy.", health
        return STATUS_UNAVAILABLE, health.get("message") or "Event bus unavailable.", health

    def event_publisher_check():
        from config import EVENT_ENABLED
        from eventbus.factory import get_event_publisher

        if not EVENT_ENABLED:
            return STATUS_DEGRADED, "Publisher idle (bus disabled).", {}
        try:
            get_event_publisher()
            return STATUS_HEALTHY, "Event publisher ready.", {}
        except Exception as exc:  # noqa: BLE001
            return STATUS_UNAVAILABLE, f"Publisher unavailable: {type(exc).__name__}", {}

    def event_subscribers_check():
        from eventbus.registry import get_registry

        subs = get_registry().list_subscriptions()
        if not subs:
            # Ensure defaults registered
            from eventbus.factory import get_event_bus

            get_event_bus()
            subs = get_registry().list_subscriptions()
        if subs:
            return STATUS_HEALTHY, f"{len(subs)} subscribers registered.", {
                "count": len(subs),
            }
        return STATUS_DEGRADED, "No subscribers registered.", {}

    def event_workers_check():
        from eventbus.factory import get_event_bus

        worker = get_event_bus().worker.health_check()
        if worker.get("ok"):
            return STATUS_HEALTHY, worker.get("message") or "Workers healthy.", worker
        return STATUS_UNAVAILABLE, "Workers unavailable.", worker

    def dead_letter_queue_check():
        from eventbus.dead_letter import get_dead_letter_queue

        stats = get_dead_letter_queue().stats()
        # Pending dead letters are degraded for visibility, not system unavailable.
        if stats.get("pending", 0) > 0:
            return STATUS_DEGRADED, f"{stats['pending']} dead letter(s) pending replay.", stats
        return STATUS_HEALTHY, "Dead letter queue empty.", stats

    def erp_check():
        erp = erp_service.adapter_health()
        if not erp.get("ok", True):
            return (
                STATUS_UNAVAILABLE,
                erp.get("detail") or "ERP adapter unavailable.",
                {
                    "label": f"ERP — {erp.get('source') or erp.get('provider_name') or 'Mock ERP'}",
                    "provider_name": erp.get("provider_name"),
                    "source": erp.get("source") or "Mock ERP",
                    "real_erp": False,
                    "adapter": erp.get("adapter"),
                },
            )
        return (
            STATUS_HEALTHY,
            erp.get("detail")
            or f"{erp.get('provider_name') or 'ERP'} is ready (no live supplier connectivity).",
            {
                "label": f"ERP — {erp.get('source') or 'Mock ERP'}",
                "provider_name": erp.get("provider_name"),
                "source": erp.get("source") or "Mock ERP",
                "real_erp": False,
                "adapter": erp.get("adapter"),
            },
        )

    checks = [
        _check(
            component="application",
            purpose="Serve the Streamlit ops UI and agent session.",
            fn=app_check,
        ),
        _check(
            component="postgresql_database",
            purpose="Persist runs, recommendations, approvals, and orders.",
            fn=db_check,
        ),
        _check(
            component="recommendation_repository",
            purpose="Store and load scored replenishment recommendations.",
            fn=recommendation_repo_check,
        ),
        _check(
            component="forecast_service",
            purpose="Deterministic demand forecast used in scoring.",
            fn=forecast_check,
        ),
        _check(
            component="inventory_master_data",
            purpose="Inventory positions via configured InventoryProvider.",
            fn=inventory_source_check,
        ),
        _check(
            component="sales_data_source",
            purpose="Historical sales via configured SalesProvider.",
            fn=sales_source_check,
        ),
        _check(
            component="product_master_data",
            purpose="Product master via configured ProductProvider.",
            fn=product_provider_check,
        ),
        _check(
            component="supplier_data_source",
            purpose="Supplier / vendor terms via configured SupplierProvider.",
            fn=supplier_provider_check,
        ),
        _check(
            component="openai_model_service",
            purpose="Optional LLM orchestration for analysis chat (not quantity authority).",
            fn=openai_check,
        ),
        _check(
            component="scheduler_last_run",
            purpose="Scheduled/manual replenishment batch execution status.",
            fn=scheduler_check,
        ),
        _check(
            component="agent_runtime",
            purpose="Durable agent execution engine persistence and recent outcomes.",
            fn=agent_runtime_check,
        ),
        _check(
            component="knowledge_retrieval",
            purpose="Semantic knowledge retrieval (fail-soft; structured memory remains).",
            fn=knowledge_retrieval_check,
        ),
        _check(
            component="embedding_provider",
            purpose="Text embedding provider for RAG.",
            fn=embedding_provider_check,
        ),
        _check(
            component="vector_store",
            purpose="Local vector index for semantic search.",
            fn=vector_store_check,
        ),
        _check(
            component="decision_engine",
            purpose="Decision Intelligence candidate evaluation (advisory; fail-soft).",
            fn=decision_engine_check,
        ),
        _check(
            component="decision_strategy",
            purpose="Configured decision selection strategy.",
            fn=decision_strategy_check,
        ),
        _check(
            component="scoring_engine",
            purpose="Decision candidate scoring dimensions.",
            fn=scoring_engine_check,
        ),
        _check(
            component="decision_explainer",
            purpose="Decision explanation / trace assembly.",
            fn=decision_explainer_check,
        ),
        _check(
            component="workflow_engine",
            purpose="Durable workflow coordination over planner plans.",
            fn=workflow_engine_check,
        ),
        _check(
            component="workflow_checkpoint_store",
            purpose="Workflow checkpoints in AgentRunStateRow.state_json.",
            fn=workflow_checkpoint_store_check,
        ),
        _check(
            component="workflow_executor",
            purpose="Step executor (reuses planner TaskExecutor).",
            fn=workflow_executor_check,
        ),
        _check(
            component="resume_engine",
            purpose="Workflow / plan resume after HITL or retry.",
            fn=resume_engine_check,
        ),
        _check(
            component="event_bus",
            purpose="Enterprise event bus (in-process; broker providers later).",
            fn=event_bus_check,
        ),
        _check(
            component="event_publisher",
            purpose="Domain event publisher façade.",
            fn=event_publisher_check,
        ),
        _check(
            component="event_subscribers",
            purpose="Registered event subscribers.",
            fn=event_subscribers_check,
        ),
        _check(
            component="event_workers",
            purpose="In-process event workers.",
            fn=event_workers_check,
        ),
        _check(
            component="dead_letter_queue",
            purpose="Failed event dead letter / replay queue.",
            fn=dead_letter_queue_check,
        ),
        _check(
            component="mock_erp_order_channel",
            purpose="Transmit approved purchase orders via configured ERP adapter.",
            fn=erp_check,
        ),
    ]
    return checks


def _rollup(statuses: list[str]) -> str:
    if STATUS_UNAVAILABLE in statuses:
        return STATUS_UNAVAILABLE
    if STATUS_STALE in statuses:
        return STATUS_STALE
    if STATUS_DEGRADED in statuses:
        return STATUS_DEGRADED
    return STATUS_HEALTHY


def get_operational_health() -> dict[str, Any]:
    """Full operational dependency payload for the System Health page."""
    dependencies = run_dependency_checks()
    freshness = get_feed_freshness()
    overall = _rollup([c["status"] for c in dependencies])
    # Probe-compatible coarse status — scheduler stale/degraded alone must not
    # fail the hosting health check (critical = app + database).
    probe_status = "ok" if overall in {
        STATUS_HEALTHY,
        STATUS_DEGRADED,
        STATUS_STALE,
    } and all(
        c["status"] != STATUS_UNAVAILABLE
        for c in dependencies
        if c["component"] in {"application", "postgresql_database"}
    ) else "degraded"
    # If DB/app unavailable, probe is degraded/fail.
    critical = {
        c["component"]: c["status"]
        for c in dependencies
        if c["component"] in {"application", "postgresql_database"}
    }
    if STATUS_UNAVAILABLE in critical.values():
        probe_status = "degraded"

    try:
        providers = get_provider_summary()
    except Exception:  # noqa: BLE001
        providers = {"selected": {}, "providers": {}}

    inv = (providers.get("providers") or {}).get("inventory") or {}
    sales = (providers.get("providers") or {}).get("sales") or {}
    erp_p = (providers.get("providers") or {}).get("erp") or {}

    return {
        "status": probe_status,
        "overall_status": overall,
        "service": "retail-replenishment-poc",
        "timestamp": _iso(_now()),
        "dependencies": dependencies,
        "data_freshness": freshness,
        "providers": providers,
        "demo": {
            "banner": "Demonstration Environment — sample data — no real supplier orders.",
            "real_erp": False,
            "real_pos": False,
            "inventory_label": f"Inventory — {inv.get('source') or 'Demo CSV'}",
            "sales_label": f"Sales — {sales.get('source') or 'Demo CSV'}",
            "erp_label": f"ERP — {erp_p.get('source') or 'Mock ERP'}",
        },
    }
