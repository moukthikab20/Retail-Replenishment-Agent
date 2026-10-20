"""Scheduled / manual replenishment batch entry point.

Usage:
  python -m jobs.run_replenishment
  python -m jobs.run_replenishment --trigger scheduled --initiated-by render-cron
  python -m jobs.run_replenishment --status-only
  python -m jobs.run_replenishment --trigger retry --initiated-by admin.demo

Exit codes:
  0 = completed successfully, or harmless skip
      (schedule_disabled / duplicate_invocation / active_run overlap)
  1 = genuine execution failure (batch status=failed or unexpected exception)

This module must not be imported by Streamlit pages for side effects — pages
read status via scheduler_service.get_run_trigger_status() only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import SCHEDULER_ACTOR  # noqa: E402
from services import scheduler_service  # noqa: E402


def _parse_pairs(values: list[str] | None) -> list[tuple[str, str]] | None:
    if not values:
        return None
    pairs: list[tuple[str, str]] = []
    for raw in values:
        if ":" not in raw:
            raise SystemExit(f"Invalid --pair '{raw}' (expected STORE:SKU)")
        store_id, sku = raw.split(":", 1)
        store_id, sku = store_id.strip(), sku.strip()
        if not store_id or not sku:
            raise SystemExit(f"Invalid --pair '{raw}' (expected STORE:SKU)")
        pairs.append((store_id, sku))
    return pairs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a replenishment batch (scheduled or manual CLI)"
    )
    parser.add_argument(
        "--trigger",
        choices=("scheduled", "manual", "retry"),
        default="scheduled",
        help="Run trigger type (default: scheduled)",
    )
    parser.add_argument(
        "--initiated-by",
        default=None,
        help="Actor recorded on the run (default: replenishment_scheduler)",
    )
    parser.add_argument(
        "--cron-secret",
        default=None,
        help="Must match CRON_SECRET when that env var is set",
    )
    parser.add_argument(
        "--pair",
        action="append",
        dest="pairs",
        help="Optional STORE:SKU (repeatable). Default = full inventory catalog.",
    )
    parser.add_argument(
        "--resume-active",
        action="store_true",
        help="Resume an in-progress run instead of blocking",
    )
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Print current run/schedule status and exit (never starts a batch)",
    )
    parser.add_argument(
        "--invocation-key",
        default=None,
        help="Optional explicit scheduled invocation key (tests / ops)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.status_only:
        print(json.dumps(scheduler_service.get_run_trigger_status(), indent=2, default=str))
        return 0

    pairs = _parse_pairs(args.pairs)
    initiated_by = args.initiated_by or (
        SCHEDULER_ACTOR if args.trigger == "scheduled" else "cli"
    )

    try:
        if args.trigger == "scheduled":
            outcome = scheduler_service.run_scheduled(
                initiated_by=initiated_by,
                store_sku_pairs=pairs,
                resume_active=args.resume_active,
                cron_secret=args.cron_secret,
                invocation_key=args.invocation_key,
            )
        elif args.trigger == "retry":
            outcome = scheduler_service.trigger_replenishment_run(
                trigger_type="retry",
                initiated_by=initiated_by,
                store_sku_pairs=pairs,
                resume_active=args.resume_active,
                cron_secret=args.cron_secret,
                require_admin_role=False,
            )
        else:
            outcome = scheduler_service.trigger_replenishment_run(
                trigger_type="manual",
                initiated_by=initiated_by,
                store_sku_pairs=pairs,
                resume_active=args.resume_active,
                cron_secret=args.cron_secret,
                require_admin_role=False,
            )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"started": False, "error": str(exc)}, indent=2, default=str))
        return 1

    print(json.dumps(outcome, indent=2, default=str))

    # Harmless skips (disabled / duplicate / overlap) → exit 0 for Render cron.
    if not outcome.get("started"):
        if outcome.get("harmless_skip") or outcome.get("blocked_reason") in {
            "schedule_disabled",
            "duplicate_invocation",
            "active_run",
        }:
            return 0
        return 1

    status = (outcome.get("run") or {}).get("status")
    if status == "failed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
