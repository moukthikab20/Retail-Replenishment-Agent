"""Seven-day demand forecast from trailing average daily sales."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd


def compute_average_daily_sales(
    sales_df: pd.DataFrame,
    store_id: str,
    sku: str,
    as_of_date: pd.Timestamp,
    lookback_days: int = 7,
) -> float:
    """Average units sold per day over the previous `lookback_days` (exclusive of as_of_date)."""
    window_end = as_of_date.normalize()
    window_start = window_end - timedelta(days=lookback_days)

    mask = (
        (sales_df["store_id"] == store_id)
        & (sales_df["sku"] == sku)
        & (sales_df["date"] >= window_start)
        & (sales_df["date"] < window_end)
    )
    window = sales_df.loc[mask, "units_sold"]

    if window.empty:
        return 0.0

    return float(window.sum()) / lookback_days


def forecast_demand(
    avg_daily_sales: float,
    horizon_days: int = 7,
) -> dict:
    """Project demand for the next `horizon_days` using flat average daily sales."""
    daily_forecast = avg_daily_sales
    total_forecast = daily_forecast * horizon_days
    return {
        "avg_daily_sales": round(avg_daily_sales, 2),
        "daily_forecast": round(daily_forecast, 2),
        "horizon_days": horizon_days,
        "total_forecast": round(total_forecast, 2),
    }


def build_sales_trend(
    sales_df: pd.DataFrame,
    store_id: str,
    sku: str,
    as_of_date: pd.Timestamp,
    days: int = 14,
) -> pd.DataFrame:
    """Return daily sales for charting (most recent `days` ending day before as_of_date)."""
    window_end = as_of_date.normalize()
    window_start = window_end - timedelta(days=days)

    mask = (
        (sales_df["store_id"] == store_id)
        & (sales_df["sku"] == sku)
        & (sales_df["date"] >= window_start)
        & (sales_df["date"] < window_end)
    )
    trend = sales_df.loc[mask, ["date", "units_sold"]].copy()
    trend = trend.sort_values("date")
    return trend
