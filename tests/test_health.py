"""Health check tests — ensure secrets are never returned."""

from __future__ import annotations

from health import check_health, is_healthy


def test_health_ok_on_sqlite_test_db():
    payload = check_health()
    assert payload["status"] == "ok"
    assert is_healthy() is True
    assert payload["database"]["ok"] is True
    assert payload["demo"]["real_erp"] is False


def test_health_payload_has_no_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value")
    monkeypatch.setattr("config.OPENAI_API_KEY", "sk-test-secret-value")
    monkeypatch.setattr("health.OPENAI_MODEL", "gpt-test")
    # Force re-read path used by _api_key_present
    monkeypatch.setattr("config.DEMO_ACCESS_CODE", "super-secret-access")
    payload = check_health()
    dumped = str(payload)
    assert "sk-test-secret-value" not in dumped
    assert "super-secret-access" not in dumped
    assert "password" not in dumped.lower() or "***" in dumped
    assert payload["openai"]["api_key_present"] is True
    assert "banner" in payload["demo"]
