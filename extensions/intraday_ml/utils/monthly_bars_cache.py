"""Reusable cache for loading monthly Gold bars once per batch."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

import pandas as pd

from qx_data.gold_loader import load_bars

logger = logging.getLogger(__name__)


class MonthlyBarsCache:
    """Load and reuse bars across many day-level operations (e.g., SIP scoring)."""

    def __init__(
        self,
        *,
        root: str,
        family: str = "bars_1m",
        symbols: Iterable[str],
        start_date: str | datetime,
        end_date: str | datetime,
        business_days_only: bool = True,
    ) -> None:
        self.root = root
        self.family = family
        self.symbols = sorted({str(symbol).upper() for symbol in symbols})
        if not self.symbols:
            raise ValueError("MonthlyBarsCache requires at least one symbol.")

        start_ts = pd.to_datetime(start_date)
        end_ts = pd.to_datetime(end_date)
        if end_ts < start_ts:
            raise ValueError("end_date must be greater than or equal to start_date.")

        freq = "B" if business_days_only else "D"
        self._date_index = pd.date_range(start_ts, end_ts, freq=freq)
        if self._date_index.empty:
            raise ValueError("No dates available for the requested cache window.")

        self._date_strings = self._date_index.strftime("%Y-%m-%d").tolist()
        self._bars = self._load_all()

    def _load_all(self) -> pd.DataFrame:
        """Load bars for every requested symbol/date once."""
        logger.info(
            "Loading Gold bars once for %d symbols across %d dates.",
            len(self.symbols),
            len(self._date_strings),
        )
        month_to_dates: dict[str, list[str]] = {}
        for date_str in self._date_strings:
            month_to_dates.setdefault(date_str[:7], []).append(date_str)

        dfs: list[pd.DataFrame] = []
        months = sorted(month_to_dates.items())
        total_months = len(months)
        for idx, (month, dates) in enumerate(months, 1):
            logger.info(
                "Loading month %s for %d symbols (%d/%d)...",
                month,
                len(self.symbols),
                idx,
                total_months,
            )
            try:
                df = load_bars(
                    root=self.root,
                    family=self.family,
                    symbols=self.symbols,
                    dates=dates,
                    validate=True,
                    sort=True,
                )
            except RuntimeError as exc:
                logger.warning("Skipping month %s: %s", month, exc)
                continue

            if df.empty:
                logger.warning("No data returned for month %s.", month)
                continue

            dfs.append(self._normalize_bars(df))
            logger.info(
                "Month %s loaded (%d rows, cumulative %d rows).",
                month,
                len(df),
                sum(len(chunk) for chunk in dfs),
            )

        if not dfs:
            logger.error("No monthly data could be loaded for the requested window.")
            return pd.DataFrame()

        combined = pd.concat(dfs, ignore_index=True)
        logger.info(
            "Finished loading %d rows across %d months.",
            len(combined),
            len(dfs),
        )
        return combined

    @staticmethod
    def _normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
        normalized = df.copy()
        if "symbol" in normalized.columns:
            normalized["symbol"] = normalized["symbol"].astype(str).str.upper()

        ts_series = normalized["ts"].astype("int64")
        max_ts = int(ts_series.max()) if not ts_series.empty else 0
        # Convert microseconds to nanoseconds if needed
        if 0 < max_ts < 10**17:
            ts_series = ts_series * 1000
        normalized["ts"] = ts_series
        return normalized

    def is_empty(self) -> bool:
        """Return True if no bars were loaded."""
        return self._bars.empty

    def available_symbols(self) -> list[str]:
        """Return symbols with at least one loaded row."""
        if self._bars.empty:
            return []
        return sorted(self._bars["symbol"].unique().tolist())

    def get_window(
        self,
        *,
        start_date: str | datetime,
        end_date: str | datetime,
        symbols: Iterable[str] | None = None,
    ) -> pd.DataFrame:
        """Return a filtered view for a specific time window."""
        if self._bars.empty:
            return pd.DataFrame()

        start_ns = self._timestamp_to_int(start_date)
        end_ns = self._timestamp_to_int(end_date)
        if end_ns < start_ns:
            start_ns, end_ns = end_ns, start_ns

        mask = (self._bars["ts"] >= start_ns) & (self._bars["ts"] <= end_ns)
        if symbols:
            requested = {str(symbol).upper() for symbol in symbols}
            mask &= self._bars["symbol"].isin(requested)

        window = self._bars.loc[mask]
        if window.empty:
            return pd.DataFrame()
        return window.copy()

    def _normalize_ts(self, value: str | datetime) -> pd.Timestamp:
        ts = pd.Timestamp(value)
        if ts.tzinfo is not None:
            ts = ts.tz_convert("UTC")
        return ts

    def _timestamp_to_int(self, value: str | datetime) -> int:
        ts = self._normalize_ts(value)
        # Gold bars are stored in nanoseconds, so keep the same unit when comparing.
        return int(ts.value)
