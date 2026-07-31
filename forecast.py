"""Compatibility wrapper — prefer services.forecast_service."""

from __future__ import annotations

from services.forecast_service import (  # noqa: F401
    build_sales_trend,
    compute_average_daily_sales,
)
from services.forecast_service import get_demand_forecast as _get_demand_forecast


def forecast_demand(avg_daily_sales: float, horizon_days: int = 7) -> dict:
    daily_forecast = avg_daily_sales
    total_forecast = daily_forecast * horizon_days
    return {
        "avg_daily_sales": round(avg_daily_sales, 2),
        "daily_forecast": round(daily_forecast, 2),
        "horizon_days": horizon_days,
        "total_forecast": round(total_forecast, 2),
    }
