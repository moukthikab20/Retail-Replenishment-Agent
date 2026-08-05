# Retail Replenishment Agent — Multi-user Demo

Single-agent Streamlit application for Infolob Solutions. Deterministic Python services own forecasting, replenishment math, risk, human override validation, approval policy, and mock purchase orders. The language model coordinates tools and explains results — it does not invent business values.

> **Demonstration Environment — sample data — no real supplier orders.**

## Architecture

```
retail-replenishment-poc/
├── app.py
├── pages/
│   ├── 1_Analysis.py
│   ├── 2_Review.py
│   └── 3_Health.py
├── agent/
├── services/
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

Without `OPENAI_API_KEY`, analysis uses the deterministic service pipeline and still persists recommendations.

## Environment

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Enables live Agents SDK runs |
| `OPENAI_MODEL` | Model name (default `gpt-4o-mini` when unset) |
| `DATABASE_URL` | SQLite locally; Postgres on Render |
| `APP_ENV` | `development` / `production` |
| `DEMO_ACCESS_CODE` | Shared demo gate |
| `TRACE_SENSITIVE_DATA` | Keep `false` |
| `MAX_AGENT_RUNS_PER_USER_PER_HOUR` | Shared-demo rate limit |
| `RATE_LIMIT_WINDOW_MINUTES` | Rate-limit window |

## Tests

```powershell
python -m pytest tests -q
```

## Hosted deployment

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for GitHub → Render web service + PostgreSQL, migrations, seeding, and custom domains.

Health probe: `/Health`

© 2026 Infolob Solutions · Confidential
