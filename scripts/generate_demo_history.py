"""Regenerate expanded demo master CSVs (products / inventory / sales).

Usage:
  python scripts/generate_demo_history.py
  python scripts/generate_demo_history.py --seed 101
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.demo_catalog import DEMO_HISTORY_SEED  # noqa: E402
from services.demo_history_generator import regenerate_all  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate demo history master CSVs")
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help=f"RNG seed for demo history (default: {DEMO_HISTORY_SEED} or last meta seed)",
    )
    args = parser.parse_args()
    result = regenerate_all(seed=args.seed)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
