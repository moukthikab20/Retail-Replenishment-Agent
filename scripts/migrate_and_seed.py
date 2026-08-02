"""Run Alembic migrations then idempotent demo seed (deploy helper)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    upgrade = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT,
        check=False,
    )
    if upgrade.returncode != 0:
        return upgrade.returncode
    seed = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "seed_demo_data.py")],
        cwd=ROOT,
        check=False,
    )
    return seed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
