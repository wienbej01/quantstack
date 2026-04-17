"""L2 order book data loader with multi-location support.

Supports loading L2 data from multiple sources:
1. Old location: ~/quantstack/data/l2/l2_maximum/raw/ (full order book depth)
2. New location: ~/quantstack-v2/data/l2/l2_maximum/ (raw and pre-computed features)

Data organization:
- Raw: l2_maximum/raw/date={YYYY-MM-DD}/symbol={SYMBOL}/*.parquet
- Features: l2_maximum/features/date={YYYY-MM-DD}/symbol={SYMBOL}/*.parquet

Schema (raw):
- ts_utc, ts_epoch, date_et, symbol, exchange, has_depth
- bid/ask prices and sizes for 10 levels (bid_px_1, bid_sz_1, ..., ask_px_10, ask_sz_10)
- L1 fields: l1_bid, l1_ask, l1_last, l1_mid, l1_spread

Schema (features):
- ts_utc, ts_epoch, date_et
- mid, spread, obi_1, obi_5 (order book imbalance)
- depth_bid, depth_ask, pressure
- bid, ask, bid_size, ask_size

Temporal integrity: Loader returns snapshots as-is. Backtest engine enforces
no look-ahead by executing trades at next bar's open after signal.
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Literal, Optional, Sequence, Tuple

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class L2Source:
    """Configuration for an L2 data source."""

    path: Path
    source_type: Literal["raw", "features"]
    name: str
    priority: int  # Lower = higher priority


class L2Loader:
    """Load L2 order book snapshots from multiple L2 data stores.

    Supports automatic fallback between data sources:
    1. Tries quantstack-v2 first (newer data, more symbols)
    2. Falls back to quantstack if not found
    3. Supports both raw depth and pre-computed features
    """

    # Default L2 data sources (tried in priority order)
    DEFAULT_SOURCES = [
        # New location - features (pre-computed, faster access)
        L2Source(
            path=Path("~/quantstack-v2/data/l2/l2_maximum/features").expanduser(),
            source_type="features",
            name="quantstack-v2-features",
            priority=1,
        ),
        # New location - raw (full depth)
        L2Source(
            path=Path("~/quantstack-v2/data/l2/l2_maximum/raw").expanduser(),
            source_type="raw",
            name="quantstack-v2-raw",
            priority=2,
        ),
        # Old location - raw (full depth, legacy)
        L2Source(
            path=Path("~/quantstack/data/l2/l2_maximum/raw").expanduser(),
            source_type="raw",
            name="quantstack-raw",
            priority=3,
        ),
    ]

    def __init__(
        self,
        sources: Optional[List[L2Source]] = None,
        prefer_features: bool = True,
    ):
        """Initialize loader with optional custom sources.

        Args:
            sources: List of L2Source configs. Defaults to built-in sources.
            prefer_features: If True, prioritize features over raw for same priority.
        """
        self.sources = sources or self.DEFAULT_SOURCES.copy()

        # Sort by priority
        self.sources.sort(key=lambda s: s.priority)

        # If prefer_features, prioritize feature sources
        if prefer_features:
            self.sources.sort(key=lambda s: (s.source_type != "features", s.priority))

        logger.info(f"Initialized L2Loader with {len(self.sources)} sources")
        for src in self.sources:
            exists = src.path.exists()
            logger.info(
                f"  [{src.priority}] {src.name}: {src.path} - {'OK' if exists else 'NOT FOUND'}"
            )

    def _find_data_path(
        self,
        symbol: str,
        date: str,
        source_type: Optional[Literal["raw", "features", "any"]] = None,
    ) -> Tuple[Path, L2Source]:
        """Find data path for symbol/date across all sources.

        Args:
            symbol: Ticker symbol
            date: Date in YYYY-MM-DD format
            source_type: Preferred source type ("raw", "features", or "any")

        Returns:
            Tuple of (directory_path, source_config)

        Raises:
            FileNotFoundError: If data not found in any source
        """
        # Filter sources by type if specified
        if source_type and source_type != "any":
            filtered_sources = [s for s in self.sources if s.source_type == source_type]
            if not filtered_sources:
                raise ValueError(f"No sources found for type: {source_type}")
            sources_to_try = filtered_sources
        else:
            sources_to_try = self.sources

        # Try each source in priority order
        for source in sources_to_try:
            symbol_dir = source.path / f"date={date}" / f"symbol={symbol}"
            if symbol_dir.exists():
                parquet_files = list(symbol_dir.glob("*.parquet"))
                if parquet_files:
                    logger.debug(f"Found data in {source.name} for {symbol} on {date}")
                    return symbol_dir, source

        # Not found in any source
        raise FileNotFoundError(
            f"L2 data not found for {symbol} on {date} in any source. "
            f"Tried: {[s.name for s in sources_to_try]}"
        )

    @staticmethod
    def _is_business_date(date_str: str) -> bool:
        """Return True when a YYYY-MM-DD string falls on a weekday."""
        try:
            return pd.Timestamp(date_str).dayofweek < 5
        except Exception:
            return False

    @staticmethod
    def _symbol_dir_has_parquet(symbol_dir: Path) -> bool:
        """Require at least one parquet file before treating a symbol-dir as usable."""
        return symbol_dir.is_dir() and any(symbol_dir.glob("*.parquet"))

    def load_snapshots(
        self,
        symbol: str,
        date: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        min_depth: int = 0,
        source_type: Optional[Literal["raw", "features", "any"]] = None,
        columns: Optional[Sequence[str]] = None,
    ) -> pd.DataFrame:
        """Load L2 snapshots for a symbol on a specific date.

        Args:
            symbol: Ticker symbol (e.g., "AAPL", "LUV")
            date: Date in YYYY-MM-DD format
            start_time: Optional start time in HH:MM:SS format (ET)
            end_time: Optional end time in HH:MM:SS format (ET)
            min_depth: Minimum depth levels required (0-10). Only applies to raw data.
            source_type: Preferred source type ("raw", "features", or "any")
            columns: Optional subset of columns to load from parquet

        Returns:
            DataFrame with L2 snapshot data. Schema depends on source:
            - Raw: Full order book with bid_px_1-10, bid_sz_1-10, ask_px_1-10, ask_sz_1-10
            - Features: Pre-computed features (mid, spread, obi_1, obi_5, depth_bid, depth_ask, pressure)

        Raises:
            FileNotFoundError: If symbol/date not found
            ValueError: If date format is invalid
        """
        # Validate date format
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"Invalid date format. Use YYYY-MM-DD: {e}")

        # Find data path
        symbol_dir, source = self._find_data_path(symbol, date, source_type)

        # Find all parquet files in the symbol directory
        parquet_files = list(symbol_dir.glob("*.parquet"))

        if not parquet_files:
            raise FileNotFoundError(f"No parquet files found in {symbol_dir}")

        # Load and concatenate all parquet files
        all_dfs = []
        for file_path in parquet_files:
            try:
                df = pd.read_parquet(
                    file_path, columns=list(columns) if columns else None
                )
            except Exception as e:
                if columns and "No match for FieldRef.Name" in str(e):
                    logger.debug(
                        "Retrying %s without column pruning due to schema mismatch",
                        file_path,
                    )
                    df = pd.read_parquet(file_path)
                    present = [col for col in columns if col in df.columns]
                    df = df[present]
                else:
                    logger.warning(f"Failed to read {file_path}: {e}")
                    continue
            try:
                if "symbol" not in df.columns:
                    df["symbol"] = symbol
                all_dfs.append(df)
            except Exception as e:
                logger.warning(f"Failed to read {file_path}: {e}")

        if not all_dfs:
            raise FileNotFoundError(f"Failed to load any data from {symbol_dir}")

        # Drop empty/all-NA frames to avoid future concat dtype changes and pointless work.
        non_empty_frames = [
            df
            for df in all_dfs
            if not df.empty and not df.dropna(axis=1, how="all").empty
        ]
        if not non_empty_frames:
            raise FileNotFoundError(f"Loaded only empty dataframes from {symbol_dir}")

        result = pd.concat(non_empty_frames, ignore_index=True)

        # Add metadata
        result.attrs["source"] = source.name
        result.attrs["source_type"] = source.source_type

        # Convert ts_utc to datetime if needed
        if not pd.api.types.is_datetime64_any_dtype(result["ts_utc"]):
            result["ts_utc"] = pd.to_datetime(
                result["ts_utc"], format="mixed", utc=True
            )

        # Filter by time range if specified
        if start_time or end_time:
            # Extract time from ts_utc
            result["time"] = result["ts_utc"].dt.time

            if start_time:
                try:
                    start_dt = datetime.strptime(start_time, "%H:%M:%S").time()
                    result = result[result["time"] >= start_dt]
                except ValueError as e:
                    raise ValueError(f"Invalid start_time format. Use HH:MM:SS: {e}")

            if end_time:
                try:
                    end_dt = datetime.strptime(end_time, "%H:%M:%S").time()
                    result = result[result["time"] <= end_dt]
                except ValueError as e:
                    raise ValueError(f"Invalid end_time format. Use HH:MM:SS: {e}")

            # Drop temporary time column
            result = result.drop(columns=["time"])

        # Filter by minimum depth if specified (only applies to raw data)
        if min_depth > 0 and source.source_type == "raw":
            # Count how many price levels have non-NaN values
            bid_cols = [f"bid_px_{i}" for i in range(1, 11)]
            ask_cols = [f"ask_px_{i}" for i in range(1, 11)]

            # Check if columns exist
            if all(col in result.columns for col in bid_cols + ask_cols):
                # Count non-NaN bid and ask levels
                result["_bid_levels"] = result[bid_cols].notna().sum(axis=1)
                result["_ask_levels"] = result[ask_cols].notna().sum(axis=1)

                # Keep snapshots with at least min_depth levels on both sides
                result = result[
                    (result["_bid_levels"] >= min_depth)
                    & (result["_ask_levels"] >= min_depth)
                ]

                # Drop temporary columns
                result = result.drop(columns=["_bid_levels", "_ask_levels"])

        # Sort by timestamp
        result = result.sort_values("ts_utc").reset_index(drop=True)

        logger.info(
            f"Loaded {len(result)} L2 snapshots for {symbol} on {date} "
            f"from {source.name} ({source.source_type})"
        )

        return result

    def load_snapshots_multi(
        self,
        symbols: List[str],
        date: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        source_type: Optional[Literal["raw", "features", "any"]] = None,
    ) -> pd.DataFrame:
        """Load L2 snapshots for multiple symbols on a single date.

        Args:
            symbols: List of ticker symbols
            date: Date in YYYY-MM-DD format
            start_time: Optional start time in HH:MM:SS format
            end_time: Optional end time in HH:MM:SS format
            source_type: Preferred source type ("raw", "features", or "any")

        Returns:
            DataFrame with all snapshots for all symbols, with symbol column added
        """
        all_dfs = []

        for symbol in symbols:
            try:
                df = self.load_snapshots(
                    symbol, date, start_time, end_time, source_type=source_type
                )
                all_dfs.append(df)
            except FileNotFoundError as e:
                logger.warning(f"Skipping {symbol} for {date}: {e}")
            except Exception as e:
                logger.error(f"Error loading {symbol} for {date}: {e}")

        if not all_dfs:
            return pd.DataFrame()

        result = pd.concat(all_dfs, ignore_index=True)
        result = result.sort_values(["ts_utc", "symbol"]).reset_index(drop=True)

        logger.info(
            f"Loaded {len(result)} total L2 snapshots for {len(symbols)} symbols on {date}"
        )

        return result

    def get_available_dates(
        self,
        source_type: Optional[Literal["raw", "features", "any"]] = None,
        *,
        trading_days_only: bool = True,
    ) -> List[str]:
        """Get list of available dates across all L2 data sources.

        Args:
            source_type: Filter by source type ("raw", "features", or "any")

        Returns:
            Sorted list of unique dates in YYYY-MM-DD format
        """
        all_dates = set()

        for source in self.sources:
            if (
                source_type
                and source_type != "any"
                and source.source_type != source_type
            ):
                continue

            if not source.path.exists():
                continue

            # Find all date= directories
            date_dirs = [
                d
                for d in source.path.iterdir()
                if d.is_dir() and d.name.startswith("date=")
            ]

            for date_dir in date_dirs:
                date_str = date_dir.name.replace("date=", "")
                if trading_days_only and not self._is_business_date(date_str):
                    continue
                symbol_dirs = [
                    d
                    for d in date_dir.iterdir()
                    if d.is_dir()
                    and d.name.startswith("symbol=")
                    and self._symbol_dir_has_parquet(d)
                ]
                if not symbol_dirs:
                    continue
                all_dates.add(date_str)

        return sorted(all_dates)

    def get_available_symbols(
        self,
        date: str,
        source_type: Optional[Literal["raw", "features", "any"]] = None,
    ) -> List[str]:
        """Get list of available symbols for a specific date.

        Args:
            date: Date in YYYY-MM-DD format
            source_type: Filter by source type ("raw", "features", or "any")

        Returns:
            Sorted list of unique symbol strings
        """
        if not self._is_business_date(date):
            return []

        all_symbols = set()

        for source in self.sources:
            if (
                source_type
                and source_type != "any"
                and source.source_type != source_type
            ):
                continue

            date_dir = source.path / f"date={date}"

            if not date_dir.exists():
                continue

            # Find all symbol= directories
            symbol_dirs = [
                d
                for d in date_dir.iterdir()
                if d.is_dir()
                and d.name.startswith("symbol=")
                and self._symbol_dir_has_parquet(d)
            ]

            for symbol_dir in symbol_dirs:
                symbol_str = symbol_dir.name.replace("symbol=", "")
                all_symbols.add(symbol_str)

        return sorted(all_symbols)

    def get_data_inventory(self) -> Dict[str, Dict]:
        """Get inventory of all available data across sources.

        Returns:
            Dict mapping date -> {source_type: {symbols: [], count: N}}
        """
        inventory = {}

        for source in self.sources:
            if not source.path.exists():
                continue

            for date_dir in sorted(source.path.glob("date=*")):
                if not date_dir.is_dir():
                    continue

                date = date_dir.name.replace("date=", "")

                if date not in inventory:
                    inventory[date] = {}

                if source.source_type not in inventory[date]:
                    inventory[date][source.source_type] = {
                        "sources": [],
                        "symbols": [],
                    }

                inventory[date][source.source_type]["sources"].append(source.name)

                # Get symbols
                symbol_dirs = [
                    d
                    for d in date_dir.iterdir()
                    if d.is_dir() and d.name.startswith("symbol=")
                ]
                for symbol_dir in symbol_dirs:
                    symbol = symbol_dir.name.replace("symbol=", "")
                    if symbol not in inventory[date][source.source_type]["symbols"]:
                        inventory[date][source.source_type]["symbols"].append(symbol)

        # Add counts
        for date, data in inventory.items():
            for stype, info in data.items():
                info["count"] = len(info["symbols"])
                info["sources"] = list(set(info["sources"]))

        return inventory

    def check_coverage(
        self,
        date: str,
        symbol: Optional[str] = None,
        source_type: Optional[Literal["raw", "features", "any"]] = None,
    ) -> dict:
        """Check L2 data coverage for a date or symbol.

        Args:
            date: Date in YYYY-MM-DD format
            symbol: Optional symbol to check. If None, checks all symbols for the date.
            source_type: Filter by source type ("raw", "features", or "any")

        Returns:
            Dict with coverage stats:
            - date: Date checked
            - symbol: Symbol checked (None if all symbols)
            - total_symbols: Total symbols available for date
            - snapshots_loaded: Number of snapshots loaded
            - has_depth_pct: Percentage of snapshots with depth data (raw only)
            - source: Which source was used
        """
        try:
            if symbol:
                df = self.load_snapshots(symbol, date, source_type=source_type)
                total_symbols = 1
                source_name = df.attrs.get("source", "unknown")
            else:
                symbols = self.get_available_symbols(date, source_type=source_type)
                if not symbols:
                    return {
                        "date": date,
                        "symbol": symbol,
                        "total_symbols": 0,
                        "snapshots_loaded": 0,
                        "has_depth_pct": 0,
                        "source": "none",
                    }
                df = self.load_snapshots_multi(symbols, date, source_type=source_type)
                total_symbols = len(symbols)
                source_name = (
                    df.attrs.get("source", "unknown") if not df.empty else "none"
                )

            if df.empty:
                return {
                    "date": date,
                    "symbol": symbol,
                    "total_symbols": total_symbols,
                    "snapshots_loaded": 0,
                    "has_depth_pct": 0,
                    "source": source_name,
                }

            # Calculate percentage with depth (raw data only)
            has_depth_pct = 0
            if "has_depth" in df.columns:
                has_depth_pct = (
                    (df["has_depth"].sum() / len(df) * 100) if len(df) > 0 else 0
                )

            return {
                "date": date,
                "symbol": symbol,
                "total_symbols": total_symbols,
                "snapshots_loaded": len(df),
                "has_depth_pct": round(has_depth_pct, 2),
                "source": source_name,
            }

        except Exception as e:
            logger.error(f"Error checking coverage for {date}, {symbol}: {e}")
            return {
                "date": date,
                "symbol": symbol,
                "total_symbols": 0,
                "snapshots_loaded": 0,
                "has_depth_pct": 0,
                "source": "error",
                "error": str(e),
            }


# Create default loader instance for backward compatibility
_default_loader = None


def get_default_loader() -> L2Loader:
    """Get or create the default L2Loader instance."""
    global _default_loader
    if _default_loader is None:
        _default_loader = L2Loader()
    return _default_loader
