# Customer Demo Walkthrough — Retail Replenishment Agent

End-to-end **demonstration story** using existing CSV demo data and supported services.  
UI values come from real scoring, approvals, and mock purchasing — nothing is faked in the UI.

**Queue ≠ Transmit** remains in force (`ERP_AUTO_TRANSMIT=false` by default).

---

## Login

| Field | Value |
|-------|--------|
| App | `streamlit run app.py` |
| Demo access code | `infolob-demo` (when `DEMO_ACCESS_CODE` is unset) |
| Primary role | **Alex Johnson** (`alex.store`) |
| Admin trail | **Dana Miller** (`admin.demo`) for Agent Operations / System Health |

Optional prep (fresh deterministic batch):

```bash
python scripts/prepare_customer_demo.py
```

Or use **Run replenishment now** on Overview / Today's Decisions after login (same SKU set can be re-run; blocked scenario needs the prepare script or a scoring session that applies the stale-age override for SKU-1004).

---

## Deterministic scenarios (A–F)

| ID | Store / SKU | Product | Expected disposition / status | Business story |
|----|-------------|---------|-------------------------------|----------------|
| **A** | ST001 / SKU-1002 | Sparkling Water | `auto_release` → Handled automatically | Low-risk within policy — released without human review |
| **B** | ST001 / SKU-1001 | Organic Whole Milk | `human_review` → Needs your review | Clear exception for Decision Detail + approve |
| **C** | ST001 / SKU-1004 | Greek Yogurt | `blocked` → Cannot proceed | Stale inventory signal (demo prep applies in-process age override; **CSV not modified**) |
| **D** | ST002 / SKU-1003 | Granola Bars | `no_order` → No order needed | Sufficient coverage — no PO |
| **E** | (after approving B) | — | `retry_pending` → Retry Scheduled | Mock `temporary_failure` on transmit |
| **F** | (after approving B on a fresh run) | — | `erp_rejected` → Rejected by Purchasing System | Mock `business_rejection` — no auto-retry |

Canonical pairs and helpers live in `services/demo_story_service.py`.

---

## Walkthrough (happy path)

### 1. Open Replenishment Overview

**Action:** Login as `alex.store` → **Replenishment Overview**.

**Expected UI:**
- Page title: Replenishment Overview
- Status strip: Agent status, Last analysis, **Next analysis**, Data freshness
- Compact KPIs (not giant metric cards)

**Story:** Continuous agent work; exceptions only when needed.

### 2. Data source health & schedule

**Expected UI:**
- Data freshness pill on the strip
- **Data source status** section (Inventory, Sales, Purchasing connection: Demo system)
- Next scheduled analysis time from the scheduler

**Story:** Customer sees whether feeds are ready before trusting recommendations.

### 3. Run replenishment (or use prepared run)

**Action (demo mode):** **Run replenishment now** (store manager may be limited — use `admin.demo` or prep script if CTA is admin-gated).  
**Or:** Rely on `prepare_customer_demo.py` output `run_id`.

**Expected UI:** Analysis completes; Overview refreshes with non-zero **Agent analyzed**.

### 4. Overview updates

**Expected metrics (prepared 4-SKU demo batch):**

| KPI label | Typical value |
|-----------|----------------|
| Agent analyzed | 4 |
| Needs your review | 1 (SKU-1001) |
| Handled automatically | 1 (SKU-1002) |
| Cannot proceed | 1 (SKU-1004) |
| No order needed | 1 (SKU-1003 @ ST002) |

**Story:** One glance at the day’s replenishment posture.

### 5. Open Today's Decisions

**Action:** Nav → **Today's Decisions** (or Review exceptions).

**Expected UI:**
- Subtitle about decisions needing attention
- Dense table: Priority, Store, Product, Agent recommends, Why, Risk, Order value, Status
- Filters include Needs your review / Handled automatically / Cannot proceed / No order needed

### 6–7. Review one clear recommendation (scenario B)

**Action:** Open **Review · Organic Whole Milk…** (SKU-1001 / Downtown Flagship).

**Expected Decision Detail:**
- Hero action (e.g. Order N units)
- Evidence strip: Demand forecast, On hand, In transit, Safety stock, Days of supply, Case pack, Order value
- Stages: **Demand**, **Inventory**, **Replenishment calculation**, **Policy & risk**
- Memory/knowledge sections when present (collapsed / secondary — not required to invent content)

**Story:** Transparent quantity reasoning before a human commits.

### 8. Approve

**Action:** Approve as recommended (store manager).

**Expected UI:** Success / decided state; recommendation leaves Needs your review.

### 9. Approved for Purchase — what happens next

**Action:** Nav → **Approved for Purchase**.

**Expected UI:**
- Summary: Approved today, Handled automatically, Approved by people, Total value, Next transmission
- For SKU-1001: **Next step** = `Requires manual send` (demo; auto-transmit off)
- Status language: **Ready to Send** (not “queued for ERP”)

**Story:** Approval prepared a purchasing order; sending is a separate demo action.

### 10. Purchase Order Ready to Send

**Action:** Nav → **Purchase Orders**.

**Expected UI:**
- Subtitle about approved orders ready to send
- KPI: Ready to send ≥ 1 (human-approved + any auto-queued)
- Status pill: **Ready to Send**

### 11. Demo / manual transmission

**Action:** Under **Demo action**, click **Send now** (authorized roles only).

**Expected UI:** Confirmation of sent / created / skipped counts.  
Do **not** present this as a production purchasing schedule.

### 12. Status progression

**Expected labels (customer-facing):**

1. Ready to Send  
2. Sending *(brief / may be skipped in fast mock)*  
3. Accepted by Purchasing System / **Completed**

After mock success, workbench shows **Completed** / Accepted counts up; Ready to send decreases.

### 13. History — business trail

**Action:** Nav → **History**.

**Expected events (examples):**
- `recommendation_created` / `policy_evaluated`
- `recommendation_auto_released` (A)
- `recommendation_blocked` (C)
- `human_review_submitted`, `recommendation_approved` (B)
- `order_queued`, `purchase_order_created`
- `erp_transmission_started`, `erp_transmission_succeeded`

**Story:** Append-only business audit the customer can explain to auditors.

### 14. Agent Operations — execution trail (admin)

**Action:** Login as `admin.demo` → **Agent Operations**.

**Expected UI:** Execution metrics (completed today, waiting for human, failures/retries) and execution list/timeline for deeper ops diagnosis.

### 15. System Health

**Action:** Admin → **System Health**.

**Expected UI:** Dependencies listed (DB, CSV feeds, mock purchasing).  
Overall may be **healthy** or **stale** when CSV watermarks age past policy thresholds — that is **truthful**. It must not show Unavailable for core demo providers.

---

## Failure demos (E / F)

Use a **fresh** prepare + approve of scenario B (do not Send now successfully first).

| Scenario | How | Expected customer status | Message intent |
|----------|-----|--------------------------|----------------|
| **E** Retry | `transmit_order_intent(..., mock_scenario="temporary_failure")` or force-fail mock | Retry Scheduled | Temporary problem; agent will retry; no action required |
| **F** Reject | `mock_scenario="business_rejection"` | Rejected by Purchasing System | Reason shown; review required; no auto-retry |

Covered by `tests/test_customer_demo_story.py` and existing lifecycle tests.

---

## What we deliberately do **not** change

- ERP lifecycle semantics / enum names  
- Default `ERP_AUTO_TRANSMIT=false`  
- Policy formulas, Decision Engine, Planner, Memory, RAG  
- CSV master data files  

Blocked scenario **C** uses an in-process inventory-age override during scoring only (same technique as AppTests).
