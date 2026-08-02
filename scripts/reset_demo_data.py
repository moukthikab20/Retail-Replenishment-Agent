"""Administrator reset of workflow demo data.

Usage:
  python scripts/reset_demo_data.py --actor admin.demo --role administrator
  python scripts/reset_demo_data.py --actor admin.demo --role administrator --reseed
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.demo_data_service import reset_and_seed, reset_demo_workflow_data  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset demo workflow tables")
    parser.add_argument("--actor", default="admin.demo")
    parser.add_argument("--role", default="administrator")
    parser.add_argument(
        "--reseed",
        action="store_true",
        help="Seed sample recommendations after reset",
    )
    args = parser.parse_args()
    if args.reseed:
        result = reset_and_seed(actor=args.actor, actor_role=args.role)
    else:
        result = reset_demo_workflow_data(actor=args.actor, actor_role=args.role)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
