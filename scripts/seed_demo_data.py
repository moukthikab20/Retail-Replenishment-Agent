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

from services.demo_data_service import seed_demo_data  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed demo workflow data (idempotent)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Create sample recommendations even if already seeded",
    )
    args = parser.parse_args()
    result = seed_demo_data(force=args.force)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
