"""L2 order book data loader.

Loads L2 order book snapshots from ~/quantstack/data/l2/l2_maximum/raw/.
Data is organized as: raw/date={YYYY-MM-DD}/symbol={SYMBOL}/*.parquet

Example: ~/quantstack/data/l2/l2_maximum/raw/date=2025-12-19/symbol=LUV/part_*.parquet

Schema includes:
- ts_utc, ts_epoch, date_et, symbol, exchange, has_depth
- bid/ask prices and sizes for 10 levels (bid_px_1, bid_sz_1, ..., ask_px_10, ask_sz_10)
- L1 fields: l1_bid, l1_ask, l1_last, l1_mid, l1_spread

Temporal integrity: Loader returns snapshots as-is. Backtest engine enforces
no look-ahead by executing trades at next bar's open after signal.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class L2Loader:
    """Load L2 order book snapshots from L2 data store."""

    # Base path for L2 data
    DEFAULT_L2_PATH = (
        Path(os.environ.get("L2_DATA_ROOT", "/home/jacobw/quantstack/data/l2"))
        .expanduser()
        / "l2_maximum"
        / "raw"
    )

    def __init__(self, l2_path: Optional[Path] = None):
        """Initialize loader with optional custom path.

        Args:
            l2_path: Path to L2 data store. Defaults to ~/quantstack/data/l2/l2_maximum/raw
        """
        self.l2_path = l2_path or self.DEFAULT_L2_PATH

        if not self.l2_path.exists():
            logger.warning(f"L2 path not found: {self.l2_path}")

    def load_snapshots(
        self,
        symbol: str,
        date: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        min_depth: int = 0,
    ) -> pd.DataFrame:
        """Load L2 snapshots for a symbol on a specific date.

        Args:
            symbol: Ticker symbol (e.g., "AAPL", "LUV")
            date: Date in YYYY-MM-DD format
            start_time: Optional start time in HH:MM:SS format (ET)
            end_time: Optional end time in HH:MM:SS format (ET)
            min_depth: Minimum depth levels required (0-10). Filters snapshots with fewer levels.

        Returns:
            DataFrame with L2 snapshot data including:
            - ts_utc: Timestamp in UTC
            - ts_epoch: Timestamp as epoch nanoseconds
            - date_et: Date in ET
            - symbol: Ticker symbol
            - exchange: Exchange (SMART, etc.)
            - has_depth: Whether depth data is available
            - bid_px_1-10, bid_sz_1-10: Bid prices and sizes for 10 levels
            - ask_px_1-10, ask_sz_1-10: Ask prices and sizes for 10 levels
            - l1_bid, l1_ask, l1_mid, l1_spread: L1 aggregated quotes

        Raises:
            FileNotFoundError: If symbol/date not found
            ValueError: If date format is invalid
        """
        # Validate date format
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {e}")

        # Construct directory path
        symbol_dir = self.l2_path / f"date={date}" / f"symbol={symbol}"

        if not symbol_dir.exists():
            raise FileNotFoundError(
                f"L2 data not found: {symbol_dir}. "
                f"Symbol {symbol} may not have L2 data for {date}."
            )

        # Find all parquet files in the symbol directory
        parquet_files = list(symbol_dir.glob("*.parquet"))

        if not parquet_files:
            raise FileNotFoundError(
                f"No parquet files found in {symbol_dir}"
            )

        # Load and concatenate all parquet files
        all_dfs = []
        for file_path in parquet_files:
            try:
                df = pd.read_parquet(file_path)
                if "symbol" not in df.columns:
                    df["symbol"] = symbol
                all_dfs.append(df)
            except Exception as e:
                logger.warning(f"Failed to read {file_path}: {e}")

        if not all_dfs:
            raise FileNotFoundError(
                f"Failed to load any data from {symbol_dir}"
            )

        # Concatenate all dataframes
        result = pd.concat(all_dfs, ignore_index=True)

        # Convert ts_utc to datetime if needed
        if not pd.api.types.is_datetime64_any_dtype(result['ts_utc']):
            result['ts_utc'] = pd.to_datetime(result['ts_utc'])

        # Filter by time range if specified
        if start_time or end_time:
            # Extract time from ts_utc
            result['time'] = result['ts_utc'].dt.time

            if start_time:
                try:
                    start_dt = datetime.strptime(start_time, "%H:%M:%S").time()
                    result = result[result['time'] >= start_dt]
                except ValueError as e:
                    raise ValueError(f"Invalid start_time format. Use HH:MM:SS: {e}")

            if end_time:
                try:
                    end_dt = datetime.strptime(end_time, "%H:%M:%S").time()
                    result = result[result['time'] <= end_dt]
                except ValueError as e:
                    raise ValueError(f"Invalid end_time format. Use HH:MM:SS: {e}")

            # Drop temporary time column
            result = result.drop(columns=['time'])

        # Filter by minimum depth if specified
        if min_depth > 0:
            # Count how many price levels have non-NaN values
            bid_cols = [f"bid_px_{i}" for i in range(1, 11)]
            ask_cols = [f"ask_px_{i}" for i in range(1, 11)]

            # Count non-NaN bid and ask levels
            result['_bid_levels'] = result[bid_cols].notna().sum(axis=1)
            result['_ask_levels'] = result[ask_cols].notna().sum(axis=1)

            # Keep snapshots with at least min_depth levels on both sides
            result = result[
                (result['_bid_levels'] >= min_depth) &
                (result['_ask_levels'] >= min_depth)
            ]

            # Drop temporary columns
            result = result.drop(columns=['_bid_levels', '_ask_levels'])

        # Sort by timestamp
        result = result.sort_values('ts_utc').reset_index(drop=True)

        logger.info(
            f"Loaded {len(result)} L2 snapshots for {symbol} on {date}"
        )

        return result

    def load_snapshots_multi(
        self,
        symbols: List[str],
        date: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> pd.DataFrame:
        """Load L2 snapshots for multiple symbols on a single date.

        Args:
            symbols: List of ticker symbols
            date: Date in YYYY-MM-DD format
            start_time: Optional start time in HH:MM:SS format
            end_time: Optional end time in HH:MM:SS format

        Returns:
            DataFrame with all snapshots for all symbols, with symbol column added
        """
        all_dfs = []

        for symbol in symbols:
            try:
                df = self.load_snapshots(symbol, date, start_time, end_time)
                all_dfs.append(df)
            except FileNotFoundError as e:
                logger.warning(f"Skipping {symbol} for {date}: {e}")
            except Exception as e:
                logger.error(f"Error loading {symbol} for {date}: {e}")

        if not all_dfs:
            return pd.DataFrame()

        result = pd.concat(all_dfs, ignore_index=True)
        result = result.sort_values(['ts_utc', 'symbol']).reset_index(drop=True)

        logger.info(
            f"Loaded {len(result)} total L2 snapshots for {len(symbols)} symbols on {date}"
        )

        return result

    def get_available_dates(self) -> List[str]:
        """Get list of available dates in L2 data.

        Returns:
            List of dates in YYYY-MM-DD format
        """
        if not self.l2_path.exists():
            return []

        # Find all date= directories
        date_dirs = [d for d in self.l2_path.iterdir() if d.is_dir() and d.name.startswith("date=")]

        # Extract dates
        dates = []
        for date_dir in sorted(date_dirs):
            date_str = date_dir.name.replace("date=", "")
            dates.append(date_str)

        return dates

    def get_available_symbols(self, date: str) -> List[str]:
        """Get list of available symbols for a specific date.

        Args:
            date: Date in YYYY-MM-DD format

        Returns:
            List of symbol strings
        """
        date_dir = self.l2_path / f"date={date}"

        if not date_dir.exists():
            return []

        # Find all symbol= directories
        symbol_dirs = [d for d in date_dir.iterdir() if d.is_dir() and d.name.startswith("symbol=")]

        # Extract symbols
        symbols = []
        for symbol_dir in sorted(symbol_dirs):
            symbol_str = symbol_dir.name.replace("symbol=", "")
            symbols.append(symbol_str)

        return symbols

    def check_coverage(
        self,
        date: str,
        symbol: Optional[str] = None,
    ) -> dict:
        """Check L2 data coverage for a date or symbol.

        Args:
            date: Date in YYYY-MM-DD format
            symbol: Optional symbol to check. If None, checks all symbols for the date.

        Returns:
            Dict with coverage stats:
            - date: Date checked
            - symbol: Symbol checked (None if all symbols)
            - total_symbols: Total symbols available for date
            - snapshots_loaded: Number of snapshots loaded
            - has_depth_pct: Percentage of snapshots with depth data
        """
        try:
            if symbol:
                df = self.load_snapshots(symbol, date)
                total_symbols = 1
            else:
                symbols = self.get_available_symbols(date)
                if not symbols:
                    return {
                        "date": date,
                        "symbol": symbol,
                        "total_symbols": 0,
                        "snapshots_loaded": 0,
                        "has_depth_pct": 0,
                    }
                df = self.load_snapshots_multi(symbols, date)
                total_symbols = len(symbols)

            if df.empty:
                return {
                    "date": date,
                    "symbol": symbol,
                    "total_symbols": total_symbols,
                    "snapshots_loaded": 0,
                    "has_depth_pct": 0,
                }

            # Calculate percentage with depth
            has_depth_pct = (df['has_depth'].sum() / len(df) * 100) if len(df) > 0 else 0

            return {
                "date": date,
                "symbol": symbol,
                "total_symbols": total_symbols,
                "snapshots_loaded": len(df),
                "has_depth_pct": round(has_depth_pct, 2),
            }

        except Exception as e:
            logger.error(f"Error checking coverage for {date}, {symbol}: {e}")
            return {
                "date": date,
                "symbol": symbol,
                "total_symbols": 0,
                "snapshots_loaded": 0,
                "has_depth_pct": 0,
                "error": str(e),
            }
