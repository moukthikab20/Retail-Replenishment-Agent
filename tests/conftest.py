"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from database.connection import init_db, reset_engine
from repositories.csv_repository import clear_csv_cache


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_retail_agent.db"
    url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr("config.DATABASE_URL", url)
    monkeypatch.setattr("database.connection.DATABASE_URL", url)
    reset_engine()
    init_db(url)
    clear_csv_cache()
    yield
    reset_engine()
    clear_csv_cache()
