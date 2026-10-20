"""Idempotent demo-data seed script.

Usage:
  python scripts/seed_demo_data.py
  python scripts/seed_demo_data.py --force
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Python 3.10 compatibility for enum.StrEnum (3.11+)
import enum as _enum

if not hasattr(_enum, "StrEnum"):
    class StrEnum(str, _enum.Enum):  # type: ignore[no-redef]
        pass

    _enum.StrEnum = StrEnum  # type: ignore[attr-defined]

from services.demo_data_service import seed_demo_data  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo workflow data (idempotent)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Clear workflow tables and reseed historical demo data",
    )
    parser.add_argument(
        "--regenerate-csvs",
        action="store_true",
        help="Rewrite products/inventory/sales CSVs before seeding",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed for demo history (uses data/demo_history_meta.json when omitted)",
    )
    args = parser.parse_args()
    result = seed_demo_data(
        force=args.force,
        regenerate_csvs=args.regenerate_csvs,
        seed=args.seed,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
