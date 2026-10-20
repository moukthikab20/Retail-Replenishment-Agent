#!/usr/bin/env python3
"""Prepare a deterministic customer demo replenishment run.

Usage (from repo root):
  python scripts/prepare_customer_demo.py

Uses existing CSV master data and supported services.
Does not rewrite inventory/sales/products CSVs.
Does not enable ERP_AUTO_TRANSMIT.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import demo_story_service as demo


def main() -> int:
    prepared = demo.prepare_customer_demo_run()
    summary = {
        "run_id": prepared["run_id"],
        "overview_metrics": prepared["overview_metrics"],
        "scenarios": {
            letter: {
                "title": meta["title"],
                "sku": meta["pair"][1],
                "store": meta["pair"][0],
                "disposition": meta.get("disposition"),
                "recommendation_id": meta.get("recommendation_id"),
                "product": meta.get("product"),
            }
            for letter, meta in prepared["scenarios"].items()
            if letter in {"A", "B", "C", "D"}
        },
        "next_ui_steps": [
            "Login as alex.store (select user from User Login dropdown)",
            "Open Replenishment Overview — confirm metrics match overview_metrics",
            "Open Today's Decisions — review SKU-1001 (scenario B)",
            "Approve → Approved for Purchase shows Ready to Send / Requires manual send",
            "Purchase Orders → Demo action: Send now",
            "History + Agent Operations (admin.demo) for trails",
        ],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
