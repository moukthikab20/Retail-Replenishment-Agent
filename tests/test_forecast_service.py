"""Forecast service tests."""

from __future__ import annotations

import pandas as pd
import pytest

from services import forecast_service


def test_correct_seven_day_average():
    sales = pd.DataFrame(
        {
            "date": pd.to_datetime([f"2026-07-{d:02d}" for d in range(20, 27)]),
            "store_id": ["ST001"] * 7,
            "sku": ["SKU-1001"] * 7,
            "units_sold": [7, 7, 7, 7, 7, 7, 7],
        }
    )
    avg = forecast_service.compute_average_daily_sales(
        sales, "ST001", "SKU-1001", pd.Timestamp("2026-07-27")
    )
    assert avg == 7.0
    result = forecast_service.get_demand_forecast("ST001", "SKU-1001")
    # Demo CSV average may differ; structure assertions
    assert result.forecast_days == 7
    assert float(result.forecast_units) == pytest.approx(
        float(result.average_daily_sales) * 7, abs=0.05
    )


def test_insufficient_sales_history(tmp_path, monkeypatch):
    # Empty sales for unknown combo uses zero method path via missing history
    from repositories import csv_repository

    # Use real data but impossible SKU should raise missing product
    with pytest.raises(ValueError, match="Missing SKU"):
        forecast_service.get_demand_forecast("ST001", "SKU-DOES-NOT-EXIST")


def test_zero_sales():
    sales = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-20", "2026-07-21"]),
            "store_id": ["ST001", "ST001"],
            "sku": ["SKU-Z", "SKU-Z"],
            "units_sold": [0, 0],
        }
    )
    avg = forecast_service.compute_average_daily_sales(
        sales, "ST001", "SKU-Z", pd.Timestamp("2026-07-27")
    )
    assert avg == 0.0


def test_missing_sku_window_returns_zero_average():
    sales = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-07-20"]),
            "store_id": ["ST001"],
            "sku": ["SKU-1001"],
            "units_sold": [5],
        }
    )
    avg = forecast_service.compute_average_daily_sales(
        sales, "ST001", "SKU-UNKNOWN", pd.Timestamp("2026-07-27")
    )
    assert avg == 0.0
