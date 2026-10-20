# Deployment Guide — Retail Replenishment Demo

This guide covers hosting the multi-user Streamlit demo on **Render** with **PostgreSQL**, using GitHub as the source repository.

> Demonstration Environment — sample data — no real supplier orders.

---

## 1. Prerequisites

- GitHub account and a repository containing this project
- Render account
- OpenAI API key (optional for deterministic fallback; required for live Agents SDK runs)
- A shared `DEMO_ACCESS_CODE` for invitees

---

## 2. Push to GitHub

```powershell
cd retail-replenishment-poc
git status
git push -u origin proper-agent-development
```

Ensure secrets are **not** committed:

- `.env`
- `.streamlit/secrets.toml`
- local `*.db` files

Use `.env.example` as the template only.

---

## 3. Create a Render PostgreSQL database

1. In the Render Dashboard → **New** → **PostgreSQL**
2. Name it e.g. `retail-replenishment-db`
3. Choose a region close to your web service
4. Create the database and copy the **Internal Database URL** (preferred for services in the same account) or External URL if needed

Render connection strings often look like:

```text
postgres://user:password@host/dbname
```

The application normalizes these to SQLAlchemy’s `postgresql+psycopg://…` driver automatically.

---

## 4. Deploy the web service (Blueprint)

### Option A — Blueprint (`render.yaml`)

1. Render Dashboard → **New** → **Blueprint**
2. Connect the GitHub repository
3. Select branch `proper-agent-development` (or update `render.yaml` `branch`)
4. Apply the Blueprint

The Blueprint defines:

- PostgreSQL database `retail-replenishment-db`
- Web service `retail-replenishment-poc`
- Build: `pip install -r requirements.txt`
- Pre-deploy: `alembic upgrade head` + idempotent seed
- Start command:

```bash
streamlit run app.py --server.address 0.0.0.0 --server.port $PORT --server.headless true
```

- Health check path: `/Health`

### Option B — Manual web service

1. **New** → **Web Service** → connect repo
2. Runtime: Python
3. Build command: `pip install -r requirements.txt`
4. Pre-deploy command: `python -m alembic upgrade head && python scripts/seed_demo_data.py`
5. Start command (exact):

```bash
streamlit run app.py --server.address 0.0.0.0 --server.port $PORT --server.headless true
```

6. Health check path: `/Health`
7. Link the PostgreSQL instance and map `DATABASE_URL`

---

## 5. Environment variables

Set these in the Render web service **Environment** tab (never in client-side Streamlit widgets):

| Variable | Required | Notes |
|----------|----------|-------|
| `DATABASE_URL` | Yes (hosted) | From Render Postgres `connectionString` |
| `APP_ENV` | Yes | Use `production` on Render |
| `AUTH_PROVIDER` | Optional | `demo` only; unknown values fail fast |
| `SESSION_TTL_MINUTES` | Optional | Application session TTL (default `480`) |
| `SESSION_SECRET` | Recommended (hosted) | HMAC secret for signed sessions |
| `DEMO_ACCESS_CODE` | Yes (hosted) | Shared demo gate when `AUTH_PROVIDER=demo`; do not commit |
| `OIDC_ISSUER` / `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` / `OIDC_REDIRECT_URI` | Optional | Placeholders only — OIDC not implemented |
| `OPENAI_API_KEY` | Optional | Enables live agent runs |
| `OPENAI_MODEL` | Optional | Defaults to `gpt-4o-mini` when unset |
| `TRACE_SENSITIVE_DATA` | Optional | Keep `false` |
| `MAX_AGENT_RUNS_PER_USER_PER_HOUR` | Optional | Default `20` |
| `RATE_LIMIT_WINDOW_MINUTES` | Optional | Default `60` |
| `CRON_SECRET` | Recommended (hosted) | Shared secret for scheduled batch CLI; sync:false in Blueprint |
| `REPLENISHMENT_SCHEDULE_ENABLED` | Optional | Master switch for scheduled triggers (default `true`) |
| `REPLENISHMENT_CRON` | Optional | Cron expression (default `0 */6 * * *`) |
| `REPLENISHMENT_TIMEZONE` | Optional | Timezone for cron/buckets (default `UTC`) |
| `REPLENISHMENT_STALE_TOLERANCE_MINUTES` | Optional | Stale health grace (default `90`) |
| `BATCH_SCHEDULE_CRON` | Optional | Legacy alias for `REPLENISHMENT_CRON` |
| `BATCH_SCHEDULE_TIMEZONE` | Optional | Legacy alias for `REPLENISHMENT_TIMEZONE` |
| `ERP_ADAPTER` | Optional | Legacy alias for `ERP_PROVIDER` (default `mock`) |
| `ERP_PROVIDER` | Optional | ERP adapter key (default `mock`; unknown values fail fast) |
| `ERP_AUTO_TRANSMIT` | Optional | Keep `false` — queue ≠ transmit |
| `ERP_MAX_RETRY_ATTEMPTS` | Optional | Bounded technical retries (default `3`) |
| `ERP_RETRY_DELAY_SECONDS` | Optional | Delay metadata for retry_pending (default `60`) |
| `ERP_MOCK_SCENARIO` | Optional | `success` / `temporary_failure` / `business_rejection` / `timeout` |
| `INVENTORY_PROVIDER` | Optional | `csv` only in this deployment |
| `SALES_PROVIDER` | Optional | `csv` only in this deployment |
| `PRODUCT_PROVIDER` | Optional | `csv` only in this deployment |
| `SUPPLIER_PROVIDER` | Optional | `demo` only in this deployment |
| `MEMORY_PROVIDER` | Optional | `database` \| `mock` (unknown fails fast) |
| `RAG_ENABLED` | Optional | Semantic knowledge retrieval (default `true`) |
| `EMBEDDING_PROVIDER` | Optional | `mock` \| `openai` (unknown fails fast; OpenAI needs `OPENAI_API_KEY`) |
| `RAG_MAX_RESULTS` | Optional | Max semantic hits (default `5`) |
| `RAG_MAX_CONTEXT_CHARS` | Optional | Retrieved knowledge size cap (default `4000`) |
| `RAG_MIN_SCORE` | Optional | Minimum similarity score (default `0.15`) |
| `LLM_PROVIDER` | Optional | `mock` \| `openai` |
| `PLANNER_PROVIDER` | Optional | `mock` \| `rules` |
| `DECISION_ENABLED` | Optional | Decision Intelligence layer (default `true`) |
| `DECISION_STRATEGY` | Optional | `balanced` (default) \| `lowest_risk` \| `lowest_cost` \| `fastest_delivery` \| `business_policy_first` \| `mock` |
| `DECISION_LLM_ADVISOR` | Optional | LLM may summarize candidates only (default `false`) |
| `DECISION_CONFIDENCE_FLOOR` | Optional | Escalate below this confidence (default `0.45`) |
| `DECISION_RISK_CEILING` | Optional | Escalate at/above this risk (default `0.75`) |
| `WORKFLOW_ENABLED` | Optional | Workflow coordination (default `true`) |
| `WORKFLOW_MAX_PARALLEL` | Optional | Parallel ready steps (default `4`) |
| `WORKFLOW_DEFAULT_TIMEOUT_SECONDS` | Optional | Timeout hint (default `120`) |
| `WORKFLOW_RETRY_LIMIT` | Optional | Technical retry limit (default `3`) |
| `WORKFLOW_CHECKPOINTS_ENABLED` | Optional | Persist workflow_ops in state_json (default `true`) |
| `WORKFLOW_COMPENSATION_ENABLED` | Optional | Explicit compensation metadata (default `false`) |
| `EVENT_ENABLED` | Optional | Enterprise Event Bus (default `true`) |
| `EVENT_PROVIDER` | Optional | `in_process` \| `mock` (unknown fails fast) |
| `EVENT_RETRY_LIMIT` | Optional | Handler retries (default `3`) |
| `EVENT_MAX_WORKERS` | Optional | In-process workers (default `2`) |
| `EVENT_ORDERING` | Optional | Per-aggregate ordering (default `true`) |
| `EVENT_DEAD_LETTER` | Optional | Dead letter persistence (default `true`) |
| `EVENT_SYNC_DISPATCH` | Optional | Force sync dispatch (default `false`) |

### Decision Intelligence

```text
Runtime → Planner → Decision Engine → LLM (advisor) → Business Services
```

- Decision Engine is advisory; hard policy rules win; LLM cannot override RBAC/approvals/ERP.

### Workflow Execution

```text
Runtime → Planner → Decision Engine → Workflow Engine → Tools → Business Services
```

- **Persistence:** Checkpoints in `agent_run_states.state_json` (no separate workflow tables in this checkpoint).
- **Resume / retry:** Continues from last safe checkpoint; business rejections do not auto-retry.
- **Compensation / cancel:** Stops future steps; does not invent ERP rollback.
- **Planner relationship:** Workflow Engine wraps `TaskExecutor` / resume — it does not replace the planner.

### Enterprise Event Bus

```text
Runtime → Planner → Decision → Workflow → Event Bus → Business Services → Workers
```

- **Lifecycle:** Business service / workflow publishes `EventEnvelope` → router selects handlers → worker dispatches (sync or async) → audit (published / received / processed / retried / dead_letter / replayed).
- **Ordering:** When `EVENT_ORDERING=true`, handlers for the same `aggregate_type:aggregate_id` run under a lock (at-least-once still applies).
- **Retries:** Transient handler failures retry up to `EVENT_RETRY_LIMIT` (exponential by default). Business validation errors (`ValueError` / `TypeError` / `KeyError`) are not retried.
- **Dead letters & replay:** Exhausted failures go to an in-memory DLQ; `EventBus.replay_dead_letter` re-publishes. Pending DLQ → Health **Degraded** (not Unavailable).
- **Fail-soft:** If the bus is disabled or workers fail, publish falls back to synchronous dispatch or skip; business commits are never rolled back because of event delivery.
- **Not in this deployment:** Kafka, RabbitMQ, Azure Service Bus, AWS SQS, Kubernetes event mesh, live SAP eventing.

### Semantic knowledge (RAG)

- **Structured vs semantic:** SQL memory owns exact IDs/history; RAG owns prose policies/SOPs/guides.
- **Ingestion:** Use `memory.rag.ingestion.ingest_knowledge` (or `seed_demo_knowledge` for demos). Not a CMS.
- **Embeddings / vectors:** Local vector store only. Do **not** set env vars implying pgvector, Azure AI Search, OpenSearch, or Pinecone — those providers are not implemented.
- **Hybrid retrieval:** Combines structured filters with semantic similarity; fail-soft if embeddings/vector search fail.
- **Access / injection:** Filter by `access_scope` before the LLM; treat retrieved text as untrusted data (cannot override RBAC, tools, or approvals).
- **Migration:** Alembic revision `20260812_0013` adds `knowledge_documents` / `knowledge_chunks`.

### Integration providers

Business services call provider interfaces in `integrations/`. Add a future adapter by:

1. Implementing the contract in `integrations/contracts.py`
2. Registering it in `integrations/factory.py` `_SUPPORTED`
3. Documenting the env value here

Do **not** describe SAP/Oracle/POS providers as available until implemented.

### Authentication model

- **Provider:** `AUTH_PROVIDER=demo` → `DemoAuthenticationProvider`. Other values fail fast (OIDC/Entra/Okta are not wired yet).
- **Sessions:** Login creates a signed opaque token; roles come from the server session store / `DEMO_USERS`, never from client-editable Streamlit fields.
- **TTL:** `SESSION_TTL_MINUTES` (default 480). Logout revokes the session.
- **RBAC:** Five roles preserved (`viewer` … `administrator`). Analysis, HITL resume, Agent Operations, and Administration enforce permissions in services.
- **Secrets:** Never log or return `DEMO_ACCESS_CODE`, `SESSION_SECRET`, or provider credentials in UI, health, or Agent Operations payloads.

Local development may keep:

```env
DATABASE_URL=sqlite:///retail_agent.db
APP_ENV=development
AUTH_PROVIDER=demo
DEMO_ACCESS_CODE=
SESSION_TTL_MINUTES=480
```

When `DEMO_ACCESS_CODE` is empty in development, the app uses the local default `infolob-demo`.

---

## 6. Database migrations

Hosted deploys should run:

```bash
python -m alembic upgrade head
```

Or:

```bash
python scripts/migrate_and_seed.py
```

The initial revision `20260731_0001` creates:

- `recommendations`
- `human_reviews`
- `approvals`
- `purchase_orders`
- `audit_events`
- `agent_run_states`

Local tests continue to use SQLite via `init_db()` / `create_all` in pytest fixtures.

If an existing local SQLite file was created before Alembic, delete `retail_agent.db` or run migrations against a fresh database.

---

## 7. Demo-data seeding

Idempotent seed:

```bash
python scripts/seed_demo_data.py
```

Force additional sample recommendations:

```bash
python scripts/seed_demo_data.py --force
```

Administrator reset (workflow tables only; CSV master data kept):

```bash
python scripts/reset_demo_data.py --actor admin.demo --role administrator --reseed
```

In the UI, sign in as **Dana Miller** (`admin.demo`) and use **Reset Demo Data** in the sidebar.

---

## 8. Scheduled replenishment batch (“Run now” + cron)

The batch scores the full inventory catalog (`store × SKU` from CSV) through the existing deterministic services and policy engine. Results feed **Today's Queue**.

**Important:** Streamlit page loads never start a batch. Only an explicit **Run now** click or the CLI/cron job does.

### Default schedule

| Setting | Value |
|---|---|
| Default cadence | Every 6 hours |
| Cron | `0 */6 * * *` |
| Timezone | `REPLENISHMENT_TIMEZONE` (default `UTC`) |

Configuration:

| Variable | Default | Purpose |
|---|---|---|
| `REPLENISHMENT_SCHEDULE_ENABLED` | `true` | Master switch for scheduled CLI/cron triggers |
| `REPLENISHMENT_CRON` | `0 */6 * * *` | Canonical cron expression (next-run + bucket identity) |
| `REPLENISHMENT_TIMEZONE` | `UTC` | Timezone for cron evaluation and bucket keys |
| `REPLENISHMENT_RUN_INTERVAL_HOURS` | `6` | Display / stale-window helper |
| `REPLENISHMENT_STALE_TOLERANCE_MINUTES` | `90` | Extra grace before scheduler health is `stale` |
| `CRON_SECRET` | _(empty)_ | Required for machine triggers when set |
| `BATCH_SCHEDULE_CRON` / `BATCH_SCHEDULE_TIMEZONE` | aliases | Backward-compatible fallbacks |

When `REPLENISHMENT_SCHEDULE_ENABLED=false`, scheduled CLI/cron invocations skip with `blocked_reason=schedule_disabled` (exit 0). **Manual Run Now** and **Retry** still work for administrators.

### Manual — Administration UI

1. Sign in as **Dana Miller** (`admin.demo`)
2. Open **Administration**
3. Review scheduler health, last/next run, and status
4. Click **Run now** (or **Retry failed run** when applicable)

### CLI (local or host shell)

Preferred entry point:

```bash
python -m jobs.run_replenishment
python -m jobs.run_replenishment --trigger scheduled --initiated-by replenishment_scheduler
```

When `CRON_SECRET` is set:

```bash
python -m jobs.run_replenishment --trigger scheduled --initiated-by render-cron --cron-secret "$CRON_SECRET"
```

Status only (never starts a batch):

```bash
python -m jobs.run_replenishment --status-only
```

Disable schedule:

```bash
REPLENISHMENT_SCHEDULE_ENABLED=false python -m jobs.run_replenishment --trigger scheduled
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Batch completed, **or** harmless skip (`schedule_disabled`, `duplicate_invocation`, `active_run`) |
| `1` | Genuine failure (exception or run `status=failed`) |

Overlapping runs are blocked with a database-backed lease while a run is `pending`/`running`. Scheduled retries for the **same cron bucket** reuse the deterministic invocation key (`scheduled:<bucket-iso>`) and do not create duplicate recommendations or OrderIntents.

(`scripts/run_replenishment_batch.py` remains a thin wrapper around the same module.)

### Render scheduling (simplest demo approach)

Use Render’s **native Cron Job** — no Celery/RQ/worker fleet.

`render.yaml` defines `retail-replenishment-batch` on `0 */6 * * *` (every 6 hours), running:

```bash
python -m jobs.run_replenishment --trigger scheduled --initiated-by render-cron --cron-secret "$CRON_SECRET"
```

- Set `CRON_SECRET` on **both** the web and cron services (Dashboard → Environment).
- Share the same `DATABASE_URL` / Postgres — do not create a second database.
- Render cron typically requires a **paid** cron-capable plan. On free-only accounts, disable/remove the cron service and use an external scheduler (GitHub Actions, system cron, etc.) with the same command + `DATABASE_URL`.

### External cron example

```bash
0 */6 * * * cd /app && CRON_SECRET=… DATABASE_URL=… python -m jobs.run_replenishment --trigger scheduled --initiated-by external-cron
```

Timezone: cron expressions are evaluated in `REPLENISHMENT_TIMEZONE`. Persist run timestamps in UTC; convert for display only.
---

## 9. Custom domain

1. Render web service → **Settings** → **Custom Domains**
2. Add your domain (e.g. `replenishment-demo.example.com`)
3. Create the DNS records Render shows (usually a CNAME to `*.onrender.com`)
4. Wait for certificate provisioning
5. Confirm:

- Home page loads with the demonstration banner
- `/Health` returns a healthy JSON-like status payload
- Login works with your hosted `DEMO_ACCESS_CODE`

---

## 10. Post-deploy verification checklist

1. Open `/Health` — status `ok`, database dialect `postgresql`
2. Sign in with access code + named demo user
3. As administrator, open **Administration** → **Run now** and confirm Today's Queue refreshes
4. Approve / adjust exceptions; open **Approved Today**
5. On **Orders**, run **Send approved to ERP** and confirm mock ERP references
6. Confirm viewer cannot submit/approve or trigger Run now
7. Confirm a second user session can create its own recommendations
8. As administrator, run **Reset Demo Data** once and verify the app still works
9. (Optional) Trigger `python -m jobs.run_replenishment --status-only` against hosted `DATABASE_URL`

---

## 11. Operational notes

- Purchase orders transmit through a **mock ERP** adapter only — no real supplier network calls
- Authorization is enforced in Python services, not by the language model
- Per-user analysis rate limits protect the shared demo budget
- SQLite remains supported for local development and automated tests only
- Scheduled batch and Admin **Run now** use the same scoring path; chat cannot start a batch

© 2026 Infolob Solutions · Confidential
