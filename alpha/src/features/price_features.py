"""Price-based features computed from OHLCV bars.

Features for:
- VWAP (Volume-Weighted Average Price)
- Returns over multiple periods
- ATR (Average True Range) for volatility
- Session range (high/low of day)

All functions are pure (no side effects) for reproducibility.
"""

import logging
from typing import List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def compute_vwap(bars: pd.DataFrame) -> pd.Series:
    """Compute Volume-Weighted Average Price (VWAP).

    VWAP = sum(price * volume) / sum(volume)
    Uses typical price: (high + low + close) / 3

    Args:
        bars: DataFrame with columns: high, low, close, volume

    Returns:
        Series with VWAP values, same index as input
    """
    required_cols = ["high", "low", "close", "volume"]
    for col in required_cols:
        if col not in bars.columns:
            raise ValueError(f"Missing required column: {col}")

    # Typical price
    typical_price = (bars["high"] + bars["low"] + bars["close"]) / 3

    # VWAP calculation
    vwap = (typical_price * bars["volume"]).cumsum() / bars["volume"].cumsum()

    return vwap


def compute_returns(
    bars: pd.DataFrame,
    periods: List[int] = [5, 15, 30],
    price_col: str = "close",
) -> pd.DataFrame:
    """Compute returns over multiple time periods.

    Args:
        bars: DataFrame with price data
        periods: List of periods for return calculation (in bars)
        price_col: Column to use for price (default: "close")

    Returns:
        DataFrame with columns: ret_{period} for each period
    """
    if price_col not in bars.columns:
        raise ValueError(f"Price column '{price_col}' not found in DataFrame")

    result = pd.DataFrame(index=bars.index)

    for period in periods:
        result[f"ret_{period}"] = bars[price_col].pct_change(period)

    return result


def compute_log_returns(
    bars: pd.DataFrame,
    periods: List[int] = [5, 15, 30],
    price_col: str = "close",
) -> pd.DataFrame:
    """Compute log returns over multiple time periods.

    Log returns are additive over time: log(P_t/P_0) = sum(log(P_i/P_{i-1}))

    Args:
        bars: DataFrame with price data
        periods: List of periods for return calculation (in bars)
        price_col: Column to use for price (default: "close")

    Returns:
        DataFrame with columns: log_ret_{period} for each period
    """
    if price_col not in bars.columns:
        raise ValueError(f"Price column '{price_col}' not found in DataFrame")

    result = pd.DataFrame(index=bars.index)

    for period in periods:
        result[f"log_ret_{period}"] = np.log(bars[price_col] / bars[price_col].shift(period))

    return result


def compute_atr(
    bars: pd.DataFrame,
    period: int = 14,
) -> pd.Series:
    """Compute Average True Range (ATR) for volatility measurement.

    True Range = max(high - low, |high - prev_close|, |low - prev_close|)
    ATR = rolling mean of True Range

    Args:
        bars: DataFrame with columns: high, low, close
        period: Period for ATR calculation (default: 14)

    Returns:
        Series with ATR values, same index as input
    """
    required_cols = ["high", "low", "close"]
    for col in required_cols:
        if col not in bars.columns:
            raise ValueError(f"Missing required column: {col}")

    # Previous close
    prev_close = bars["close"].shift(1)

    # True Range components
    high_low = bars["high"] - bars["low"]
    high_prev_close = np.abs(bars["high"] - prev_close)
    low_prev_close = np.abs(bars["low"] - prev_close)

    # True Range = max of the three
    true_range = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)

    # ATR = rolling mean
    atr = true_range.rolling(window=period).mean()

    return atr


def compute_session_range(bars: pd.DataFrame) -> pd.DataFrame:
    """Compute session-based range features.

    Adds columns for:
    - session_high: Highest price in current session
    - session_low: Lowest price in current session
    - session_range: Difference between high and low
    - position_in_range: Current close relative to range (0-1)

    Args:
        bars: DataFrame with columns: high, low, close, ts (datetime)

    Returns:
        DataFrame with session range features added
    """
    required_cols = ["high", "low", "close"]
    for col in required_cols:
        if col not in bars.columns:
            raise ValueError(f"Missing required column: {col}")

    # Ensure ts is datetime
    if "ts" in bars.columns and not pd.api.types.is_datetime64_any_dtype(bars["ts"]):
        bars = bars.copy()
        bars["ts"] = pd.to_datetime(bars["ts"])

    result = bars.copy()

    if "ts" in result.columns:
        # Group by date to compute session stats
        result["date"] = result["ts"].dt.date

        # Session high and low (expanding max/min within session)
        result["session_high"] = result.groupby("date")["high"].transform(
            lambda x: x.expanding().max()
        )
        result["session_low"] = result.groupby("date")["low"].transform(
            lambda x: x.expanding().min()
        )
    else:
        # No timestamp, assume entire dataframe is one session
        result["session_high"] = result["high"].cummax()
        result["session_low"] = result["low"].cummin()

    # Session range
    result["session_range"] = result["session_high"] - result["session_low"]

    # Position in range (0 = at session low, 1 = at session high)
    result["position_in_range"] = (
        (result["close"] - result["session_low"]) / result["session_range"]
    ).fillna(0.5)

    return result


def compute_rsi(
    bars: pd.DataFrame,
    period: int = 14,
    price_col: str = "close",
) -> pd.Series:
    """Compute Relative Strength Index (RSI).

    RSI = 100 - (100 / (1 + RS))
    where RS = Average Gain / Average Loss

    Args:
        bars: DataFrame with price data
        period: Period for RSI calculation (default: 14)
        price_col: Column to use for price (default: "close")

    Returns:
        Series with RSI values (0-100), same index as input
    """
    if price_col not in bars.columns:
        raise ValueError(f"Price column '{price_col}' not found in DataFrame")

    # Price change
    delta = bars[price_col].diff()

    # Separate gains and losses
    gains = delta.where(delta > 0, 0)
    losses = -delta.where(delta < 0, 0)

    # Average gain and loss (using exponential moving average)
    avg_gains = gains.ewm(span=period, adjust=False).mean()
    avg_losses = losses.ewm(span=period, adjust=False).mean()

    # Relative strength
    rs = avg_gains / avg_losses

    # RSI
    rsi = 100 - (100 / (1 + rs))

    return rsi


def compute_bollinger_bands(
    bars: pd.DataFrame,
    period: int = 20,
    num_std: float = 2.0,
    price_col: str = "close",
) -> pd.DataFrame:
    """Compute Bollinger Bands.

    Args:
        bars: DataFrame with price data
        period: Period for moving average (default: 20)
        num_std: Number of standard deviations (default: 2.0)
        price_col: Column to use for price (default: "close")

    Returns:
        DataFrame with columns: bb_middle, bb_upper, bb_lower, bb_width
    """
    if price_col not in bars.columns:
        raise ValueError(f"Price column '{price_col}' not found in DataFrame")

    result = pd.DataFrame(index=bars.index)

    # Middle band = SMA
    result["bb_middle"] = bars[price_col].rolling(window=period).mean()

    # Standard deviation
    std = bars[price_col].rolling(window=period).std()

    # Upper and lower bands
    result["bb_upper"] = result["bb_middle"] + (std * num_std)
    result["bb_lower"] = result["bb_middle"] - (std * num_std)

    # Band width (volatility measure)
    result["bb_width"] = (result["bb_upper"] - result["bb_lower"]) / result["bb_middle"]

    # Position within bands
    result["bb_position"] = (
        (bars[price_col] - result["bb_lower"]) / (result["bb_upper"] - result["bb_lower"])
    ).fillna(0.5)

    return result


def compute_all_price_features(
    bars: pd.DataFrame,
    return_periods: List[int] = [5, 15, 30],
    atr_period: int = 14,
    rsi_period: int = 14,
    bb_period: int = 20,
) -> pd.DataFrame:
    """Compute all price-based features for a DataFrame of bars.

    Args:
        bars: DataFrame with OHLCV data
        return_periods: Periods for return calculations
        atr_period: Period for ATR
        rsi_period: Period for RSI
        bb_period: Period for Bollinger Bands

    Returns:
        DataFrame with all price features added as columns
    """
    result = bars.copy()

    # VWAP
    result["vwap"] = compute_vwap(result)

    # Returns
    returns_df = compute_returns(result, periods=return_periods)
    for col in returns_df.columns:
        result[col] = returns_df[col]

    # Log returns
    log_returns_df = compute_log_returns(result, periods=return_periods)
    for col in log_returns_df.columns:
        result[f"log_{col}"] = log_returns_df[col]

    # ATR
    result["atr"] = compute_atr(result, period=atr_period)

    # ATR relative to price (normalized volatility)
    result["atr_pct"] = result["atr"] / result["close"]

    # Session range
    session_df = compute_session_range(result)
    result["session_high"] = session_df["session_high"]
    result["session_low"] = session_df["session_low"]
    result["session_range"] = session_df["session_range"]
    result["position_in_range"] = session_df["position_in_range"]

    # RSI
    result["rsi"] = compute_rsi(result, period=rsi_period)

    # Bollinger Bands
    bb_df = compute_bollinger_bands(result, period=bb_period)
    result["bb_middle"] = bb_df["bb_middle"]
    result["bb_upper"] = bb_df["bb_upper"]
    result["bb_lower"] = bb_df["bb_lower"]
    result["bb_width"] = bb_df["bb_width"]
    result["bb_position"] = bb_df["bb_position"]

    return result
