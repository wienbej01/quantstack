"""Trade flow and microstructure features.

Features for analyzing order flow and trading activity:
- Trade imbalance (buy vs sell volume pressure)
- Relative volume (RVOL)
- Sweep detection (multi-level executions)

Note: Full trade tape data required for some features.
L2-derived flow features use book depth changes as proxy.
"""

import logging
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_trade_imbalance(
    bars: pd.DataFrame,
    period: int = 1,
) -> pd.Series:
    """Compute trade imbalance from OHLCV bars.

    Uses candle position as proxy for buy/sell pressure:
    - Close near high = buying pressure (imbalance > 0)
    - Close near low = selling pressure (imbalance < 0)

    Imbalance = (close - mid_hl) / (high - low)
    Where mid_hl = (high + low) / 2

    Args:
        bars: DataFrame with columns: high, low, close
        period: Period for rolling aggregation (default: 1)

    Returns:
        Series with trade imbalance values, range [-1, 1]
    """
    required_cols = ["high", "low", "close"]
    for col in required_cols:
        if col not in bars.columns:
            raise ValueError(f"Missing required column: {col}")

    # Mid of high-low range
    mid_hl = (bars["high"] + bars["low"]) / 2

    # Range
    hl_range = bars["high"] - bars["low"]

    # Imbalance (close relative to mid)
    imbalance = (bars["close"] - mid_hl) / hl_range

    # Handle zero range
    imbalance = imbalance.fillna(0)

    # Rolling sum over period
    if period > 1:
        imbalance = imbalance.rolling(window=period).sum() / period

    return imbalance


def compute_rvol(
    bars: pd.DataFrame,
    baseline_period: int = 20,
) -> pd.Series:
    """Compute Relative Volume (RVOL).

    RVOL = current volume / average volume over baseline period
    Values > 1: Higher than normal volume
    Values < 1: Lower than normal volume

    Args:
        bars: DataFrame with columns: volume
        baseline_period: Period for average volume calculation (default: 20)

    Returns:
        Series with RVOL values
    """
    if "volume" not in bars.columns:
        raise ValueError("Missing required column: volume")

    # Average volume
    avg_volume = bars["volume"].rolling(window=baseline_period).mean()

    # RVOL
    rvol = bars["volume"] / avg_volume

    return rvol.fillna(1.0)


def compute_volume_weighted_imbalance(
    bars: pd.DataFrame,
    period: int = 1,
) -> pd.Series:
    """Compute volume-weighted trade imbalance.

    Similar to trade_imbalance but weighted by volume.
    Higher volume + directional move = stronger signal.

    Args:
        bars: DataFrame with columns: high, low, close, volume
        period: Period for rolling aggregation

    Returns:
        Series with volume-weighted imbalance
    """
    required_cols = ["high", "low", "close", "volume"]
    for col in required_cols:
        if col not in bars.columns:
            raise ValueError(f"Missing required column: {col}")

    # Trade imbalance
    mid_hl = (bars["high"] + bars["low"]) / 2
    hl_range = bars["high"] - bars["low"]
    imbalance = (bars["close"] - mid_hl) / hl_range.fillna(1)
    imbalance = imbalance.fillna(0)

    # Volume-weighted
    vw_imbalance = imbalance * bars["volume"]

    # Rolling sum
    if period > 1:
        vw_imbalance = vw_imbalance.rolling(window=period).sum()
        volume_sum = bars["volume"].rolling(window=period).sum()
        vw_imbalance = vw_imbalance / volume_sum

    return vw_imbalance.fillna(0)


def detect_sweep(
    snapshot: pd.Series,
    levels: int = 3,
) -> dict:
    """Detect order book sweep (multi-level execution).

    A sweep occurs when a large order executes through multiple
    price levels, leaving the book thin on that side.

    Detection: Check if bid/ask sizes decline monotonically
    across levels (indicating consumption).

    Note: This is a simplified detection using L2 snapshots.
    True sweep detection requires tracking trades vs quotes.

    Args:
        snapshot: L2 snapshot as pandas Series
        levels: Number of levels to check (default: 3)

    Returns:
        Dict with keys:
        - bid_sweep_detected: bool
        - ask_sweep_detected: bool
        - bid_slope_trend: str ('declining', 'flat', 'increasing')
        - ask_slope_trend: str
    """
    bid_sizes = []
    ask_sizes = []

    for i in range(1, levels + 1):
        bid_sz = snapshot.get(f"bid_sz_{i}", 0) or 0
        ask_sz = snapshot.get(f"ask_sz_{i}", 0) or 0

        if pd.isna(bid_sz):
            bid_sz = 0
        if pd.isna(ask_sz):
            ask_sz = 0

        bid_sizes.append(bid_sz)
        ask_sizes.append(ask_sizes)

    # Detect monotonic decline
    def _detect_trend(sizes: List[float]) -> str:
        if len(sizes) < 2:
            return "flat"

        # Check if strictly declining
        declining = all(sizes[i] > sizes[i+1] for i in range(len(sizes) - 1))

        # Check if strictly increasing
        increasing = all(sizes[i] < sizes[i+1] for i in range(len(sizes) - 1))

        if declining:
            return "declining"
        elif increasing:
            return "increasing"
        else:
            return "flat"

    bid_trend = _detect_trend(bid_sizes)
    ask_trend = _detect_trend(ask_sizes)

    # Sweep = declining sizes (being consumed)
    bid_sweep = bid_trend == "declining"
    ask_sweep = ask_trend == "declining"

    return {
        "bid_sweep_detected": bid_sweep,
        "ask_sweep_detected": ask_sweep,
        "bid_slope_trend": bid_trend,
        "ask_slope_trend": ask_trend,
    }


def compute_order_flow_aggression(
    bars: pd.DataFrame,
    short_period: int = 5,
    long_period: int = 20,
) -> pd.DataFrame:
    """Compute order flow aggression metrics.

    Aggressive buyers push prices up (close > open)
    Aggressive sellers push prices down (close < open)

    Args:
        bars: DataFrame with OHLCV data
        short_period: Short-term aggregation period
        long_period: Long-term aggregation period

    Returns:
        DataFrame with columns:
        - aggression_short: Short-term buy/sell pressure
        - aggression_long: Long-term buy/sell pressure
        - aggression_delta: Difference (short - long)
    """
    required_cols = ["open", "close", "volume"]
    for col in required_cols:
        if col not in bars.columns:
            raise ValueError(f"Missing required column: {col}")

    result = pd.DataFrame(index=bars.index)

    # Price change (direction)
    price_change = bars["close"] - bars["open"]

    # Volume-weighted direction
    direction = price_change * bars["volume"]

    # Short-term aggregation
    result["aggression_short"] = direction.rolling(window=short_period).sum()
    result["aggression_short"] = (
        result["aggression_short"] /
        bars["volume"].rolling(window=short_period).sum()
    )

    # Long-term aggregation
    result["aggression_long"] = direction.rolling(window=long_period).sum()
    result["aggression_long"] = (
        result["aggression_long"] /
        bars["volume"].rolling(window=long_period).sum()
    )

    # Delta
    result["aggression_delta"] = result["aggression_short"] - result["aggression_long"]

    return result.fillna(0)


def compute_tick_imbalance(
    bars: pd.DataFrame,
    period: int = 1,
) -> pd.Series:
    """Compute tick imbalance (upticks vs downticks).

    Uses price changes from open to close as proxy for ticks.

    Args:
        bars: DataFrame with columns: open, close
        period: Period for rolling aggregation

    Returns:
        Series with tick imbalance, range [-1, 1]
    """
    required_cols = ["open", "close"]
    for col in required_cols:
        if col not in bars.columns:
            raise ValueError(f"Missing required column: {col}")

    # Tick direction
    tick_direction = np.sign(bars["close"] - bars["open"])

    # Rolling sum
    if period > 1:
        tick_sum = tick_direction.rolling(window=period).sum()
        imbalance = tick_sum / period
    else:
        imbalance = tick_direction

    return imbalance.fillna(0)


def compute_all_flow_features(
    bars: pd.DataFrame,
    rvol_baseline: int = 20,
    aggression_short: int = 5,
    aggression_long: int = 20,
) -> pd.DataFrame:
    """Compute all flow-based features for a DataFrame of bars.

    Args:
        bars: DataFrame with OHLCV data
        rvol_baseline: Baseline period for RVOL
        aggression_short: Short period for aggression
        aggression_long: Long period for aggression

    Returns:
        DataFrame with all flow features added as columns
    """
    result = bars.copy()

    # Trade imbalance
    result["trade_imbalance_1"] = compute_trade_imbalance(result, period=1)
    result["trade_imbalance_5"] = compute_trade_imbalance(result, period=5)
    result["trade_imbalance_20"] = compute_trade_imbalance(result, period=20)

    # RVOL
    result["rvol"] = compute_rvol(result, baseline_period=rvol_baseline)

    # Volume-weighted imbalance
    result["vw_imbalance"] = compute_volume_weighted_imbalance(result, period=1)
    result["vw_imbalance_5"] = compute_volume_weighted_imbalance(result, period=5)

    # Order flow aggression
    aggression_df = compute_order_flow_aggression(
        result,
        short_period=aggression_short,
        long_period=aggression_long,
    )
    result["aggression_short"] = aggression_df["aggression_short"]
    result["aggression_long"] = aggression_df["aggression_long"]
    result["aggression_delta"] = aggression_df["aggression_delta"]

    # Tick imbalance
    result["tick_imbalance"] = compute_tick_imbalance(result, period=1)
    result["tick_imbalance_5"] = compute_tick_imbalance(result, period=5)

    return result
