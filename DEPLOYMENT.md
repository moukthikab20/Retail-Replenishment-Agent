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
| `DEMO_ACCESS_CODE` | Yes (hosted) | Shared demo gate; do not commit |
| `OPENAI_API_KEY` | Optional | Enables live agent runs |
| `OPENAI_MODEL` | Optional | Defaults to `gpt-4o-mini` when unset |
| `TRACE_SENSITIVE_DATA` | Optional | Keep `false` |
| `MAX_AGENT_RUNS_PER_USER_PER_HOUR` | Optional | Default `20` |
| `RATE_LIMIT_WINDOW_MINUTES` | Optional | Default `60` |

**Never expose** `OPENAI_API_KEY`, `DEMO_ACCESS_CODE`, or raw `DATABASE_URL` passwords to the browser. The Health page redacts credentials.

Local development may keep:

```env
DATABASE_URL=sqlite:///retail_agent.db
APP_ENV=development
DEMO_ACCESS_CODE=
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

In the UI, sign in as **Dana Administrator** (`admin.demo`) and use **Reset Demo Data** in the sidebar.

---

## 8. Custom domain

1. Render web service → **Settings** → **Custom Domains**
2. Add your domain (e.g. `replenishment-demo.example.com`)
3. Create the DNS records Render shows (usually a CNAME to `*.onrender.com`)
4. Wait for certificate provisioning
5. Confirm:

- Home page loads with the demonstration banner
- `/Health` returns a healthy JSON-like status payload
- Login works with your hosted `DEMO_ACCESS_CODE`

---

## 9. Post-deploy verification checklist

1. Open `/Health` — status `ok`, database dialect `postgresql`
2. Sign in with access code + named demo user
3. Run Analysis as `alex.store` and confirm a `recommendation_id`
4. Continue to Review; submit for approval
5. Approve with a role that satisfies the required level
6. Confirm mock PO IDs only (no real supplier/ERP calls)
7. Confirm a second user session can create its own recommendations
8. Confirm viewer cannot submit/approve
9. As administrator, run **Reset Demo Data** once and verify the app still works

---

## 10. Operational notes

- Purchase orders are **mock only** — status `Draft — Mock ERP`
- Authorization is enforced in Python services, not by the language model
- Per-user analysis rate limits protect the shared demo budget
- SQLite remains supported for local development and automated tests only

© 2026 Infolob Solutions · Confidential
