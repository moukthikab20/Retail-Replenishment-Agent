"""Console-only perf_step timing for navigation / detail-page investigation."""

from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from typing import Iterator

_LOG = logging.getLogger("retail.perf")
_CONFIGURED = False


def perf_enabled() -> bool:
    return os.environ.get("RETAIL_PERF_TIMING", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _ensure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED or not perf_enabled():
        return
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _CONFIGURED = True


@contextmanager
def perf_step(name: str) -> Iterator[None]:
    """Emit one timing line to console when RETAIL_PERF_TIMING is enabled."""
    if not perf_enabled():
        yield
        return
    _ensure_logging()
    started = time.perf_counter()
    yield
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    _LOG.info("PERF %s: %.1f ms", name, elapsed_ms)


def perf_mark(name: str, started: float) -> None:
    if not perf_enabled():
        return
    _ensure_logging()
    _LOG.info("PERF %s: %.1f ms", name, (time.perf_counter() - started) * 1000.0)
