# Retail Replenishment Agent — OpenAI Agents SDK POC

Single-agent Streamlit application for Infolob Solutions. Deterministic Python services own forecasting, replenishment math, risk, human override validation, approval policy, and mock purchase orders. The language model coordinates tools and explains results — it does not invent business values.

## Architecture

```
retail-replenishment-poc/
├── app.py                      # Home entry
├── pages/
│   ├── 1_Analysis.py           # Store/SKU analysis + agent recommendation
│   └── 2_Human_Review.py       # Human override, formal approval, mock PO
├── agent/                      # OpenAI Agents SDK single agent
├── services/                   # Deterministic business logic
├── repositories/               # CSV + SQLite persistence
├── models/                     # Pydantic domain models
├── database/                   # SQLAlchemy schema + connection
├── tests/
├── data/                       # products, inventory, sales CSVs
├── styles.py                   # Infolob design system
├── config.py
├── .env.example
└── requirements.txt
```

## Quantity separation

These three values are always kept distinct:

| Field | Meaning |
|-------|---------|
| `agent_recommended_quantity` | Deterministic agent/service recommendation (never overwritten by humans) |
| `human_proposed_quantity` | Quantity submitted on Human Review |
| `approved_final_quantity` | Quantity set only by formal approval |

## Workflow

1. **Analysis** — select store/SKU, review forecast metrics, run the Retail Replenishment Agent, continue with a saved `recommendation_id`.
2. **Human Review** — accept the agent quantity or enter a different quantity (override reason required when different).
3. **Formal approval** — role-gated approve/reject (development identity simulator in the sidebar).
4. **Mock PO** — created only from an approved `approval_id` (sensitive tool may pause for SDK HITL).

## Quick start

```powershell
cd retail-replenishment-poc
pip install -r requirements.txt
copy .env.example .env
# Optional: set OPENAI_API_KEY and OPENAI_MODEL in .env

streamlit run app.py
```

Without `OPENAI_API_KEY`, analysis uses the same deterministic service pipeline and still persists recommendations (structured fallback).

## Environment

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Enables live Agents SDK runs |
| `OPENAI_MODEL` | Model name (default `gpt-4o-mini` when unset) |
| `DATABASE_URL` | Default `sqlite:///retail_agent.db` |
| `APP_ENV` | `development` by default |
| `TRACE_SENSITIVE_DATA` | `false` by default |

## Tests

```powershell
python -m pytest tests -q
```

Tests use an isolated temporary SQLite database and do not require a live OpenAI API key.

## Git checkpoint

Initial POC preserved as tag `poc-before-agent` on branch `proper-agent-development`.

© 2026 Infolob Solutions · Confidential
