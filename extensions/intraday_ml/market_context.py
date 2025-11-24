"""Market Context Data Loader for Intraday ML.

Loads and aligns broad market instruments (SPY, QQQ, VIX, etc.) to provide
regime awareness features for the pipeline.
"""

from typing import Any

import pandas as pd

from qx_data.gold_loader import load_bars
from .data_prep import _build_date_list, _resolve_loader_options
from .utils import normalize_timestamp_series


def load_market_context(
    start_date: str,
    end_date: str,
    tickers: list[str] | None = None,
    data_loader_config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Load and align market context data (SPY, VIX, etc.) in wide format.

    Args:
        start_date: Start date string (YYYY-MM-DD)
        end_date: End date string (YYYY-MM-DD)
        tickers: List of market tickers. Defaults to ["SPY", "QQQ", "VIX"].
        data_loader_config: Configuration for data loader.

    Returns:
        DataFrame indexed by UTC timestamp.
        Columns are prefixed: 'SPY_open', 'SPY_close', 'VIX_close', etc.
    """
    if tickers is None:
        tickers = ["SPY", "QQQ", "VIX"]

    # 1. Resolve loader options (reuse logic from data_prep for consistency)
    (
        loader_config,
        resample_frequency,
        loader_family,
        market_timezone,
        assume_naive_as_market,
        output_mode,
    ) = _resolve_loader_options(data_loader_config)

    # 2. Load raw data
    dates = _build_date_list(start_date, end_date)
    
    # Ensure we request necessary columns
    columns = loader_config.get("columns", ["open", "high", "low", "close", "volume"])
    
    load_kwargs = {
        "root": loader_config.get("root", "/home/jacobw/gcs-mount"),
        "family": loader_family,
        "symbols": tickers,
        "dates": dates,
        "validate": loader_config.get("validate", True),
        "sort": True,
        "columns": columns
    }

    try:
        raw_df = load_bars(**load_kwargs)
    except RuntimeError:
        # Fallback: try uppercased tickers if lower case fails, or vice versa
        # (This mimics data_prep behavior)
        alt_symbols = [s.upper() for s in tickers]
        if alt_symbols == tickers:
             # If fallback also fails or is same, suppress error and return empty
             print(f"Warning: Failed to load market context data for {tickers}. Returning empty.")
             return pd.DataFrame()
        
        load_kwargs["symbols"] = alt_symbols
        try:
            raw_df = load_bars(**load_kwargs)
        except Exception as e:
            print(f"Warning: Failed to load market context data (fallback): {e}. Returning empty.")
            return pd.DataFrame()
    except Exception as e:
        print(f"Warning: Failed to load market context data: {e}. Returning empty.")
        return pd.DataFrame()

    if raw_df.empty:
        return pd.DataFrame()

    # 3. Normalize Timestamps
    # We enforce output="aware_utc" to ensure alignment with the main pipeline
    raw_df["ts"] = normalize_timestamp_series(
        raw_df["ts"],
        market_tz=market_timezone,
        output="aware_utc",
        assume_naive_as_market=assume_naive_as_market,
    )

    # 4. Pivot to Wide Format
    # We want one row per timestamp, with columns like SPY_close, VIX_close
    pivot_df = raw_df.pivot(index="ts", columns="symbol", values=columns)
    
    # The pivot creates a MultiIndex columns (metric, symbol). Flatten it.
    # e.g. (close, SPY) -> SPY_close
    pivot_df.columns = [f"{symbol}_{metric}" for metric, symbol in pivot_df.columns]
    
    # 5. Resample (if needed) and Forward Fill
    # Market data is crucial context; we assume continuous availability during sessions.
    # Forward filling handles minor sync issues (e.g. VIX updates every 15s, SPY every 1s)
    if resample_frequency:
        # Resample to the target frequency (e.g. 1min, 5min)
        # taking the last value (close) or sum (volume) would be ideal, 
        # but simply taking the last known value is safer for "state" features.
        pivot_df = pivot_df.resample(resample_frequency).last()

    # Forward fill to propagate the last known market state
    # Limit the fill to avoid propagating stale data across days/long gaps
    pivot_df = pivot_df.ffill(limit=None) 
    
    # Drop rows that are still completely empty (e.g. before market open if data starts late)
    pivot_df = pivot_df.dropna(how="all")

    return pivot_df
