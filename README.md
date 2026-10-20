# Retail Replenishment Agent — Multi-user Demo

Single-agent Streamlit application for Infolob Solutions. Deterministic Python services own forecasting, replenishment math, risk, human override validation, approval policy, and mock purchase orders. The language model coordinates tools and explains results — it does not invent business values.

> **Demonstration Environment — sample data — no real supplier orders.**

## Architecture

```
Agent Tool → Business Service → Provider Interface → Configured Adapter
```

External data access goes through `integrations/` providers. This deployment supports:

| Domain | Env var | Supported value |
|--------|---------|-----------------|
| Inventory | `INVENTORY_PROVIDER` | `csv` |
| Sales | `SALES_PROVIDER` | `csv` |
| Product | `PRODUCT_PROVIDER` | `csv` |
| Supplier | `SUPPLIER_PROVIDER` | `demo` |
| ERP | `ERP_PROVIDER` (alias `ERP_ADAPTER`) | `mock` |

Unknown provider values fail fast. SAP/Oracle/POS adapters are **not** available in this deployment.

```
retail-replenishment-poc/
├── app.py
├── pages/
├── agent/
├── planner/
├── decision/
├── workflow/
├── eventbus/              # Enterprise Event Bus (in-process; broker-ready)
├── memory/
├── llm/
├── services/
├── integrations/          # provider contracts + CSV/demo/mock adapters
├── repositories/
├── models/
├── database/
├── alembic/
├── scripts/
├── tests/
├── data/
├── health.py
├── render.yaml
├── DEPLOYMENT.md
├── styles.py
├── config.py
├── .env.example
└── requirements.txt
```

## Quantity separation

| Field | Meaning |
|-------|---------|
| `agent_recommended_quantity` | Deterministic recommendation (never overwritten by humans) |
| `human_proposed_quantity` | Quantity submitted on Review |
| `approved_final_quantity` | Quantity set only by formal approval |

## Workflow

1. Sign in with demo access code + named user/role
2. **Analysis** — store/SKU, forecast, agent recommendation
3. **Review** — accept or override quantity, submit for approval
4. Formal role-gated approve/reject → mock purchase order

## Local quick start

```powershell
cd retail-replenishment-poc
pip install -r requirements.txt
copy .env.example .env
# Optional: OPENAI_API_KEY, OPENAI_MODEL, DEMO_ACCESS_CODE

streamlit run app.py
```

Development login default access code (when `DEMO_ACCESS_CODE` is empty): `infolob-demo`

End-to-end customer demo story (roles, screens, scenarios A–F): see [DEMO_WALKTHROUGH.md](DEMO_WALKTHROUGH.md).  
Optional prep: `python scripts/prepare_customer_demo.py`.

Without `OPENAI_API_KEY`, analysis uses the deterministic service pipeline and still persists recommendations.

## Authentication & RBAC

This deployment uses a pluggable **authentication provider** with signed application sessions.

| Variable | Purpose |
|----------|---------|
| `AUTH_PROVIDER` | `demo` only (unknown values fail fast; OIDC not implemented yet) |
| `SESSION_TTL_MINUTES` | Application session lifetime (default `480`) |
| `SESSION_SECRET` | HMAC key for session tokens (dev default when empty) |
| `DEMO_ACCESS_CODE` | Demo gate — only when `AUTH_PROVIDER=demo` |
| `OIDC_*` | Placeholders for a future OIDC provider (unused) |

**Demo vs production auth:** `AUTH_PROVIDER=demo` uses `DemoAuthenticationProvider` (named `DEMO_USERS` workspace selection — no access code). Any other provider value is rejected.

**Session lifecycle:** Login issues an opaque signed token (`session_id.hmac`). Streamlit stores only the token; identity and roles are revalidated from the server session store on every protected request. Logout revokes the session. Expired/forged tokens are rejected.

**Roles (unchanged hierarchy):** `viewer` < `store_manager` < `inventory_planner` < `category_manager` < `administrator`.

**Permissions:** Explicit permission catalog in `integrations/auth/permissions.py`. Analysis, HITL resume, Agent Operations, and Administration enforce authorization in services — not UI alone.

## Environment

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Enables live Agents SDK runs |
| `OPENAI_MODEL` | Model name (default `gpt-4o-mini` when unset) |
| `DATABASE_URL` | SQLite locally; Postgres on Render |
| `APP_ENV` | `development` / `production` |
| `AUTH_PROVIDER` | Authentication provider (`demo` only today) |
| `MEMORY_PROVIDER` | Memory/knowledge provider (`database` \| `mock`; unknown fails fast) |
| `MEMORY_RETRIEVAL_DEFAULT_LIMIT` | Default retrieval page size (default `10`) |
| `MEMORY_RETRIEVAL_MAX_LIMIT` | Hard cap on retrieval limit (default `50`) |
| `RAG_ENABLED` | Enable semantic knowledge retrieval (default `true`; fail-soft when off/unavailable) |
| `EMBEDDING_PROVIDER` | Embedding provider (`mock` \| `openai`; unknown fails fast) |
| `RAG_MAX_RESULTS` | Max semantic hits after policy (default `5`) |
| `RAG_MAX_CONTEXT_CHARS` | Cap on retrieved knowledge text size (default `4000`) |
| `RAG_MIN_SCORE` | Minimum similarity score (default `0.15`) |
| `LLM_PROVIDER` | LLM orchestration provider (`mock` \| `openai`; unknown fails fast) |
| `LLM_MODEL` | Model id (defaults to `OPENAI_MODEL` / `gpt-4o-mini`) |
| `LLM_TIMEOUT` | Provider timeout seconds (default `60`) |
| `LLM_MAX_TOKENS` | Max completion tokens (default `4096`) |
| `LLM_TEMPERATURE` | Sampling temperature (default `0.0`) |
| `LLM_ENABLE_TOOL_CALLS` | Allow registered tool calls in orchestration (default `true`) |
| `PLANNER_PROVIDER` | Planning provider (`mock` \| `rules`; unknown fails fast) |
| `PLANNER_MAX_PARALLEL` | Max parallel ready steps (default `4`) |
| `PLANNER_MAX_DEPTH` | Max steps per plan (default `16`) |
| `PLANNER_ENABLE_PARALLEL` | Enable fan-out parallel branches (default `true`) |
| `DECISION_ENABLED` | Enable Decision Intelligence evaluation (default `true`) |
| `DECISION_STRATEGY` | `balanced` \| `lowest_risk` \| `lowest_cost` \| `fastest_delivery` \| `business_policy_first` \| `mock` |
| `DECISION_LLM_ADVISOR` | Optional LLM summary of candidates (default `false`; never overrides policy) |
| `DECISION_CONFIDENCE_FLOOR` | Escalate when confidence below this (default `0.45`) |
| `DECISION_RISK_CEILING` | Escalate when max risk at/above this (default `0.75`) |
| `WORKFLOW_ENABLED` | Enable workflow coordination layer (default `true`) |
| `WORKFLOW_MAX_PARALLEL` | Max parallel ready steps (default `4`) |
| `WORKFLOW_DEFAULT_TIMEOUT_SECONDS` | Default step/workflow timeout hint (default `120`) |
| `WORKFLOW_RETRY_LIMIT` | Max technical retries (default `3`) |
| `WORKFLOW_CHECKPOINTS_ENABLED` | Persist checkpoints in execution state_json (default `true`) |
| `WORKFLOW_COMPENSATION_ENABLED` | Allow explicit compensation metadata path (default `false`) |
| `EVENT_ENABLED` | Enable Enterprise Event Bus (default `true`) |
| `EVENT_PROVIDER` | `in_process` \| `mock` (unknown fails fast; Kafka/SQS not implemented) |
| `EVENT_RETRY_LIMIT` | Handler retry attempts (default `3`) |
| `EVENT_MAX_WORKERS` | In-process worker threads (default `2`) |
| `EVENT_ORDERING` | Ordered dispatch per aggregate (default `true`) |
| `EVENT_DEAD_LETTER` | Persist failed events for replay (default `true`) |
| `EVENT_SYNC_DISPATCH` | Force sync dispatch (default `false`; tests use `true`) |
| `SESSION_TTL_MINUTES` | Signed session TTL |
| `SESSION_SECRET` | Session HMAC secret |
| `DEMO_ACCESS_CODE` | Shared demo gate (demo provider only) |
| `TRACE_SENSITIVE_DATA` | Keep `false` |
| `MAX_AGENT_RUNS_PER_USER_PER_HOUR` | Shared-demo rate limit |
| `RATE_LIMIT_WINDOW_MINUTES` | Rate-limit window |
| `REPLENISHMENT_SCHEDULE_ENABLED` | Enable/disable scheduled CLI/cron triggers |
| `REPLENISHMENT_CRON` | Cron expression (default `0 */6 * * *`) |
| `REPLENISHMENT_TIMEZONE` | Timezone for schedule buckets (default `UTC`) |

## Scheduled replenishment

Batch scoring is **OpenAI-independent** and never starts from Streamlit page loads.

```powershell
# One-shot scheduled job simulation
python -m jobs.run_replenishment

# Inspect schedule / last run (no batch)
python -m jobs.run_replenishment --status-only
```

Default: every 6 hours (`0 */6 * * *`) in `REPLENISHMENT_TIMEZONE`. Render Blueprint includes a separate Cron Job sharing the same Postgres `DATABASE_URL`. See **DEPLOYMENT.md §8**.

## Semantic retrieval (RAG)

Extends the existing **Memory & Knowledge Engine** (`memory/rag/`). Structured SQL memory remains authoritative for recommendation IDs, approvals, executions, store/SKU/supplier history, and ERP outcomes. Semantic retrieval adds policies, SOPs, supplier notes, operations guides, and similar narrative cases.

| Concern | Behavior |
|---------|----------|
| Ingestion | `ingest_knowledge` → deterministic chunks → embed → local vector upsert + SQL metadata |
| Embeddings | `EMBEDDING_PROVIDER=mock` (default) or `openai` (requires `OPENAI_API_KEY`) |
| Vector store | Local/in-process + SQL `embedding_json` mirror; **not** pgvector / Azure AI Search / Pinecone yet |
| Hybrid search | Structured exact matches + semantic similarity; exact lookup is never replaced |
| Citations | Source references retained (e.g. `[Policy POL-004]`); never fabricated |
| Access control | `access_scope` filtered by role **before** LLM context |
| Injection defense | Retrieved text is untrusted **user** content (`RETRIEVED KNOWLEDGE`); cannot change RBAC, tools, approvals, or system instructions |
| Fail-soft | Embedding/vector outages degrade RAG only; structured memory and replenishment continue |

Demo corpus (`seed_demo_knowledge`) is for tests/demos only — not production policy authority.

## Decision Intelligence

```text
Agent Runtime
    → Planner (task graph)
    → Decision Engine (candidates + scores + strategy)
    → LLM (optional advisor only)
    → Business Services (authoritative execution)
```

Runtime → Planner → **Decision Engine** → LLM (advisor) → Business Services.

The Decision Engine (`decision/`) evaluates typed candidates (create PO, escalate, delay, wait for human, etc.) using policy, inventory, supplier, ERP, memory, and semantic knowledge signals. It **recommends** only — it does not approve orders, change RBAC, or transmit ERP.

| Concern | Behavior |
|---------|----------|
| Scoring | Policy compliance, inventory risk, supplier reliability, cost, lead time, forecast confidence, complexity, history, ERP risk, human-approval impact |
| Strategies | `DECISION_STRATEGY` — unknown values fail fast |
| Policy precedence | Hard business rules win before LLM advice |
| Confidence / risk | Computed from evidence; missing data lowers confidence (never fabricated) |
| Human escalation | Low confidence or high risk → require human |
| Fail-soft | Scoring failure → planner continues; LLM outage does not block decisions |

## Workflow Execution

```text
Runtime → Planner → Decision Engine → Workflow Engine → Controlled Tools → Business Services
```

The Workflow Engine (`workflow/`) coordinates durable execution of planner Plans. It **reuses** `TaskExecutor`, HITL pause/resume, tool registry auth, and ERP lifecycle services. Checkpoints are stored in existing `AgentRunStateRow.state_json` (`workflow_ops` + `plan_snapshot`) — no parallel workflow tables.

| Concern | Behavior |
|---------|----------|
| Lifecycle | created → running → waiting/retry → completed/failed/cancelled |
| Checkpoint / resume | Survives restart; completed non-replayable steps are not re-run |
| Retry | Technical failures only; business rejection never auto-retries |
| Compensation | Explicit/service-backed only; ERP acknowledged orders are not rolled back |
| Authorization | Server-side tool registry gates; LLM/RAG cannot bypass |
| Decision integration | Advisory only — mutations still require business/approval paths |

## Enterprise Event Bus

```text
Runtime → Planner → Decision → Workflow → Event Bus → Business Services → Distributed Workers
```

The Event Bus (`eventbus/`) is the communication backbone. Business services remain authoritative for mutations; they **publish** typed events and do not know subscribers. Delivery today is **in-process** (async workers + sync fail-soft fallback). Kafka / RabbitMQ / Azure Service Bus / AWS SQS are architected for later — not deployed.

| Concern | Behavior |
|---------|----------|
| Contracts | `EventEnvelope` — event_id, type, aggregate, correlation/causation, payload, metadata |
| Standard events | Recommendations, workflow lifecycle, ERP queue/submit/ack/reject, human approval, notifications, inventory/policy |
| Routing | Event type → many registered handlers (memory, notifications, workflow resume, ERP signals, Agent Ops, audit, health) |
| Guarantees | At-least-once; idempotent handlers; duplicate detection; ordered processing per aggregate |
| Retries | Fixed or exponential; exhausted failures → dead letter queue |
| Dead letters | In-memory DLQ with replay; pending DLQ is Degraded, not system Unavailable |
| Workflow / ERP / HITL | Workflow publishes step/waiting/completed; ERP ack and human approval publish events that request workflow resume |
| Memory | Subscribes to business events and records breadcrumbs (no redesign of Memory Engine) |
| Fail-soft | Bus down or disabled → sync fallback / skip publish; no business mutation is lost |
| Agent Ops / Health | Live stream, subscriptions, DLQ, retry/worker health; Health checks for bus, publisher, subscribers, workers, DLQ |

Demo: `python scripts/demo_event_bus.py`

## Order lifecycle & ERP

Approved recommendations create an **OrderIntent** in `queued_for_erp`. That is **not** an ERP acknowledgement.

```
Approval / Auto-release → OrderIntent (queued_for_erp) → explicit transmit → ERP ack → completed
```

- **QUEUE ≠ TRANSMIT:** approval and auto-release only enqueue. Set `ERP_AUTO_TRANSMIT=false` (default).
- **Transmit:** `order_lifecycle_service.transmit_order_intent` → configured `ERPAdapter` (Mock today).
- **Statuses:** Queued for ERP → Transmitting → ERP Acknowledged → Completed; failures → Transmission Failed / Retry Pending; business reject → ERP Rejected; cancel only while queued.
- **Idempotency:** `erp-order:{order_intent_id}` prevents duplicate external orders.
- **Mock scenarios:** `ERP_MOCK_SCENARIO` or per-call `mock_scenario` (`success`, `temporary_failure`, `business_rejection`, `timeout`).
- Live SAP/Oracle are **not** connected.

## Tests

```powershell
python -m pytest tests -q
```

## Hosted deployment

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for GitHub → Render web service + PostgreSQL + Cron Job, migrations, seeding, and custom domains.

Health probe: `/Health`

© 2026 Infolob Solutions · Confidential
