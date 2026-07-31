# Requirements — Retail Replenishment Agent POC

This document describes **only what the current implementation does**. It reflects the code as shipped in this repository.

---

## Functional requirements

### FR-1 Data loading

- The application loads three CSV files from the `data/` directory at startup: `products.csv`, `inventory.csv`, and `sales.csv`.
- Sales dates are parsed to datetime. Loaded data is cached for the Streamlit session (`@st.cache_data`).

### FR-2 Store and SKU selection

- The user selects **one store** from a dropdown populated from distinct values in `inventory.csv`.
- The user selects **one SKU** from a dropdown filtered to SKUs available at the selected store.
- SKU labels display as `{sku} — {product_name}`.

### FR-3 Demand forecasting

- The system computes **average daily sales** for the selected store and SKU using the **7 calendar days immediately before** the as-of date.
- The system forecasts **7-day total demand** as average daily sales × 7.
- The system builds a **14-day sales trend** series for charting (days before the as-of date, exclusive).

### FR-4 Replenishment calculation

- The system calculates a recommended reorder quantity using inventory, forecast, and product master data.
- All numeric results are computed in Python (`forecast.py`, `replenishment.py`). The agent does not perform calculations.

### FR-5 Inventory risk classification

- The system assigns one of three risk labels: `stockout`, `balanced`, or `overstock`.
- The label is displayed as a badge in the UI.

### FR-6 Agent explanation

- A **single orchestration agent** produces a natural-language explanation of the replenishment recommendation and inventory risk.
- If `OPENAI_API_KEY` is set, the agent calls the OpenAI Chat Completions API (default model: `gpt-4o-mini`; overridable via `OPENAI_MODEL`).
- If the API key is missing or the API call fails, the agent returns a **rule-based fallback** explanation keyed to the risk level.
- The agent is instructed not to recalculate numbers; it receives precomputed metrics as JSON context.

### FR-7 Human approval workflow

- The user can **Approve** or **Reject** the current recommendation.
- **Approve** with recommended quantity > 0: creates a **mock purchase order** record in Streamlit session state and displays it on screen.
- **Approve** with recommended quantity = 0: records approval with a message that no PO is required; no PO record is created.
- **Reject**: records rejection; no PO is created.
- Changing store or SKU clears prior approval status, PO record, and cached agent explanation for the new selection.

### FR-8 Agent refresh

- The user can click **Refresh Agent Analysis** to regenerate the agent explanation for the current store/SKU.
- Refresh clears approval status and any existing PO record.

### FR-9 Application entry point

- The application runs as a Streamlit app via `streamlit run app.py`.
- Page title: **Retail Replenishment Agent | Infolob**.
- Layout: wide, sidebar collapsed.

---

## Business rules

### BR-1 As-of date

- All forecast and trend windows are anchored to a **fixed as-of date**: `2026-07-27`.
- The 7-day average sales window is `[as_of_date − 7 days, as_of_date)` — the as-of date itself is excluded.
- The 14-day chart window is `[as_of_date − 14 days, as_of_date)`.

### BR-2 Average daily sales

```
average_daily_sales = sum(units_sold in lookback window) / 7
```

- If no sales rows exist in the window, average daily sales = `0.0`.
- Lookback period defaults to **7 days**.

### BR-3 Seven-day forecast

```
daily_forecast = average_daily_sales
total_forecast = daily_forecast × 7
```

- Forecast horizon defaults to **7 days**.
- Returned values are rounded to 2 decimal places.

### BR-4 Reorder quantity

```
raw_reorder = total_forecast + safety_stock − on_hand − in_transit
non_negative = max(0, raw_reorder)
```

- If `case_pack_size ≤ 0`, it is treated as **1**.
- If `non_negative = 0`, recommended order quantity = **0**.
- Otherwise:

```
recommended_order_qty = ceil(non_negative / case_pack_size) × case_pack_size
```

(integral case-pack multiple, rounded up)

### BR-5 Days of supply

```
days_of_supply = (on_hand + in_transit) / (total_forecast / 7)
```

- If `total_forecast = 0`, days of supply is **undefined** (`None` in output).

### BR-6 Risk classification (`assess_inventory_risk`)

Evaluated in order:

| Condition | Risk label |
|-----------|------------|
| `total_forecast ≤ 0` and `on_hand > 0` | `overstock` |
| `days_of_supply` is `None` | `balanced` |
| `days_of_supply < 3` **or** (`recommended_order_qty > 0` and `on_hand < total_forecast × 0.3`) | `stockout` |
| `days_of_supply > 14` and `recommended_order_qty = 0` | `overstock` |
| Otherwise | `balanced` |

### BR-7 Agent context

The agent receives a flat dictionary containing:

- Store name, SKU, product name
- Average daily sales, total forecast, horizon days
- Safety stock, on hand, in transit
- Recommended order quantity, case pack size, days of supply
- Risk level (`stockout` / `balanced` / `overstock`)

### BR-8 Mock purchase order

Created only on **Approve** when `recommended_order_qty > 0`.

| Field | Value |
|-------|-------|
| `po_number` | `PO-MOCK-{YYYYMMDDHHMMSS}` |
| `status` | `Draft — Mock ERP` |
| `store_id`, `store_name`, `sku`, `product_name` | From current selection |
| `order_qty` | `recommended_order_qty` |
| `created_at` | Current local timestamp |

- PO exists only in **Streamlit session state** for the active browser session.
- PO is **not** written to disk or sent to an external system.

### BR-9 Agent behavior constraints

- System prompt requires 3–5 sentences, prose only (no bullet lists).
- Agent must explain stockout or overstock risk using provided metrics.
- Agent must not recalculate replenishment figures.

---

## Data requirements

### DR-1 Sample dataset scale

| Dataset | Current rows |
|---------|----------------|
| Stores | 2 (`ST001`, `ST002`) |
| SKUs | 5 (`SKU-1001` … `SKU-1005`) |
| Inventory records | 10 (2 stores × 5 SKUs) |
| Sales history | 14 days per store/SKU (140 rows total) |

### DR-2 `data/products.csv`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `sku` | string | Yes | Unique product identifier |
| `product_name` | string | Yes | Display name |
| `case_pack_size` | integer | Yes | Order rounding unit |
| `safety_stock_units` | integer | Yes | Safety stock buffer in units |

### DR-3 `data/inventory.csv`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `store_id` | string | Yes | Store identifier |
| `store_name` | string | Yes | Store display name |
| `sku` | string | Yes | Product identifier |
| `on_hand` | integer | Yes | Units in store |
| `in_transit` | integer | Yes | Units on order |

- Each `(store_id, sku)` pair must exist for SKUs sold at that store.
- Store list in the UI is derived from distinct rows in this file.

### DR-4 `data/sales.csv`

| Column | Type | Required | Description |
|--------|------|----------|-------------|
| `date` | date (`YYYY-MM-DD`) | Yes | Sale date |
| `store_id` | string | Yes | Store identifier |
| `sku` | string | Yes | Product identifier |
| `units_sold` | integer | Yes | Units sold that day |

- Sample data spans **2026-07-13** through **2026-07-26** (14 days before as-of date).
- Rows must align with store/SKU combinations in inventory for meaningful forecasts.

### DR-5 Environment variables (optional)

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `OPENAI_API_KEY` | No | — | Enables OpenAI agent explanations |
| `OPENAI_MODEL` | No | `gpt-4o-mini` | OpenAI model for agent |

### DR-6 Runtime dependencies

Declared in `requirements.txt`:

- `streamlit >= 1.32.0`
- `pandas >= 2.0.0`
- `openai >= 1.12.0`
- `plotly >= 5.18.0`

---

## UI requirements

All styling follows the **Infolob Brand & Design System** via `styles.py`. Body text is left-aligned throughout.

### UR-1 Page chrome

- **Background:** `#FAFBFC`
- **Primary structural color:** `#1C2B3A` (headers, primary buttons, footer, navy bands)
- **Body text:** `#2C3E50`
- **Font:** Aptos preferred (`'Aptos', 'Segoe UI', system-ui, sans-serif`)
- **Page title:** "Retail Replenishment Agent" with subtitle "Agentic AI POC · Seven-day forecast · Human-in-the-loop approval"
- **Title styling:** No underline; thin **4px red stripe** (`#C0392B`) to the left of the title
- **Borders:** `#E2E8F0`

### UR-2 Layout

- **Two-column** main content area (equal width, large gap).
- **Full-width** replenishment summary callout below the two columns.
- **Approval buttons** in a three-column row (`3:1:1`), aligned **lower right** (Approve primary, Reject secondary).
- **Footer bar** fixed to the bottom of the viewport, always visible.

### UR-3 Left column

1. **Selector card** — Store dropdown, SKU dropdown, pillar chips:
   - `Forecasting` chip — teal (`#0D9488`)
   - `Analytics Layer` chip — purple (`#7C3AED`)

2. **Sales Trend · Last 14 Days card** — Navy header, white text; Plotly bar chart:
   - Bar color `#0D9488`
   - Empty state message if no sales data

3. **Inventory & Forecast Statistics card** — Risk badge plus six stat callouts in a 2×3 grid:
   - Avg Daily Sales (7d)
   - 7-Day Forecast
   - On Hand
   - In Transit
   - Safety Stock
   - Days of Supply (displays `N/A` when undefined)

### UR-4 Right column

**Agentic AI Recommendation card** containing:

- Chips: `Agentic AI` (purple `#7C3AED`), `Mock ERP` (amber `#D97706`)
- Agent explanation prose
- **Refresh Agent Analysis** secondary button
- **Navy callout band** showing recommended order quantity (white text on `#1C2B3A`)
- Secondary line: case pack size, raw calc, rounded result

### UR-5 Full-width summary callout

- White card with purple left accent (`#7C3AED`)
- Shows product name, store, SKU, and full formula breakdown with numeric values

### UR-6 Risk badge styling

| Risk | Label shown | Accent |
|------|-------------|--------|
| `stockout` | Stockout Risk | Red accent `#C0392B` (badge only, not large fill) |
| `balanced` | Balanced | Teal `#0D9488` |
| `overstock` | Overstock Risk | Amber `#D97706` |

- Red (`#C0392B`) is used only as a thin accent (title stripe, stockout badge) — **not** as a primary button or large fill.

### UR-7 Approval feedback

| Action | UI feedback |
|--------|-------------|
| Approve (qty > 0) | Amber-left-accent PO record panel with PO number, status, line details, timestamp |
| Approve (qty = 0) | PO-style panel stating no PO required |
| Reject | PO-style panel with gray left accent stating no PO created |

### UR-8 Footer bar

- Background `#1C2B3A`, white text
- Left: `© 2026 Infolob Solutions · Confidential`
- Right: `INFOLOB` (bold, letter-spaced)

### UR-9 Buttons

- **Approve:** Primary — navy fill (`#1C2B3A`), white text
- **Reject:** Secondary — white fill, navy text, `#E2E8F0` border
- **Refresh Agent Analysis:** Secondary style

### UR-10 Streamlit configuration

- Wide layout
- Sidebar collapsed
- Page icon: 📦
- Max content width ~1200px with bottom padding to clear fixed footer

---

## Out of scope

The following are **explicitly not part of the current implementation**:

- Database or persistent storage (POs, approvals, audit logs)
- User authentication, authorization, or role-based access
- Real ERP, WMS, or supplier integration
- Purchase order export, email, or API submission
- CSV upload or runtime data editing
- Configurable as-of date via UI or config file
- Multiple agents or agent orchestration frameworks
- Machine learning or statistical forecasting beyond flat average
- Seasonality, promotions, holidays, or external demand signals
- Lead time, supplier calendars, or minimum order value rules
- Multi-SKU or multi-store batch replenishment in one action
- Docker, CI/CD, or deployment configuration
- Automated approval (human action is required)
- Unit, integration, or end-to-end test suite
- Logging, monitoring, or error reporting infrastructure
- Internationalization or multi-language support

---

© 2026 Infolob Solutions · Confidential
