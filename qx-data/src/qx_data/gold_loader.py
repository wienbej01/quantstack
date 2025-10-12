"""Gold loader for read-only access to normalized bars."""

import glob
import os
from typing import List

import pandas as pd

from qx_core.hashers import hash_dataframe


REQUIRED = ["ts", "symbol", "open", "high", "low", "close", "volume"]
OPTIONAL = ["trades", "vwap", "session", "date_et"]


def load_bars(root: str, family: str, symbols: List[str], dates: List[str]) -> pd.DataFrame:
    """Load and normalize bars from Gold parquet files.

    Args:
        root: Path to Gold root directory
        family: Data family (e.g., 'bars_1m')
        symbols: List of symbols to load
        dates: List of date strings in YYYY-MM-DD format

    Returns:
        Normalized DataFrame with canonical schema
    """
    dfs = []
    for symbol in symbols:
        for date in dates:
            paths = _get_parquet_paths(root, family, symbol, date)
            for path in paths:
                try:
                    df = pd.read_parquet(path)
                    if "symbol" not in df.columns:
                        df["symbol"] = symbol
                    dfs.append(df)
                except Exception as e:
                    # Log warning but continue
                    print(f"Warning: failed to read {path}: {e}")

    if not dfs:
        raise RuntimeError("No parquet files could be read")

    combined = pd.concat(dfs, ignore_index=True)
    normalized = _normalize_in_memory(combined)
    return normalized


def _get_parquet_paths(root: str, family: str, symbol: str, date: str) -> List[str]:
    """Get parquet file paths for given symbol and date."""
    year, month, _ = date.split("-")
    if family == "bars_1m":
        # Structure: .../stocks/1m/symbol/year/year-month.parquet
        pattern = os.path.join(root, "stocks", "1m", symbol, year, f"{year}-{month}.parquet")
    else:
        # Structure: .../family/symbol=symbol/date=date/*.parquet
        pattern = os.path.join(root, family, f"symbol={symbol}", f"date={date}", "*.parquet")

    return glob.glob(pattern)


def _normalize_in_memory(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize DataFrame in memory for canonical schema."""
    out = df.copy()
    # Column name standardization
    rename = {"T": "symbol", "t": "ts", "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
    cols_lower = {c: c.lower() for c in out.columns}
    out = out.rename(columns=cols_lower).rename(columns=rename)

    # Ensure required columns
    missing = set(REQUIRED) - set(out.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Types
    if not pd.api.types.is_datetime64_any_dtype(out["ts"]):
        out["ts"] = pd.to_datetime(out["ts"], utc=True, errors="coerce")
    elif out["ts"].dt.tz is None:
        out["ts"] = out["ts"].dt.tz_localize("UTC")
    else:
        out["ts"] = out["ts"].dt.tz_convert("UTC")

    out["symbol"] = out["symbol"].astype(str)
    for col in ["open", "high", "low", "close"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")
    out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0).astype("int64")

    # Sanity checks
    bad_hilo = (out["high"] < out["low"]).sum()
    if bad_hilo > 0:
        print(f"Warning: {bad_hilo} rows have high < low")

    # Sort for determinism
    out = out.sort_values(["symbol", "ts"]).reset_index(drop=True)
    return out