"""Gold 1-minute OHLCV data loader.

Loads 1-minute bar data from ~/gcs-mount/gold/stocks/ directory.
Data is organized as: 1m/{SYMBOL}/{YEAR}/{YEAR}-{MONTH}.parquet

Example: ~/gcs-mount/gold/stocks/1m/A/2024/2024-01.parquet

Temporal integrity: Loader returns data as-is. Backtest engine enforces
no look-ahead by executing trades at next bar's open after signal.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow.dataset as ds

logger = logging.getLogger(__name__)


def _next_month(dt: datetime) -> datetime:
    """Advance to the first day of the next month without day overflow."""
    if dt.month == 12:
        return dt.replace(year=dt.year + 1, month=1, day=1)
    return dt.replace(month=dt.month + 1, day=1)


class GoldLoader:
    """Load 1-minute OHLCV bars from Gold data store."""

    # Base path for Gold data
    DEFAULT_GOLD_PATH = Path("~/gcs-mount/gold/stocks").expanduser()
    # Subdirectory for 1-minute data
    MIN_1_DIR = "1m"

    def __init__(self, gold_path: Optional[Path] = None):
        """Initialize loader with optional custom path.

        Args:
            gold_path: Path to Gold data store. Defaults to ~/gcs-mount/gold/stocks
        """
        self.gold_path = gold_path or self.DEFAULT_GOLD_PATH
        self.min_1_path = self.gold_path / self.MIN_1_DIR

        if not self.min_1_path.exists():
            logger.warning(f"Gold 1m path not found: {self.min_1_path}")

    def load_bars(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        cache: bool = True,
    ) -> pd.DataFrame:
        """Load 1-minute bars for a symbol within date range.

        Args:
            symbol: Ticker symbol (e.g., "AAPL", "SPY")
            start_date: Start date in YYYY-MM-DD format (ET)
            end_date: End date in YYYY-MM-DD format (ET)
            cache: Whether to cache loaded data (not implemented, for future use)

        Returns:
            DataFrame with columns: ts, open, high, low, close, volume,
            session_id, bar_index, ret_1m, log_ret_1m, first_open,
            ret_from_open, cum_volume, cum_dollar_vol, vwap_session,
            bars_in_session, is_first_bar, is_last_bar, prev_session_close

            ts column contains timestamps in ET (America/New_York).

        Raises:
            FileNotFoundError: If symbol or date range not found
            ValueError: If date format is invalid
        """
        # Validate date format
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {e}")

        if start_dt > end_dt:
            raise ValueError(f"start_date {start_date} must be <= end_date {end_date}")

        symbol_path = self.min_1_path / symbol

        if not symbol_path.exists():
            raise FileNotFoundError(
                f"Symbol path not found: {symbol_path}. "
                f"Symbol {symbol} may not exist in Gold data."
            )

        # Collect all parquet files in the date range
        all_dfs = []
        current_date = start_dt

        while current_date <= end_dt:
            year = current_date.year
            month = current_date.month

            # File pattern: {YEAR}/{YEAR}-{MONTH}.parquet
            file_path = symbol_path / str(year) / f"{year}-{month:02d}.parquet"

            if file_path.exists():
                try:
                    # Read parquet file
                    df = pd.read_parquet(file_path)
                    all_dfs.append(df)
                except Exception as e:
                    logger.warning(f"Failed to read {file_path}: {e}")
            else:
                logger.debug(f"File not found: {file_path}")

            # Move to next month
            current_date = _next_month(current_date)

        if not all_dfs:
            raise FileNotFoundError(
                f"No data found for {symbol} between {start_date} and {end_date}"
            )

        # Concatenate all dataframes
        result = pd.concat(all_dfs, ignore_index=True)

        # Filter to date range (ts column is in ET)
        # Convert ts to datetime if it's not already
        if not pd.api.types.is_datetime64_any_dtype(result["ts"]):
            result["ts"] = pd.to_datetime(result["ts"])

        # Filter by date range
        result = result[
            (result["ts"].dt.date >= start_dt.date())
            & (result["ts"].dt.date <= end_dt.date())
        ]

        # Sort by timestamp
        result = result.sort_values("ts").reset_index(drop=True)

        logger.info(
            f"Loaded {len(result)} bars for {symbol} "
            f"from {start_date} to {end_date}"
        )

        return result

    def load_spy_bars(
        self,
        start_date: str,
        end_date: str,
        spy_path: Optional[Path] = None,
    ) -> pd.DataFrame:
        """Load SPY 1-minute bars for regime classification.

        SPY data is at: ~/gcs-mount/stocks/SPY/{YEAR}/SPY_{YEAR}-{MONTH}.parquet

        Args:
            start_date: Start date in YYYY-MM-DD format (ET)
            end_date: End date in YYYY-MM-DD format (ET)
            spy_path: Optional custom path to SPY data

        Returns:
            DataFrame with same schema as load_bars()
        """
        # Default SPY path is different from regular symbols
        if spy_path is None:
            spy_path = Path("~/gcs-mount/stocks/SPY").expanduser()

        # Validate date format
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {e}")

        if not spy_path.exists():
            raise FileNotFoundError(f"SPY path not found: {spy_path}")

        # Collect all parquet files in the date range
        all_dfs = []
        current_date = start_dt

        while current_date <= end_dt:
            year = current_date.year
            month = current_date.month

            # SPY file pattern: {YEAR}/SPY_{YEAR}-{MONTH}.parquet
            file_path = spy_path / str(year) / f"SPY_{year}-{month:02d}.parquet"

            if file_path.exists():
                try:
                    df = pd.read_parquet(file_path)
                    all_dfs.append(df)
                except Exception as e:
                    logger.warning(f"Failed to read {file_path}: {e}")
            else:
                logger.debug(f"SPY file not found: {file_path}")

            # Move to next month
            current_date = _next_month(current_date)

        if not all_dfs:
            raise FileNotFoundError(
                f"No SPY data found between {start_date} and {end_date}"
            )

        # Concatenate and filter
        result = pd.concat(all_dfs, ignore_index=True)

        # SPY data has different column names - standardize them
        # Original: t, o, h, l, c, v, vw, n, session, date_et
        # Standard: ts, open, high, low, close, volume, ...
        column_map = {
            "t": "ts",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
        }
        result = result.rename(columns=column_map)

        # Convert timestamp (t is in milliseconds epoch)
        if "ts" in result.columns:
            result["ts"] = pd.to_datetime(result["ts"], unit="ms")

        result = result[
            (result["ts"].dt.date >= start_dt.date())
            & (result["ts"].dt.date <= end_dt.date())
        ]

        result = result.sort_values("ts").reset_index(drop=True)

        logger.info(f"Loaded {len(result)} SPY bars from {start_date} to {end_date}")

        return result

    def check_data_coverage(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> dict:
        """Check data coverage for a symbol without loading full data.

        Args:
            symbol: Ticker symbol
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format

        Returns:
            Dict with coverage stats:
            - total_bars: Total bars in date range
            - found_bars: Bars actually found
            - coverage_pct: Percentage coverage
            - missing_dates: List of dates with no data
        """
        try:
            df = self.load_bars(symbol, start_date, end_date)
            found_bars = len(df)

            # Calculate expected bars (6.5 hours * 60 minutes = 390 bars per day)
            # Excluding weekends and holidays
            # Approximate: 390 bars per trading day
            trading_days = pd.bdate_range(start_date, end_date)
            expected_bars = len(trading_days) * 390

            coverage_pct = (
                (found_bars / expected_bars * 100) if expected_bars > 0 else 0
            )

            # Find missing dates (dates with zero bars)
            if found_bars > 0:
                df["date"] = df["ts"].dt.date
                dates_with_data = set(df["date"].unique())
                all_dates = set(trading_days.date)
                missing_dates = sorted(all_dates - dates_with_data)
            else:
                missing_dates = []

            return {
                "total_bars": expected_bars,
                "found_bars": found_bars,
                "coverage_pct": round(coverage_pct, 2),
                "missing_dates": missing_dates,
            }

        except Exception as e:
            logger.error(f"Error checking coverage for {symbol}: {e}")
            return {
                "total_bars": 0,
                "found_bars": 0,
                "coverage_pct": 0,
                "missing_dates": [],
                "error": str(e),
            }
