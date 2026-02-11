"""L2 data reader - reads real-time L2 data written by l2-scalping."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)


class L2DataReader:
    """Reads L2 data from parquet files written by l2-scalping in real-time."""

    def __init__(self, base_path: str | None = None):
        if base_path is None:
            data_root = Path(
                os.environ.get("L2_DATA_ROOT", "/home/jacobw/quantstack/data/l2")
            ).expanduser()
            base_path = str(data_root / "l2_maximum" / "features")
        self.base_path = Path(base_path)
        self._cache: dict[str, pd.DataFrame] = {}
        self._cache_date: date | None = None
        self._last_file_mtime: dict[str, float] = {}

    def _get_symbol_path(self, symbol: str, trade_date: date) -> Path:
        """Get path to symbol's L2 data directory."""
        date_str = trade_date.strftime("%Y-%m-%d")
        return self.base_path / f"date={date_str}" / f"symbol={symbol}"

    def _load_latest_data(self, symbol: str, trade_date: date) -> pd.DataFrame | None:
        """Load latest L2 data for symbol, checking for new files."""
        symbol_path = self._get_symbol_path(symbol, trade_date)

        if not symbol_path.exists():
            return None

        parquet_files = sorted(symbol_path.glob("*.parquet"))
        if not parquet_files:
            return None

        # Check if we need to reload (new files or modified)
        latest_file = parquet_files[-1]
        current_mtime = latest_file.stat().st_mtime
        cache_key = f"{symbol}_{trade_date}"

        if (
            cache_key in self._cache
            and self._last_file_mtime.get(cache_key) == current_mtime
        ):
            # Check if there are newer files
            if len(parquet_files) == len(
                [f for f in parquet_files if f.stat().st_mtime <= current_mtime]
            ):
                return self._cache[cache_key]

        # Load all parquet files for today
        try:
            dfs = [pd.read_parquet(f) for f in parquet_files]
            df = pd.concat(dfs, ignore_index=True)
            df = df.sort_values("ts_epoch").reset_index(drop=True)
            self._cache[cache_key] = df
            self._last_file_mtime[cache_key] = current_mtime
            return df
        except Exception as e:
            logger.warning(f"Failed to load L2 data for {symbol}: {e}")
            return None

    def get_latest_snapshot(self, symbol: str, trade_date: date) -> dict | None:
        """Get most recent L2 snapshot for symbol."""
        df = self._load_latest_data(symbol, trade_date)
        if df is None or df.empty:
            return None

        row = df.iloc[-1]
        return {
            "symbol": symbol,
            "timestamp": row.get("ts_epoch", 0),
            "depth_bid": row.get("depth_bid", 0),
            "depth_ask": row.get("depth_ask", 0),
            "mid": row.get("mid", 0),
            "spread": row.get("spread", 0),
            "obi_1": row.get("obi_1", 0),
            "bid": row.get("bid"),
            "ask": row.get("ask"),
        }

    def get_l2_ratio(self, symbol: str, trade_date: date) -> float | None:
        """Get L2 depth ratio (depth_bid / depth_ask) for symbol."""
        snapshot = self.get_latest_snapshot(symbol, trade_date)
        if snapshot is None:
            return None

        depth_bid = snapshot.get("depth_bid", 0)
        depth_ask = snapshot.get("depth_ask", 0)

        if depth_ask <= 0:
            return None

        return depth_bid / depth_ask

    def clear_cache(self) -> None:
        """Clear cached data (call on new trading day)."""
        self._cache.clear()
        self._last_file_mtime.clear()
