"""Regime detection features for market state classification.

Streaming-friendly features designed for intraday regime detection using
1-minute OHLCV data with no forward-looking bias.
"""

from typing import Any

import numpy as np
import pandas as pd


def mod_normalized_volatility(
    df: pd.DataFrame, lookback_m: int = 30, min_periods: int = 5
) -> pd.Series:
    """Compute month-of-day normalized intraday volatility.

    Normalizes current intraday volatility by historical average for the same
    time of day across the dataset to remove seasonal patterns.

    Args:
        df: DataFrame with ts, symbol, high, low, close, sorted by [symbol, ts]
        lookback_m: Rolling window in minutes for volatility calculation
        min_periods: Minimum periods required for rolling calculation

    Returns:
        Series of MoD-normalized volatility values
    """
    if not all(col in df.columns for col in ["ts", "symbol", "high", "low", "close"]):
        raise ValueError(
            "DataFrame must contain 'ts', 'symbol', 'high', 'low', 'close' columns"
        )

    results = []

    for symbol, group in df.groupby("symbol"):
        group = group.copy().sort_values("ts")

        # Calculate intraday volatility (True Range normalized by close)
        high_low = group["high"] - group["low"]
        high_close = (group["high"] - group["close"].shift(1)).abs()
        low_close = (group["low"] - group["close"].shift(1)).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        volatility = true_range / group["close"]

        # Rolling volatility (uses only current and past bars)
        rolling_vol = volatility.rolling(lookback_m, min_periods=min_periods).mean()

        # Month-of-day (minute) identifier
        timestamps = pd.to_datetime(group["ts"], utc=True)
        time_of_day = timestamps.dt.hour * 60 + timestamps.dt.minute
        tod_series = pd.Series(time_of_day.values, index=group.index, dtype=int)

        # Running average volatility per minute-of-day using only prior observations
        tod_counts = tod_series.groupby(tod_series).cumcount()
        tod_cumsum = volatility.groupby(tod_series).cumsum() - volatility
        avg_vol_tod = tod_cumsum.divide(tod_counts.replace(0, np.nan))

        # Symbol-level expanding average as fallback (also past-only)
        symbol_counts = pd.Series(np.arange(len(group)), index=group.index, dtype=int)
        symbol_cumsum = volatility.cumsum() - volatility
        avg_vol_symbol = symbol_cumsum.divide(symbol_counts.replace(0, np.nan))

        # Combine averages, using forward fill to propagate last known values
        avg_vol_for_time = avg_vol_tod.fillna(avg_vol_symbol).ffill().replace(0, np.nan)

        mod_normalized = rolling_vol.divide(avg_vol_for_time)

        result = pd.Series(
            mod_normalized.values,
            index=group.index,
            name=f"f__regime__mod_vol_{lookback_m}",
        )
        results.append(result)

    return pd.concat(results).sort_index()


def variance_ratio(
    df: pd.DataFrame,
    short_window: int = 10,
    long_window: int = 60,
    min_periods: int = 3,
) -> pd.Series:
    """Compute variance ratio for trend detection.

    Ratio of short-term to long-term variance. Values > 1 indicate
    trending behavior, values < 1 indicate mean-reversion.

    Args:
        df: DataFrame with ts, symbol, close, sorted by [symbol, ts]
        short_window: Short-term window in minutes
        long_window: Long-term window in minutes
        min_periods: Minimum periods required for calculations

    Returns:
        Series of variance ratio values
    """
    if not all(col in df.columns for col in ["ts", "symbol", "close"]):
        raise ValueError("DataFrame must contain 'ts', 'symbol', 'close' columns")

    results = []

    for symbol, group in df.groupby("symbol"):
        group = group.copy().sort_values("ts")

        # Calculate returns
        returns = group["close"].pct_change()

        # Rolling variances
        short_var = returns.rolling(short_window, min_periods=min_periods).var()
        long_var = returns.rolling(long_window, min_periods=min_periods).var()

        # Variance ratio with safety checks
        variance_ratio = np.where(
            long_var > 0,
            short_var / long_var,
            1.0,  # Default to neutral when long_var is zero
        )

        # Clip extreme values for stability
        variance_ratio = np.clip(variance_ratio, 0.1, 10.0)

        result = pd.Series(
            variance_ratio,
            index=group.index,
            name=f"f__regime__var_ratio_{short_window}_{long_window}",
        )
        results.append(result)

    return pd.concat(results).sort_index()


def adx_proxy(
    df: pd.DataFrame, lookback_m: int = 14, min_periods: int = 3
) -> pd.Series:
    """Compute ADX proxy using price ranges for trend strength.

    ADX (Average Directional Index) measures trend strength without
    indicating direction. This proxy uses True Range and directional movement.

    Args:
        df: DataFrame with ts, symbol, high, low, close, sorted by [symbol, ts]
        lookback_m: Lookback window in minutes
        min_periods: Minimum periods for rolling calculations

    Returns:
        Series of ADX proxy values (0-100, higher = stronger trend)
    """
    if not all(col in df.columns for col in ["ts", "symbol", "high", "low", "close"]):
        raise ValueError(
            "DataFrame must contain 'ts', 'symbol', 'high', 'low', 'close' columns"
        )

    results = []

    for symbol, group in df.groupby("symbol"):
        group = group.copy().sort_values("ts")

        # Calculate True Range
        high_low = group["high"] - group["low"]
        high_close = (group["high"] - group["close"].shift(1)).abs()
        low_close = (group["low"] - group["close"].shift(1)).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

        # Calculate directional movements
        up_move = group["high"] - group["high"].shift(1)
        down_move = group["low"].shift(1) - group["low"]

        # Positive and negative directional movement
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

        # Convert to Series
        plus_dm = pd.Series(plus_dm, index=group.index)
        minus_dm = pd.Series(minus_dm, index=group.index)
        true_range = pd.Series(true_range, index=group.index)

        # Smoothed values
        tr_smooth = true_range.rolling(lookback_m, min_periods=min_periods).mean()
        plus_dm_smooth = plus_dm.rolling(lookback_m, min_periods=min_periods).mean()
        minus_dm_smooth = minus_dm.rolling(lookback_m, min_periods=min_periods).mean()

        # Directional indexes
        plus_di = 100 * (plus_dm_smooth / tr_smooth.replace(0, 1))
        minus_di = 100 * (minus_dm_smooth / tr_smooth.replace(0, 1))

        # ADX calculation
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, 1)
        adx = dx.rolling(lookback_m, min_periods=min_periods).mean()

        result = pd.Series(
            adx.values, index=group.index, name=f"f__regime__adx_proxy_{lookback_m}"
        )
        results.append(result)

    return pd.concat(results).sort_index()


def band_position(
    df: pd.DataFrame, window_m: int = 20, std_dev: float = 2.0, min_periods: int = 5
) -> pd.Series:
    """Compute price position relative to Bollinger Bands.

    Returns normalized position within bands: 0 = lower band, 1 = upper band.
    Values outside [0,1] indicate price outside bands.

    Args:
        df: DataFrame with ts, symbol, close, sorted by [symbol, ts]
        window_m: Window for moving average and standard deviation
        std_dev: Number of standard deviations for bands
        min_periods: Minimum periods for calculations

    Returns:
        Series of band position values
    """
    if not all(col in df.columns for col in ["ts", "symbol", "close"]):
        raise ValueError("DataFrame must contain 'ts', 'symbol', 'close' columns")

    results = []

    for symbol, group in df.groupby("symbol"):
        group = group.copy().sort_values("ts")

        # Calculate Bollinger Bands
        sma = group["close"].rolling(window_m, min_periods=min_periods).mean()
        std = group["close"].rolling(window_m, min_periods=min_periods).std()

        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)

        # Calculate position within bands
        band_width = upper_band - lower_band
        band_position = (group["close"] - lower_band) / band_width.replace(0, 1)

        # Clip to reasonable range for stability
        band_position = np.clip(band_position, -0.5, 1.5)

        result = pd.Series(
            band_position.values,
            index=group.index,
            name=f"f__regime__band_pos_{window_m}_{std_dev}",
        )
        results.append(result)

    return pd.concat(results).sort_index()


def stress_metrics(
    df: pd.DataFrame,
    volatility_window: int = 10,
    volume_window: int = 10,
    vol_threshold: float = 2.0,
    volume_threshold: float = 3.0,
    min_periods: int = 3,
) -> pd.Series:
    """Compute stress indicators based on volatility and volume spikes.

    Combines volatility spikes and volume surges to detect market stress.

    Args:
        df: DataFrame with ts, symbol, high, low, close, volume, sorted by [symbol, ts]
        volatility_window: Window for volatility calculation
        volume_window: Window for volume average
        vol_threshold: Volatility multiplier for stress detection
        volume_threshold: Volume multiplier for stress detection
        min_periods: Minimum periods for calculations

    Returns:
        Series of stress metric values (higher = more stress)
    """
    if not all(
        col in df.columns for col in ["ts", "symbol", "high", "low", "close", "volume"]
    ):
        raise ValueError(
            "DataFrame must contain 'ts', 'symbol', 'high', 'low', 'close', 'volume' columns"
        )

    results = []

    for symbol, group in df.groupby("symbol"):
        group = group.copy().sort_values("ts")

        # Calculate True Range volatility
        high_low = group["high"] - group["low"]
        high_close = (group["high"] - group["close"].shift(1)).abs()
        low_close = (group["low"] - group["close"].shift(1)).abs()
        true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        volatility = true_range / group["close"]

        # Rolling statistics
        recent_vol = volatility.rolling(
            volatility_window, min_periods=min_periods
        ).mean()
        avg_volume = (
            group["volume"].rolling(volume_window, min_periods=min_periods).mean()
        )

        # Long-term averages for normalization
        long_vol = volatility.rolling(
            max(volatility_window * 6, 30), min_periods=min_periods
        ).mean()
        long_avg_volume = (
            group["volume"]
            .rolling(max(volume_window * 6, 30), min_periods=min_periods)
            .mean()
        )

        # Normalized stress indicators
        vol_stress = recent_vol / long_vol.replace(0, 1)
        volume_stress = avg_volume / long_avg_volume.replace(0, 1)

        # Combined stress metric
        stress_score = np.maximum(
            (vol_stress - 1) * (vol_stress >= vol_threshold),
            (volume_stress - 1) * (volume_stress >= volume_threshold),
        )

        # Ensure non-negative with floor at 0
        stress_score = np.maximum(stress_score, 0)

        # Clip extreme values
        stress_score = np.clip(stress_score, 0, 10)

        result = pd.Series(
            stress_score,
            index=group.index,
            name=f"f__regime__stress_{volatility_window}_{volume_window}",
        )
        results.append(result)

    return pd.concat(results).sort_index()


def compute_all_regime_features(
    df: pd.DataFrame,
    volatility_window: int = 30,
    variance_short: int = 10,
    variance_long: int = 60,
    adx_window: int = 14,
    band_window: int = 20,
    band_std: float = 2.0,
    stress_vol_window: int = 10,
    stress_vol_threshold: float = 2.0,
    stress_volume_threshold: float = 3.0,
) -> pd.DataFrame:
    """Compute all regime features efficiently.

    Args:
        df: Input DataFrame with required OHLCV columns
        volatility_window: Window for MoD-normalized volatility
        variance_short: Short window for variance ratio
        variance_long: Long window for variance ratio
        adx_window: Window for ADX proxy
        band_window: Window for Bollinger Bands
        band_std: Standard deviations for bands
        stress_vol_window: Window for stress volatility calculation
        stress_vol_threshold: Volatility threshold for stress detection
        stress_volume_threshold: Volume threshold for stress detection

    Returns:
        DataFrame with all regime features added
    """
    import time

    # Validate inputs
    required_cols = ["ts", "symbol", "high", "low", "close", "volume"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    # Check sorting
    if (
        not df.groupby("symbol", group_keys=False)
        .apply(lambda g: g["ts"].is_monotonic_increasing, include_groups=False)
        .all()
    ):
        raise ValueError("DataFrame must be sorted by [symbol, ts]")

    result = df.copy()
    total_symbols = df["symbol"].nunique()
    total_bars = len(df)

    print(
        f"Computing regime features for {total_symbols:,} symbols ({total_bars:,} bars)..."
    )
    start_time = time.time()

    # Compute features
    print("  Computing MoD-normalized volatility...")
    result[mod_normalized_volatility(df, volatility_window).name] = (
        mod_normalized_volatility(df, volatility_window)
    )

    print("  Computing variance ratio...")
    result[variance_ratio(df, variance_short, variance_long).name] = variance_ratio(
        df, variance_short, variance_long
    )

    print("  Computing ADX proxy...")
    result[adx_proxy(df, adx_window).name] = adx_proxy(df, adx_window)

    print("  Computing band position...")
    result[band_position(df, band_window, band_std).name] = band_position(
        df, band_window, band_std
    )

    print("  Computing stress metrics...")
    result[
        stress_metrics(
            df,
            stress_vol_window,
            stress_vol_window,
            stress_vol_threshold,
            stress_volume_threshold,
        ).name
    ] = stress_metrics(
        df,
        stress_vol_window,
        stress_vol_window,
        stress_vol_threshold,
        stress_volume_threshold,
    )

    # Add warmup mask based on maximum window
    max_window = max(volatility_window, variance_long, adx_window, band_window)
    result["f__regime__warmup_ok"] = (
        result.groupby("symbol", group_keys=False).cumcount() >= max_window
    )

    total_time = time.time() - start_time
    bars_per_second = total_bars / total_time if total_time > 0 else 0

    print(
        f"  ✓ Regime features computed in {total_time:.1f}s ({bars_per_second:.0f} bars/sec)"
    )
    print(f"  ✓ Processed {total_symbols:,} symbols and {total_bars:,} bars")

    return result


# Feature registry utilities
def get_regime_feature_config() -> dict[str, dict[str, Any]]:
    """Get default configuration for regime features.

    Returns:
        Dictionary mapping feature names to their default parameters
    """
    return {
        "mod_normalized_volatility": {"lookback_m": 30, "min_periods": 5},
        "variance_ratio": {"short_window": 10, "long_window": 60, "min_periods": 3},
        "adx_proxy": {"lookback_m": 14, "min_periods": 3},
        "band_position": {"window_m": 20, "std_dev": 2.0, "min_periods": 5},
        "stress_metrics": {
            "volatility_window": 10,
            "volume_window": 10,
            "vol_threshold": 2.0,
            "volume_threshold": 3.0,
            "min_periods": 3,
        },
    }


def validate_regime_inputs(df: pd.DataFrame) -> None:
    """Validate DataFrame inputs for regime feature computation.

    Args:
        df: DataFrame to validate

    Raises:
        ValueError: If validation fails
    """
    required_columns = ["ts", "symbol", "high", "low", "close", "volume"]
    missing_cols = [col for col in required_columns if col not in df.columns]
    if missing_cols:
        raise ValueError(f"Missing required columns: {missing_cols}")

    # Check for valid OHLC relationships
    invalid_ohlc = (
        (df["high"] < df["low"])
        | (df["high"] < df["open"])
        | (df["high"] < df["close"])
        | (df["low"] > df["open"])
        | (df["low"] > df["close"])
    ).sum()

    if invalid_ohlc > 0:
        raise ValueError(f"Found {invalid_ohlc} rows with invalid OHLC relationships")

    # Check for positive prices and volume
    if (df[["high", "low", "close", "volume"]] <= 0).any().any():
        raise ValueError("Price and volume columns must contain positive values")

    # Check timestamp validity
    if (df["ts"] <= 0).any():
        raise ValueError("Timestamps must be positive")

    # Check sorting
    if (
        not df.groupby("symbol", group_keys=False)
        .apply(lambda g: g["ts"].is_monotonic_increasing, include_groups=False)
        .all()
    ):
        raise ValueError("DataFrame must be sorted by [symbol, ts]")
