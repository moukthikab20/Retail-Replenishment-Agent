"""Seven-day demand forecasting service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

from config import AS_OF_DATE, FORECAST_HORIZON_DAYS, FORECAST_LOOKBACK_DAYS
from models.forecast import ForecastResult
from repositories import csv_repository


def compute_average_daily_sales(
    sales_df: pd.DataFrame,
    store_id: str,
    sku: str,
    as_of_date: pd.Timestamp,
    lookback_days: int = FORECAST_LOOKBACK_DAYS,
) -> float:
    """Average units sold per day over the previous lookback window (exclusive of as_of_date)."""
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


def build_sales_trend(
    sales_df: pd.DataFrame,
    store_id: str,
    sku: str,
    as_of_date: pd.Timestamp,
    days: int = 14,
) -> pd.DataFrame:
    window_end = as_of_date.normalize()
    window_start = window_end - timedelta(days=days)
    mask = (
        (sales_df["store_id"] == store_id)
        & (sales_df["sku"] == sku)
        & (sales_df["date"] >= window_start)
        & (sales_df["date"] < window_end)
    )
    trend = sales_df.loc[mask, ["date", "units_sold"]].copy()
    return trend.sort_values("date")


def get_demand_forecast(
    store_id: str,
    sku: str,
    *,
    as_of_date: str | pd.Timestamp | None = None,
    horizon_days: int = FORECAST_HORIZON_DAYS,
    data_dir: Path | None = None,
) -> ForecastResult:
    product = csv_repository.get_product(sku, data_dir)
    if product is None:
        raise ValueError(f"Missing SKU: {sku}")

    sales_df = csv_repository.get_sales_frame(data_dir)
    as_of = pd.Timestamp(as_of_date or AS_OF_DATE)
    avg_daily = compute_average_daily_sales(sales_df, store_id, sku, as_of)
    avg_rounded = round(avg_daily, 2)
    forecast_units = round(avg_rounded * horizon_days, 2)
    history = sales_df.loc[(sales_df["store_id"] == store_id) & (sales_df["sku"] == sku)]
    method = "trailing_average" if not history.empty else "insufficient_data_zero"

    return ForecastResult(
        store_id=store_id,
        sku=sku,
        forecast_days=horizon_days,
        average_daily_sales=Decimal(str(avg_rounded)),
        forecast_units=Decimal(str(forecast_units)),
        method=method,
        generated_at=datetime.now(timezone.utc),
    )
