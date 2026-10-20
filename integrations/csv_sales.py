"""CSV-backed sales / demand history provider."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from config import AS_OF_DATE, FORECAST_LOOKBACK_DAYS
from integrations.contracts import ProviderHealth, SalesDayRecord, SalesHistoryResult
from repositories import csv_repository

SOURCE_LABEL = "Demo CSV"
PROVIDER_NAME = "CSV Sales Provider"


def _as_of_ts(as_of: datetime | str | pd.Timestamp | None) -> pd.Timestamp:
    if as_of is None:
        return pd.Timestamp(AS_OF_DATE)
    return pd.Timestamp(as_of)


class CSVSalesProvider:
    provider_name = PROVIDER_NAME
    source_label = SOURCE_LABEL

    def __init__(self, data_dir: Path | None = None) -> None:
        self._data_dir = data_dir

    def _frame(self) -> pd.DataFrame:
        return csv_repository.get_sales_frame(self._data_dir)

    def get_sales_history(
        self,
        store_id: str,
        sku: str,
        *,
        lookback_days: int = FORECAST_LOOKBACK_DAYS,
        as_of: datetime | None = None,
    ) -> SalesHistoryResult:
        sales_df = self._frame()
        as_of_ts = _as_of_ts(as_of).normalize()
        window_start = as_of_ts - timedelta(days=lookback_days)
        mask = (
            (sales_df["store_id"] == store_id)
            & (sales_df["sku"] == sku)
            & (sales_df["date"] >= window_start)
            & (sales_df["date"] < as_of_ts)
        )
        window = sales_df.loc[mask, ["date", "units_sold"]].sort_values("date")
        daily = [
            SalesDayRecord(
                date=pd.Timestamp(row.date).to_pydatetime(),
                units_sold=float(row.units_sold),
            )
            for row in window.itertuples(index=False)
        ]
        total = float(window["units_sold"].sum()) if not window.empty else 0.0
        avg = (total / lookback_days) if lookback_days > 0 else 0.0
        history_days = (
            int(window["date"].dt.normalize().nunique()) if not window.empty else 0
        )
        return SalesHistoryResult(
            store_id=store_id,
            sku=sku,
            period_start=window_start.to_pydatetime(),
            period_end=as_of_ts.to_pydatetime(),
            daily_sales=daily,
            average_daily_sales=round(avg, 4),
            source=self.source_label,
            provider_name=self.provider_name,
            updated_at=datetime.now(timezone.utc),
            history_days=history_days,
        )

    def get_recent_sales(
        self,
        store_id: str,
        sku: str,
        *,
        days: int = 14,
        as_of: datetime | None = None,
    ) -> SalesHistoryResult:
        return self.get_sales_history(
            store_id, sku, lookback_days=days, as_of=as_of
        )

    def count_history_days(self, store_id: str, sku: str) -> int:
        sales = self._frame()
        mask = (sales["store_id"] == store_id) & (sales["sku"] == sku)
        subset = sales.loc[mask]
        if subset.empty:
            return 0
        return int(subset["date"].dt.normalize().nunique())

    def health_check(self) -> ProviderHealth:
        try:
            frame = self._frame()
            ok = not frame.empty
            return ProviderHealth(
                ok=ok,
                status="healthy" if ok else "degraded",
                provider_name=self.provider_name,
                source=self.source_label,
                message=(
                    f"Sales Data Source — {self.source_label} "
                    f"({len(frame)} rows)."
                    if ok
                    else f"Sales Data Source — {self.source_label} is empty."
                ),
                details={"row_count": int(len(frame)), "real_pos": False},
            )
        except Exception as exc:  # noqa: BLE001
            return ProviderHealth(
                ok=False,
                status="unavailable",
                provider_name=self.provider_name,
                source=self.source_label,
                message=f"Sales provider unavailable: {exc}",
                details={"real_pos": False},
            )
