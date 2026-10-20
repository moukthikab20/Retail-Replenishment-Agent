"""Decision factory — strategy selection with fail-fast."""

from __future__ import annotations

from typing import Any

from decision.engine import DecisionEngine
from decision.strategies import STRATEGIES, get_strategy
from integrations.failures import ProviderConfigError

_engine: DecisionEngine | None = None


def validate_decision_strategy_configuration(key: str | None = None) -> str:
    from config import DECISION_STRATEGY as configured

    value = (key if key is not None else configured or "balanced").strip().lower()
    if value not in STRATEGIES:
        available = ", ".join(sorted(STRATEGIES))
        raise ProviderConfigError(
            f"Decision strategy '{value}' is not available in this deployment. "
            f"Supported: {available}.",
            provider_key="decision",
        )
    return value


def get_decision_engine(*, force_new: bool = False) -> DecisionEngine:
    global _engine
    from config import (
        DECISION_CONFIDENCE_FLOOR,
        DECISION_LLM_ADVISOR,
        DECISION_RISK_CEILING,
    )

    strategy = validate_decision_strategy_configuration()
    if _engine is None or force_new:
        _engine = DecisionEngine(
            strategy_name=strategy,
            llm_advisor_enabled=bool(DECISION_LLM_ADVISOR),
            confidence_floor=float(DECISION_CONFIDENCE_FLOOR),
            risk_ceiling=float(DECISION_RISK_CEILING),
        )
    return _engine


def reset_decision_engine() -> None:
    global _engine
    _engine = None


def decision_health() -> dict[str, Any]:
    try:
        from config import (
            DECISION_CONFIDENCE_FLOOR,
            DECISION_ENABLED,
            DECISION_LLM_ADVISOR,
            DECISION_RISK_CEILING,
        )

        strategy = validate_decision_strategy_configuration()
        get_decision_engine()
        get_strategy(strategy)
        return {
            "ok": True,
            "enabled": bool(DECISION_ENABLED),
            "strategy": strategy,
            "llm_advisor": bool(DECISION_LLM_ADVISOR),
            "confidence_floor": float(DECISION_CONFIDENCE_FLOOR),
            "risk_ceiling": float(DECISION_RISK_CEILING),
            "components": {
                "decision_engine": "healthy",
                "decision_strategy": "healthy",
                "scoring_engine": "healthy",
                "decision_explainer": "healthy",
            },
            "message": "Decision Intelligence Engine ready.",
        }
    except Exception as exc:  # noqa: BLE001
        from config import DECISION_ENABLED

        return {
            "ok": False,
            "enabled": bool(DECISION_ENABLED),
            "error": type(exc).__name__,
            "message": str(exc),
            "components": {
                "decision_engine": "unavailable",
                "decision_strategy": "unavailable",
                "scoring_engine": "degraded",
                "decision_explainer": "degraded",
            },
        }
