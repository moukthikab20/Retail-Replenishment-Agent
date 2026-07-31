# Retail Replenishment Agent — Agentic AI POC

A proof-of-concept Streamlit application that demonstrates human-in-the-loop retail replenishment. Python calculates forecasts and reorder quantities from CSV data; a single orchestration agent explains inventory risk and recommendations for human approval before a mock purchase order is created.

Built for **Infolob Solutions** with the Infolob Brand & Design System.

---

## 1. Project purpose

This POC shows how an **Agentic AI** layer can sit on top of deterministic replenishment math:

- Read sample retail data (2 stores, 5 SKUs) from CSV files
- Forecast seven-day demand using trailing average daily sales
- Calculate recommended order quantities with safety stock and case-pack rounding
- Let an AI agent **explain** stockout or overstock risk — without recalculating numbers
- Require **human approval** before creating a **mock purchase order**

It is intentionally small in scope: no database, authentication, ERP integration, or multi-agent architecture.

---

## 2. Folder structure

```
retail-replenishment-poc/
├── app.py                 # Streamlit entry point — UI, workflow, data loading
├── agent.py               # OpenAI orchestration agent + rule-based fallback
├── forecast.py            # Average daily sales and 7-day demand forecast
├── replenishment.py       # Reorder calculation and risk heuristics
├── styles.py              # Infolob brand CSS
├── requirements.txt       # Python dependencies
├── README.md
└── data/
    ├── products.csv       # SKU master (case pack, safety stock)
    ├── inventory.csv      # On-hand and in-transit by store/SKU
    └── sales.csv          # 14 days of daily sales history
```

| File | Role |
|------|------|
| `app.py` | Wires everything together; renders the two-column UI and approval flow |
| `forecast.py` | Business logic for demand forecasting |
| `replenishment.py` | Business logic for reorder quantity and risk classification |
| `agent.py` | AI logic — narrative explanation only |
| `styles.py` | UI styling aligned to Infolob design tokens |
| `data/*.csv` | Static sample datasets consumed at startup |

---

## 3. Data flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  products.csv   │     │ inventory.csv   │     │   sales.csv     │
│  (SKU master)   │     │ (on hand/trans) │     │ (daily history) │
└────────┬────────┘     └────────┬────────┘     └────────┬────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
                          app.py :: load_data()
                                 │
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
  forecast.py              replenishment.py           agent.py
  · avg daily sales        · reorder formula          · build context
  · 7-day forecast         · case-pack round          · explain risk
  · sales trend            · risk assessment          (OpenAI or fallback)
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 ▼
                          app.py :: main()
                    (stats, chart, summary, approve/reject)
                                 │
                                 ▼
                    Mock PO record (session state only)
```

**Inputs per selected store + SKU**

| Source | Fields used |
|--------|-------------|
| `products.csv` | `case_pack_size`, `safety_stock_units`, `product_name` |
| `inventory.csv` | `on_hand`, `in_transit` |
| `sales.csv` | `units_sold` over prior 7 days (forecast) and 14 days (chart) |

**Key calculations (all in Python)**

1. **Average daily sales** = sum of units sold in the previous 7 days ÷ 7  
2. **7-day forecast** = average daily sales × 7  
3. **Raw reorder** = forecast + safety stock − on hand − in transit  
4. **Recommended order** = max(0, raw reorder), rounded up to case pack size  

The agent receives these precomputed values and returns prose explaining inventory risk.

---

## 4. Current workflow

1. **Launch** the Streamlit app (`streamlit run app.py`).
2. **Select** a store and SKU from the left column.
3. **Review** the left panel:
   - Sales trend bar chart (last 14 days)
   - Inventory and forecast statistics (avg daily sales, forecast, on hand, in transit, safety stock, days of supply)
   - Risk badge (Stockout / Balanced / Overstock)
4. **Read** the right panel:
   - Agentic AI explanation of the recommendation
   - Recommended order quantity in the navy callout band
5. **Review** the full-width replenishment summary showing the formula breakdown.
6. **Approve** or **Reject** the recommendation (buttons lower right).
   - **Approve** with qty > 0 → mock purchase order created in session (displayed on screen)
   - **Approve** with qty = 0 → approval recorded, no PO
   - **Reject** → no PO created
7. **Refresh Agent Analysis** to regenerate the AI narrative (e.g. after changing SKU or when using OpenAI).

Session state resets approval and agent text when the store or SKU selection changes.

---

## 5. Technologies used

| Technology | Usage |
|------------|--------|
| **Python 3** | Application runtime |
| **Streamlit** | Web UI, widgets, session state |
| **Pandas** | CSV loading, date filtering, aggregations |
| **Plotly** | Sales trend bar chart |
| **OpenAI API** | Agent narrative (`gpt-4o-mini` by default) |
| **CSV files** | Static data store for the POC |

---

## 6. Current limitations

- **Static CSV data only** — no live ERP, database, or file upload
- **Single forecast method** — flat average of the prior 7 days; no seasonality, promotions, or ML
- **Fixed as-of date** — hardcoded to `2026-07-27` in `app.py`
- **Two stores, five SKUs** — demo scale only
- **Mock purchase orders** — stored in Streamlit session state, not persisted or sent anywhere
- **No authentication or audit trail** — anyone with app access can approve/reject
- **Agent fallback** — without `OPENAI_API_KEY`, explanations use rule-based templates
- **Simple risk rules** — stockout/overstock heuristics based on days of supply thresholds
- **No multi-SKU or multi-store batch replenishment** — one store/SKU at a time
- **No lead time or supplier constraints** — case pack is the only ordering constraint

---

## 7. Future improvements

- **Configurable data source** — upload CSVs, connect to a data warehouse, or sync from ERP
- **Richer forecasting** — weighted averages, seasonality, store-level trends, external signals
- **Batch replenishment** — review and approve orders across all SKUs/stores in one session
- **Persist purchase orders** — write approved POs to CSV, database, or mock ERP API
- **Lead time and supplier rules** — minimum order quantities, delivery calendars, vendor splits
- **Audit and roles** — approver identity, timestamps, rejection reasons
- **Enhanced agent** — tool use for what-if scenarios while keeping math in Python
- **Alerts dashboard** — prioritize SKUs with highest stockout risk across the network
- **Testing** — unit tests for forecast and replenishment modules
- **Deployment** — containerized hosting with secrets management for API keys

---

## Quick start

```powershell
cd retail-replenishment-poc
pip install -r requirements.txt

# Optional — enables OpenAI-generated agent explanations
$env:OPENAI_API_KEY = "your-api-key"

streamlit run app.py
```

Optional environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENAI_API_KEY` | *(none)* | Enables live OpenAI agent explanations |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model used for agent narrative |

---

© 2026 Infolob Solutions · Confidential
