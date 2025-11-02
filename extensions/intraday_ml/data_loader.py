"""Intraday ML data loader extension (Sprint 2).

This module wraps existing qx-data functionality while providing
Sprint 2 interface for loading and normalizing market data.
"""

import pandas as pd

from qx_core.hashers import hash_dataframe
from qx_data.gold_loader import load_bars


def intraday_ml_load_bars(
    symbols: list[str],
    dates: list[str],
    gold_root: str = "/home/jacobw/gcs-mount",
    family: str = "equities",
    validate: bool = True,
    sort: bool = True,
) -> pd.DataFrame:
    """Load bars from Gold layer using existing qx-data loader.

    Args:
        symbols: List of symbols to load
        dates: List of dates to load
        gold_root: Root path to Gold layer data
        family: Data family (equities, crypto, etc.)
        validate: Whether to validate data integrity
        sort: Whether to sort by symbol and timestamp

    Returns:
        DataFrame with OHLCV data
    """
    return load_bars(
        root=gold_root,
        family=family,
        symbols=symbols,
        dates=dates,
        validate=validate,
        sort=sort,
    )


def intraday_ml_get_data_hash(
    symbols: list[str],
    dates: list[str],
    gold_root: str = "/home/jacobw/gcs-mount",
    family: str = "equities",
) -> str:
    """Get deterministic hash of data loading parameters.

    Args:
        symbols: List of symbols to load
        dates: List of dates to load
        gold_root: Root path to Gold layer data
        family: Data family (equities, crypto, etc.)

    Returns:
        Deterministic hash string
    """
    # Create hash from loading parameters
    params = {
        "symbols": sorted(symbols),
        "dates": sorted(dates),
        "gold_root": gold_root,
        "family": family,
    }

    return hash_dataframe(pd.DataFrame([params]))
