"""Seven-day demand forecasting service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

from config import AS_OF_DATE, FORECAST_HORIZON_DAYS, FORECAST_LOOKBACK_DAYS
from integrations.factory import get_product_provider, get_sales_provider
from models.forecast import ForecastResult


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


def get_sales_trend(
    store_id: str,
    sku: str,
    *,
    as_of_date: str | pd.Timestamp | None = None,
    days: int = 14,
) -> pd.DataFrame:
    """Sales trend via SalesProvider — no direct CSV access for UI/pages."""
    history = get_sales_provider().get_recent_sales(
        store_id,
        sku,
        days=days,
        as_of=pd.Timestamp(as_of_date or AS_OF_DATE).to_pydatetime(),
    )
    if not history.daily_sales:
        return pd.DataFrame(columns=["date", "units_sold"])
    return pd.DataFrame(
        [
            {"date": day.date, "units_sold": day.units_sold}
            for day in history.daily_sales
        ]
    ).sort_values("date")


def get_demand_forecast(
    store_id: str,
    sku: str,
    *,
    as_of_date: str | pd.Timestamp | None = None,
    horizon_days: int = FORECAST_HORIZON_DAYS,
    data_dir: Path | None = None,
) -> ForecastResult:
    # data_dir retained for test compatibility; CSV providers use DATA_DIR by default.
    _ = data_dir
    product = get_product_provider().get_product(sku)
    if product is None:
        raise ValueError(f"Missing SKU: {sku}")

    as_of = pd.Timestamp(as_of_date or AS_OF_DATE)
    history = get_sales_provider().get_sales_history(
        store_id,
        sku,
        lookback_days=FORECAST_LOOKBACK_DAYS,
        as_of=as_of.to_pydatetime(),
    )
    avg_daily = float(history.average_daily_sales)
    avg_rounded = round(avg_daily, 2)
    forecast_units = round(avg_rounded * horizon_days, 2)
    method = (
        "trailing_average"
        if history.daily_sales or history.history_days > 0
        else "insufficient_data_zero"
    )

    return ForecastResult(
        store_id=store_id,
        sku=sku,
        forecast_days=horizon_days,
        average_daily_sales=Decimal(str(avg_rounded)),
        forecast_units=Decimal(str(forecast_units)),
        method=method,
        generated_at=datetime.now(timezone.utc),
    )
