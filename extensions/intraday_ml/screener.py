"""Intraday ML screener extension (Sprint 4).

This module wraps existing qx-screener functionality while providing
Sprint 4 interface for universe screening and selection.
"""

from typing import Any

import pandas as pd
from qx_core.hashers import hash_dataframe
from qx_screener.sip import ScreenerConfig, SipScreener


def intraday_ml_screen_universe(
    bars: pd.DataFrame,
    config: dict[str, Any] | None = None,
    reference_date: str | None = None,
) -> pd.DataFrame:
    """Screen universe using existing qx-screener SIP functionality.

    Args:
        bars: DataFrame with OHLCV data
        config: Screener configuration parameters
        reference_date: Reference date for ranking (YYYY-MM-DD format)

    Returns:
        DataFrame with screened symbols and rankings
    """
    if config is None:
        config = {}

    # Create screener config
    screener_config = ScreenerConfig(
        top_n=config.get("top_n", 10),
        min_relative_volume=config.get("min_relative_volume", 1.0),
        min_price=config.get("min_price", 10.0),
        max_price=config.get("max_price", 1000.0),
        min_dollar_volume=config.get("min_dollar_volume", 1_000_000),
        lookback_days=config.get("lookback_days", 20),
        volume_window=config.get("volume_window", 30),
        exclude_symbols=config.get("exclude_symbols", []),
    )

    # Apply SIP screening
    screener = SipScreener(screener_config)
    return screener.screen_universe(bars, reference_date)


def intraday_ml_get_screener_hash(
    bars: pd.DataFrame,
    config: dict[str, Any] | None = None,
    reference_date: str | None = None,
) -> str:
    """Get deterministic hash of screener parameters.

    Args:
        bars: Input bars DataFrame
        config: Screener configuration parameters
        reference_date: Reference date for ranking

    Returns:
        Deterministic hash string
    """
    if config is None:
        config = {}

    # Create hash from inputs and screener parameters
    input_hash = hash_dataframe(bars)
    screener_params = {
        "config": config,
        "reference_date": reference_date,
    }
    config_hash = hash_dataframe(pd.DataFrame([screener_params]))

    # Combine hashes
    return f"{input_hash}_{config_hash}"
