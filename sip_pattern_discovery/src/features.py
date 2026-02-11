"""Compute features for pattern discovery using qx-features."""

from functools import partial
from multiprocessing import Pool

import pandas as pd

# Silence FutureWarning about downcasting
pd.set_option("future.no_silent_downcasting", True)


def _ensure_datetime64_ns(series: pd.Series) -> pd.Series:
    """Normalize timestamps to naive datetime64[ns] for merge_asof compatibility."""
    if pd.api.types.is_datetime64_ns_dtype(series):
        return series
    if pd.api.types.is_datetime64tz_dtype(series):
        return series.dt.tz_convert("UTC").dt.tz_localize(None)
    if pd.api.types.is_datetime64_any_dtype(series):
        return series.astype("datetime64[ns]")
    return pd.to_datetime(series, utc=True, errors="coerce").dt.tz_localize(None)


def compute_momentum_features_for_symbol(symbol_group: tuple) -> pd.DataFrame:
    """Compute momentum features for a single symbol."""
    symbol, group = symbol_group
    group = group.sort_values("ts").copy()

    for window in [5, 15, 30, 60]:
        ret = group["close"].pct_change(window)
        group[f"ret_{window}m"] = ret

        # EVENT features: Momentum sign changes
        positive = ret > 0
        group[f"ret_{window}m_turned_positive"] = positive & ~positive.shift(1).fillna(
            True
        )
        group[f"ret_{window}m_turned_negative"] = ~positive & positive.shift(1).fillna(
            False
        )

    return group


def compute_relative_strength_features(
    df: pd.DataFrame, spy_df: pd.DataFrame
) -> pd.DataFrame:
    """Compute cross-ticker relative strength vs SPY.

    This is a HIGH ALPHA feature - stocks that underperform SPY tend to catch up.
    """
    result = df.copy()

    if spy_df.empty:
        result["rel_strength_60m"] = 0.0
        result["rel_strength_extreme"] = False
        return result

    # Compute SPY returns
    spy = spy_df.sort_values("ts").copy()
    spy["spy_ret_60m_pct"] = spy["close"].pct_change(60) * 100

    # Merge SPY returns to main df
    spy_rets = spy[["ts", "spy_ret_60m_pct"]].rename(columns={"ts": "spy_ts"})
    result["ts"] = _ensure_datetime64_ns(result["ts"])
    spy_rets["spy_ts"] = _ensure_datetime64_ns(spy_rets["spy_ts"])
    result = result.sort_values("ts")
    spy_rets = spy_rets.sort_values("spy_ts")

    result = pd.merge_asof(
        result,
        spy_rets,
        left_on="ts",
        right_on="spy_ts",
        direction="backward",
    )

    # Relative strength = stock return - SPY return
    # Positive = outperforming, Negative = underperforming
    result["rel_strength_60m"] = result["ret_60m"] * 100 - result[
        "spy_ret_60m_pct"
    ].fillna(0)

    # EVENT: Extreme underperformance (>1% below SPY) = mean reversion opportunity
    result["rel_underperform_extreme"] = result["rel_strength_60m"] < -1.0
    result["rel_outperform_extreme"] = result["rel_strength_60m"] > 1.0

    # Clean up
    if "spy_ts" in result.columns:
        result = result.drop(columns=["spy_ts", "spy_ret_60m_pct"])

    return result


def compute_volume_price_features_for_symbol(symbol_group: tuple) -> pd.DataFrame:
    """Compute volume-price divergence features.

    HIGH ALPHA: Price moves on low volume are weak, high volume are strong.
    """
    symbol, group = symbol_group
    group = group.sort_values("ts").copy()

    # Need rvol and ret_60m computed first
    if "rvol" not in group.columns or "ret_60m" not in group.columns:
        return group

    # Volume-price divergence signals
    # Price up but volume weak = bearish divergence
    group["price_up_vol_weak"] = (group["ret_60m"] > 0.001) & (group["rvol"] < 0.7)
    # Price down but volume weak = bullish divergence
    group["price_down_vol_weak"] = (group["ret_60m"] < -0.001) & (group["rvol"] < 0.7)
    # Price up on strong volume = bullish confirmation
    group["price_up_vol_strong"] = (group["ret_60m"] > 0.001) & (group["rvol"] > 1.5)
    # Price down on strong volume = bearish confirmation
    group["price_down_vol_strong"] = (group["ret_60m"] < -0.001) & (group["rvol"] > 1.5)

    return group


def compute_session_range_features_for_symbol(symbol_group: tuple) -> pd.DataFrame:
    """Compute intraday range position features.

    MEDIUM ALPHA: Price at session extremes tends to mean-revert.
    """
    symbol, group = symbol_group
    group = group.sort_values("ts").copy()

    if "dt_et" not in group.columns:
        group["dt"] = pd.to_datetime(group["ts"], unit="ns", utc=True)
        group["dt_et"] = group["dt"].dt.tz_convert("America/New_York")

    group["session_date"] = group["dt_et"].dt.date

    for session_date, session_group in group.groupby("session_date"):
        # Running session high/low
        session_high = session_group["high"].expanding().max()
        session_low = session_group["low"].expanding().min()
        session_range = session_high - session_low

        # Position in range (0 = at low, 1 = at high)
        range_pct = (session_group["close"] - session_low) / session_range.replace(0, 1)

        group.loc[session_group.index, "session_range_pct"] = range_pct

        # EVENT: At session extremes
        group.loc[session_group.index, "at_session_high"] = range_pct > 0.95
        group.loc[session_group.index, "at_session_low"] = range_pct < 0.05

        # EVENT: New session high/low
        prev_high = session_high.shift(1)
        prev_low = session_low.shift(1)
        group.loc[session_group.index, "new_session_high"] = (
            session_group["high"] > prev_high
        )
        group.loc[session_group.index, "new_session_low"] = (
            session_group["low"] < prev_low
        )

    # Drop heavy datetime columns to reduce memory footprint.
    group = group.drop(columns=["dt", "dt_et", "session_date"], errors="ignore")

    return group


def compute_momentum_features(df: pd.DataFrame, n_workers: int = 6) -> pd.DataFrame:
    """Compute momentum features (returns over various windows) in parallel."""
    symbols = df["symbol"].unique()
    print(f"  Computing for {len(symbols)} symbols using {n_workers} workers...")

    symbol_groups = [(symbol, group) for symbol, group in df.groupby("symbol")]

    if n_workers <= 1:
        results = [
            compute_momentum_features_for_symbol(group) for group in symbol_groups
        ]
    else:
        with Pool(n_workers) as pool:
            results = pool.map(compute_momentum_features_for_symbol, symbol_groups)

    return pd.concat(results, ignore_index=True)


def compute_vwap_features_for_symbol(
    symbol_group: tuple, window: int = 30
) -> pd.DataFrame:
    """Compute VWAP features for a single symbol."""
    symbol, group = symbol_group
    group = group.sort_values("ts").copy()

    # Rolling VWAP
    pv = (group["close"] * group["volume"]).rolling(window, min_periods=1).sum()
    vol_sum = group["volume"].rolling(window, min_periods=1).sum()
    vwap = pv / vol_sum.replace(0, 1)

    # Price vs VWAP (state feature)
    price_vs_vwap = (group["close"] - vwap) / vwap * 100

    group[f"vwap_{window}"] = vwap
    group["price_vs_vwap_pct"] = price_vs_vwap

    # EVENT features: VWAP crosses
    above_vwap = group["close"] > vwap
    group["vwap_cross_up"] = above_vwap & ~above_vwap.shift(1).fillna(False)
    group["vwap_cross_down"] = ~above_vwap & above_vwap.shift(1).fillna(True)

    return group


def compute_vwap_features(
    df: pd.DataFrame, window: int = 30, n_workers: int = 6
) -> pd.DataFrame:
    """Compute VWAP and price deviation in parallel."""
    symbols = df["symbol"].unique()
    print(f"  Computing VWAP for {len(symbols)} symbols using {n_workers} workers...")

    symbol_groups = [(symbol, group) for symbol, group in df.groupby("symbol")]
    compute_func = partial(compute_vwap_features_for_symbol, window=window)

    if n_workers <= 1:
        results = [compute_func(group) for group in symbol_groups]
    else:
        with Pool(n_workers) as pool:
            results = pool.map(compute_func, symbol_groups)

    return pd.concat(results, ignore_index=True)


def compute_volume_features_for_symbol(
    symbol_group: tuple, volume_baseline: dict[str, pd.Series] | None = None
) -> pd.DataFrame:
    """Compute volume features for a single symbol."""
    symbol, group = symbol_group
    group = group.copy()

    # Convert ts to datetime
    group["dt"] = pd.to_datetime(group["ts"], unit="ns", utc=True)
    group["dt_et"] = group["dt"].dt.tz_convert("America/New_York")
    group["minute_of_day"] = group["dt_et"].dt.hour * 60 + group["dt_et"].dt.minute

    if volume_baseline and symbol in volume_baseline:
        baseline = volume_baseline[symbol]
        tod_avg = group["minute_of_day"].map(baseline).astype("float64")
    else:
        tod_avg = group.groupby("minute_of_day")["volume"].transform("mean")

    rvol = group["volume"] / tod_avg.replace(0, 1)
    group["rvol"] = rvol

    # Drop heavy datetime columns to reduce memory footprint.
    group = group.drop(columns=["dt", "dt_et", "minute_of_day"], errors="ignore")

    return group


def compute_volume_features(
    df: pd.DataFrame,
    n_workers: int = 6,
    volume_baseline: dict[str, pd.Series] | None = None,
) -> pd.DataFrame:
    """Compute relative volume (time-of-day normalized) in parallel."""
    symbols = df["symbol"].unique()
    print(f"  Computing volume for {len(symbols)} symbols using {n_workers} workers...")

    symbol_groups = [(symbol, group) for symbol, group in df.groupby("symbol")]

    if n_workers <= 1:
        results = [
            compute_volume_features_for_symbol(group, volume_baseline=volume_baseline)
            for group in symbol_groups
        ]
    else:
        with Pool(n_workers) as pool:
            results = pool.map(compute_volume_features_for_symbol, symbol_groups)

    return pd.concat(results, ignore_index=True)


def compute_atr_features_for_symbol(
    symbol_group: tuple, window: int = 14
) -> pd.DataFrame:
    """Compute ATR for a single symbol."""
    symbol, group = symbol_group
    group = group.sort_values("ts").copy()

    # True range
    high_low = group["high"] - group["low"]
    high_close = abs(group["high"] - group["close"].shift(1))
    low_close = abs(group["low"] - group["close"].shift(1))

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(window, min_periods=1).mean()
    group[f"atr_{window}"] = atr

    return group


def compute_atr_features(
    df: pd.DataFrame, window: int = 14, n_workers: int = 6
) -> pd.DataFrame:
    """Compute ATR (Average True Range) in parallel."""
    symbols = df["symbol"].unique()
    print(f"  Computing ATR for {len(symbols)} symbols using {n_workers} workers...")

    symbol_groups = [(symbol, group) for symbol, group in df.groupby("symbol")]
    compute_func = partial(compute_atr_features_for_symbol, window=window)

    if n_workers <= 1:
        results = [compute_func(group) for group in symbol_groups]
    else:
        with Pool(n_workers) as pool:
            results = pool.map(compute_func, symbol_groups)

    return pd.concat(results, ignore_index=True)


def compute_session_features_for_symbol(symbol_group: tuple) -> pd.DataFrame:
    """Compute session features for a single symbol."""
    symbol, group = symbol_group
    group = group.sort_values("ts").copy()

    # Ensure datetime columns exist
    if "dt_et" not in group.columns:
        group["dt"] = pd.to_datetime(group["ts"], unit="ns", utc=True)
        group["dt_et"] = group["dt"].dt.tz_convert("America/New_York")

    group["session_date"] = group["dt_et"].dt.date

    # Session AVWAP (cumulative from 9:30)
    for session_date, session_group in group.groupby("session_date"):
        pv_cumsum = (session_group["close"] * session_group["volume"]).cumsum()
        vol_cumsum = session_group["volume"].cumsum()
        session_avwap = pv_cumsum / vol_cumsum.replace(0, 1)

        price_vs_avwap = (session_group["close"] - session_avwap) / session_avwap * 100

        group.loc[session_group.index, "session_avwap"] = session_avwap
        group.loc[session_group.index, "price_vs_session_avwap_pct"] = price_vs_avwap

        # EVENT: Session AVWAP crosses
        above_avwap = session_group["close"] > session_avwap
        group.loc[session_group.index, "avwap_cross_up"] = (
            above_avwap & ~above_avwap.shift(1).fillna(False)
        )
        group.loc[session_group.index, "avwap_cross_down"] = (
            ~above_avwap & above_avwap.shift(1).fillna(True)
        )

    # Drop heavy datetime columns to reduce memory footprint.
    group = group.drop(columns=["dt", "dt_et", "session_date"], errors="ignore")

    return group


def compute_session_features(df: pd.DataFrame, n_workers: int = 6) -> pd.DataFrame:
    """Compute session-anchored features in parallel."""
    symbols = df["symbol"].unique()
    print(
        f"  Computing session features for {len(symbols)} symbols using {n_workers} workers..."
    )

    symbol_groups = [(symbol, group) for symbol, group in df.groupby("symbol")]

    if n_workers <= 1:
        results = [
            compute_session_features_for_symbol(group) for group in symbol_groups
        ]
    else:
        with Pool(n_workers) as pool:
            results = pool.map(compute_session_features_for_symbol, symbol_groups)

    return pd.concat(results, ignore_index=True)


def compute_time_features(df: pd.DataFrame, inplace: bool = False) -> pd.DataFrame:
    """Compute time-of-day features including events."""
    result = df if inplace else df.copy()

    if "dt_et" not in result.columns:
        result["dt"] = pd.to_datetime(result["ts"], unit="ns", utc=True)
        result["dt_et"] = result["dt"].dt.tz_convert("America/New_York")

    result["hour_et"] = result["dt_et"].dt.hour
    result["minute_et"] = result["dt_et"].dt.minute

    # State features (for regime filtering)
    result["is_first_hour"] = (
        (result["hour_et"] == 9) & (result["minute_et"] >= 30)
    ) | (result["hour_et"] == 10)
    result["is_power_hour"] = result["hour_et"] == 15

    # EVENT features (actual entry signals)
    # Power hour start: True only at 15:00
    result["power_hour_start"] = (result["hour_et"] == 15) & (result["minute_et"] == 0)
    # First hour start: True only at 9:30
    result["first_hour_start"] = (result["hour_et"] == 9) & (result["minute_et"] == 30)
    # Last 30 min start: True only at 15:30
    result["last_30min_start"] = (result["hour_et"] == 15) & (result["minute_et"] == 30)

    # Drop heavy datetime columns to reduce memory footprint.
    result = result.drop(
        columns=["dt", "dt_et", "hour_et", "minute_et"], errors="ignore"
    )

    return result


def compute_spy_regime_features(df: pd.DataFrame, spy_df: pd.DataFrame) -> pd.DataFrame:
    """Add SPY regime features to dataframe."""
    result = df.copy()

    if spy_df.empty:
        # No SPY data - add neutral defaults
        result["spy_above_sma20"] = True
        result["spy_ret_60m"] = 0.0
        result["spy_high_vol"] = False
        return result

    # Compute SPY features
    spy = spy_df.sort_values("ts").copy()
    spy["sma20"] = spy["close"].rolling(20, min_periods=1).mean()
    spy["spy_above_sma20"] = spy["close"] > spy["sma20"]
    spy["spy_ret_60m"] = spy["close"].pct_change(60)

    # Volatility regime (ATR percentile)
    high_low = spy["high"] - spy["low"]
    high_close = abs(spy["high"] - spy["close"].shift(1))
    low_close = abs(spy["low"] - spy["close"].shift(1))
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    spy["atr_20"] = tr.rolling(20, min_periods=1).mean()
    spy["atr_percentile"] = (
        spy["atr_20"].rolling(252 * 60, min_periods=100).rank(pct=True)
    )
    spy["spy_high_vol"] = spy["atr_percentile"] > 0.7

    # Merge on ts (nearest match)
    spy_features = spy[["ts", "spy_above_sma20", "spy_ret_60m", "spy_high_vol"]].copy()
    spy_features = spy_features.rename(columns={"ts": "spy_ts"})

    # Use merge_asof for time-based join
    result["ts"] = _ensure_datetime64_ns(result["ts"])
    spy_features["spy_ts"] = _ensure_datetime64_ns(spy_features["spy_ts"])
    result = result.sort_values("ts")
    spy_features = spy_features.sort_values("spy_ts")

    result = pd.merge_asof(
        result,
        spy_features,
        left_on="ts",
        right_on="spy_ts",
        direction="backward",
    )

    # Fill any missing values with proper dtype handling
    result["spy_above_sma20"] = result["spy_above_sma20"].fillna(True).astype(bool)
    result["spy_ret_60m"] = result["spy_ret_60m"].fillna(0.0).astype(float)
    result["spy_high_vol"] = result["spy_high_vol"].fillna(False).astype(bool)

    # Drop merge column
    if "spy_ts" in result.columns:
        result = result.drop(columns=["spy_ts"])

    return result


def compute_volume_price_features(df: pd.DataFrame, n_workers: int = 6) -> pd.DataFrame:
    """Compute volume-price divergence features in parallel."""
    symbols = df["symbol"].unique()
    print(f"  Computing volume-price for {len(symbols)} symbols...")

    symbol_groups = [(symbol, group) for symbol, group in df.groupby("symbol")]

    if n_workers <= 1:
        results = [
            compute_volume_price_features_for_symbol(group) for group in symbol_groups
        ]
    else:
        with Pool(n_workers) as pool:
            results = pool.map(compute_volume_price_features_for_symbol, symbol_groups)

    return pd.concat(results, ignore_index=True)


def compute_session_range_features(
    df: pd.DataFrame, n_workers: int = 6
) -> pd.DataFrame:
    """Compute session range features in parallel."""
    symbols = df["symbol"].unique()
    print(f"  Computing session range for {len(symbols)} symbols...")

    symbol_groups = [(symbol, group) for symbol, group in df.groupby("symbol")]

    if n_workers <= 1:
        results = [
            compute_session_range_features_for_symbol(group) for group in symbol_groups
        ]
    else:
        with Pool(n_workers) as pool:
            results = pool.map(compute_session_range_features_for_symbol, symbol_groups)

    return pd.concat(results, ignore_index=True)


def compute_all_features(
    df: pd.DataFrame,
    spy_df: pd.DataFrame | None = None,
    n_workers: int = 1,
    volume_baseline: dict[str, pd.Series] | None = None,
) -> pd.DataFrame:
    """Compute all features for pattern discovery in parallel.

    Args:
        df: DataFrame with ts, symbol, OHLCV
        spy_df: Optional SPY 1m bars for regime features
        n_workers: Number of parallel workers (default 1 for memory safety, max 6).
                   WARNING: n_workers > 1 will duplicate memory across processes!
                   Use n_workers=1 for large datasets (>20M bars) to avoid OOM.

    Returns:
        DataFrame with all features added
    """
    n_workers = min(n_workers, 6)  # Cap at 6 workers
    result = df.copy()

    print("Computing momentum features...")
    result = compute_momentum_features(result, n_workers)

    print("Computing VWAP features...")
    result = compute_vwap_features(result, n_workers=n_workers)

    print("Computing volume features...")
    result = compute_volume_features(
        result, n_workers=n_workers, volume_baseline=volume_baseline
    )

    print("Computing ATR features...")
    result = compute_atr_features(result, n_workers=n_workers)

    print("Computing session features...")
    result = compute_session_features(result, n_workers)

    print("Computing time features...")
    result = compute_time_features(result)

    print("Computing session range features...")
    result = compute_session_range_features(result, n_workers)

    print("Computing volume-price divergence features...")
    result = compute_volume_price_features(result, n_workers)

    if spy_df is not None and not spy_df.empty:
        print("Computing SPY regime features...")
        result = compute_spy_regime_features(result, spy_df)

        print("Computing relative strength vs SPY...")
        result = compute_relative_strength_features(result, spy_df)

    return result


def compute_all_features_chunked(
    df: pd.DataFrame,
    spy_df: pd.DataFrame | None = None,
    chunk_size: int = 10,
) -> pd.DataFrame:
    """Memory-efficient feature computation for very large datasets.

    Processes symbols in chunks to avoid loading entire dataset into memory.
    This is useful for datasets >30M bars on memory-constrained systems.

    Args:
        df: DataFrame with ts, symbol, OHLCV
        spy_df: Optional SPY 1m bars for regime features
        chunk_size: Number of symbols to process per chunk (default 10)

    Returns:
        DataFrame with all features added

    Note:
        This function processes symbols sequentially (no parallel workers)
        to minimize memory footprint. Use compute_all_features() with
        n_workers=1 for smaller datasets that fit in memory.
    """
    symbols = df["symbol"].unique()
    print(f"Computing features for {len(symbols)} symbols in chunks of {chunk_size}...")

    results = []

    for i in range(0, len(symbols), chunk_size):
        chunk_symbols = symbols[i : i + chunk_size]

        # Filter to current chunk
        chunk = df[df["symbol"].isin(chunk_symbols)].copy()

        # Compute features (sequential, no parallel workers for memory safety)
        chunk = compute_all_features(chunk, spy_df, n_workers=1)

        results.append(chunk)

        processed = min(i + chunk_size, len(symbols))
        pct = processed / len(symbols) * 100
        print(f"  Processed {processed}/{len(symbols)} symbols ({pct:.1f}%)")

    # Concatenate all chunks
    print("Concatenating all chunks...")
    return pd.concat(results, ignore_index=True)


# =============================================================================
# Monthly Feature Cache - Memory-efficient per-month feature computation
# =============================================================================

import gc
from pathlib import Path


def _trim_feature_columns(result: pd.DataFrame, base_columns: set[str]) -> pd.DataFrame:
    """Keep only join keys and newly-created feature columns."""
    keep_cols: list[str] = []
    for key in ["ts", "symbol"]:
        if key in result.columns:
            keep_cols.append(key)
    for col in result.columns:
        if col not in base_columns and col not in keep_cols:
            keep_cols.append(col)
    return result[keep_cols]


class MonthlyFeatureCache:
    """Manage per-month feature computation and storage.

    This class enables memory-efficient feature computation by:
    1. Computing features on a per-month basis
    2. Saving each month to disk immediately
    3. Freeing memory between monthly chunks
    4. Enabling parallel processing of independent months

    Memory: ~2-3GB peak per month (vs 60GB for full dataset)
    Files: 12 months × 11 features = 132 files for 1-year run
    """

    def __init__(self, cache_dir: Path, n_workers: int = 1):
        """Initialize the monthly feature cache.

        Args:
            cache_dir: Directory for feature cache files
            n_workers: Number of parallel workers (1-12)
        """
        self.cache_dir = Path(cache_dir) / ".feature_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.n_workers = min(n_workers, 12)

    def compute_feature_monthly(
        self,
        df: pd.DataFrame,
        feature_func,
        feature_name: str,
        load_cached: bool = True,
        **kwargs,
    ) -> pd.DataFrame:
        """Compute a single feature, saving monthly chunks to disk.

        Args:
            df: Full dataset with all months
            feature_func: Function to compute the feature
            feature_name: Name of the feature (for folder naming)
            **kwargs: Passed to feature_func

        Returns:
            Concatenated result (or None if all cached)
        """
        feature_dir = self.cache_dir / feature_name
        feature_dir.mkdir(exist_ok=True)

        # MEMORY FIX: Don't copy df! Track if we add date column
        has_date_col = "date" in df.columns
        if not has_date_col:
            df["date"] = pd.to_datetime(df["ts"], unit="ns", utc=True).dt.date

        months = sorted(df["date"].unique())
        base_columns = set(df.columns)

        results = []
        months_to_process = []

        if load_cached:
            # Check which months are already cached
            for month in months:
                month_str = month.strftime("%Y_%m")
                month_file = feature_dir / f"month_{month_str}.parquet"

                if month_file.exists():
                    print(f"  Loading cached {feature_name} for {month_str}...")
                    cached = pd.read_parquet(month_file)
                    results.append(_trim_feature_columns(cached, base_columns))
                else:
                    months_to_process.append(month)
        else:
            months_to_process = list(months)

        feature_kwargs = dict(kwargs)
        if "n_workers" in feature_kwargs and feature_kwargs["n_workers"] != 1:
            print(
                "  Forcing feature n_workers=1 inside monthly cache to avoid nested pools."
            )
            feature_kwargs["n_workers"] = 1

        # Process uncached months (can parallelize)
        if months_to_process and self.n_workers > 1:
            from functools import partial

            def _month_items():
                for month in months_to_process:
                    month_mask = df["date"] == month
                    month_df = df[month_mask].copy()
                    yield month, month_df

            # Process in parallel
            with Pool(self.n_workers) as pool:
                compute_func = partial(
                    _compute_feature_for_month,
                    feature_func=feature_func,
                    feature_dir=feature_dir,
                    feature_kwargs=feature_kwargs,
                )
                for pool_result in pool.imap_unordered(compute_func, _month_items()):
                    if pool_result is not None:
                        results.append(pool_result)

        elif months_to_process:
            # Sequential processing
            for month in months_to_process:
                month_str = month.strftime("%Y_%m")
                n_bars = (df["date"] == month).sum()
                print(
                    f"  Computing {feature_name} for {month_str} ({n_bars:,} bars)..."
                )

                # MEMORY FIX: Filter and copy ONLY this month (1-2GB, not 50GB)
                month_df = df[df["date"] == month].copy()
                base_columns = set(month_df.columns)

                # Compute feature
                if "date" in month_df.columns:
                    del month_df["date"]
                result = feature_func(month_df, **feature_kwargs)
                result = _trim_feature_columns(result, base_columns)

                # Save this month
                month_file = feature_dir / f"month_{month_str}.parquet"
                result.to_parquet(month_file, index=False)

                size_mb = month_file.stat().st_size / 1024 / 1024
                print(f"    Saved: {month_file.name} ({size_mb:.0f}MB)")

                results.append(result)

                # Explicit cleanup
                del month_df, result
                gc.collect()

        # Concatenate all months
        if results:
            final = pd.concat(results, ignore_index=True)
            if "date" in final.columns:
                final = final.drop(columns=["date"])

            # CLEANUP: Restore original df state if we added date column
            # This prevents memory accumulation from repeated date column additions
            if not has_date_col and "date" in df.columns:
                del df["date"]

            return final
        else:
            # CLEANUP: Even if no results, restore df state
            if not has_date_col and "date" in df.columns:
                del df["date"]
            return None


def _compute_feature_for_month(args, feature_func, feature_dir, feature_kwargs):
    """Worker function for parallel monthly computation.

    This function is called by multiprocessing.Pool to compute features
    for a single month in parallel.

    MEMORY-OPTIMIZED: Receives a pre-filtered month frame to avoid
    pickling the full dataset for each worker.

    Args:
        args: Tuple of (month, month_df)
        feature_func: Function to compute the feature
        feature_dir: Directory to save the monthly file
        feature_kwargs: Passed to feature_func

    Returns:
        Computed feature dataframe
    """
    month, month_df = args
    month_str = month.strftime("%Y_%m")

    base_columns = set(month_df.columns)

    # Remove date column before computing feature
    if "date" in month_df.columns:
        del month_df["date"]

    result = feature_func(month_df, **feature_kwargs)
    result = _trim_feature_columns(result, base_columns)

    # Save monthly file
    month_file = feature_dir / f"month_{month_str}.parquet"
    result.to_parquet(month_file, index=False)

    return result


def compute_all_features_monthly_cached(
    df: pd.DataFrame,
    spy_df: pd.DataFrame | None = None,
    cache_dir: Path = None,
    n_workers: int = 1,
    load_cached: bool = True,
) -> pd.DataFrame:
    """Compute all features with per-month caching for memory efficiency.

    This is the main entry point for the monthly caching approach.
    It computes each feature on a per-month basis, saving intermediate
    results to disk and freeing memory between monthly chunks.

    Memory: ~2-3GB peak per month
    Files: 132 total (11 features × 12 months) for 1-year run
    Parallel: n_workers can be 6-12 for 36GB systems

    Args:
        df: Raw data with ts, symbol, OHLCV
        spy_df: Optional SPY 1m bars for regime features
        cache_dir: Directory for cache files (default: .feature_cache)
        n_workers: Number of parallel workers (default 1)

    Returns:
        DataFrame with all features added
    """
    if cache_dir is None:
        cache_dir = Path(".feature_cache")

    if len(df) > 20_000_000 and n_workers > 2:
        print(
            "Large dataset detected; capping monthly workers to 2 to reduce "
            "memory pressure."
        )
        n_workers = 2

    cache = MonthlyFeatureCache(cache_dir, n_workers)

    # MEMORY FIX: Add date column in-place, don't copy entire df!
    # Track whether we need to clean it up at the end
    had_date_col = "date" in df.columns
    if not had_date_col:
        df["date"] = pd.to_datetime(df["ts"], unit="ns", utc=True).dt.date

    # Start with base columns (will add features incrementally)
    base_cols = ["ts", "symbol", "date"]
    if "close" in df.columns:
        base_cols.append("close")
    result = df[base_cols].copy()

    # Feature 1: Momentum
    print("\n[1/11] Computing momentum features (monthly)...")
    momentum = cache.compute_feature_monthly(
        df,
        compute_momentum_features,
        "momentum",
        load_cached=load_cached,
        n_workers=n_workers,
    )
    if momentum is not None:
        result = result.merge(momentum, on=["ts", "symbol"], how="left")
        del momentum
        gc.collect()

    # Feature 2: VWAP
    print("\n[2/11] Computing VWAP features (monthly)...")
    vwap = cache.compute_feature_monthly(
        df,
        compute_vwap_features,
        "vwap",
        load_cached=load_cached,
        n_workers=n_workers,
        window=30,
    )
    if vwap is not None:
        result = result.merge(vwap, on=["ts", "symbol"], how="left")
        del vwap
        gc.collect()

    # Feature 3: Volume
    print("\n[3/11] Computing volume features (monthly)...")
    volume = cache.compute_feature_monthly(
        df,
        compute_volume_features,
        "volume",
        load_cached=load_cached,
        n_workers=n_workers,
    )
    if volume is not None:
        result = result.merge(volume, on=["ts", "symbol"], how="left")
        del volume
        gc.collect()

    # Feature 4: ATR
    print("\n[4/11] Computing ATR features (monthly)...")
    atr = cache.compute_feature_monthly(
        df,
        compute_atr_features,
        "atr",
        load_cached=load_cached,
        n_workers=n_workers,
        window=14,
    )
    if atr is not None:
        result = result.merge(atr, on=["ts", "symbol"], how="left")
        del atr
        gc.collect()

    # Feature 5: Session features (includes session VWAP)
    print("\n[5/11] Computing session features (monthly)...")
    session = cache.compute_feature_monthly(
        df,
        compute_session_features,
        "session",
        load_cached=load_cached,
        n_workers=n_workers,
    )
    if session is not None:
        result = result.merge(session, on=["ts", "symbol"], how="left")
        del session
        gc.collect()

    # Feature 6: Session range
    print("\n[6/11] Computing session range features (monthly)...")
    session_range = cache.compute_feature_monthly(
        df,
        compute_session_range_features,
        "session_range",
        load_cached=load_cached,
        n_workers=n_workers,
    )
    if session_range is not None:
        result = result.merge(session_range, on=["ts", "symbol"], how="left")
        del session_range
        gc.collect()

    # Feature 7: Time features (state-based, no need for monthly cache)
    print("\n[7/11] Computing time features...")
    result = compute_time_features(result, inplace=True)
    gc.collect()

    # Feature 8: Volume-price divergence (requires session range, compute per-month)
    print("\n[8/11] Computing volume-price divergence features (monthly)...")
    # For this feature, we need to pass the already-computed result
    volume_price = cache.compute_feature_monthly(
        result,
        compute_volume_price_features,
        "volume_price",
        load_cached=load_cached,
        n_workers=n_workers,
    )
    if volume_price is not None:
        # Merge only the volume-price columns, not the base columns
        vp_cols = [c for c in volume_price.columns if c not in ["ts", "symbol", "date"]]
        result = result.merge(
            volume_price[["ts", "symbol"] + vp_cols], on=["ts", "symbol"], how="left"
        )
        del volume_price
        gc.collect()

    # SPY-dependent features
    if spy_df is not None and not spy_df.empty:
        # Feature 9: SPY regime
        print("\n[9/11] Computing SPY regime features (monthly)...")
        spy_regime = cache.compute_feature_monthly(
            df,
            compute_spy_regime_features,
            "spy_regime",
            load_cached=load_cached,
            n_workers=1,
            spy_df=spy_df,
        )
        if spy_regime is not None:
            result = result.merge(spy_regime, on=["ts", "symbol"], how="left")
            del spy_regime
            gc.collect()

        # Feature 10: Relative strength vs SPY
        print("\n[10/11] Computing relative strength features (monthly)...")
        rel_strength = cache.compute_feature_monthly(
            df,
            compute_relative_strength_features,
            "relative_strength",
            load_cached=load_cached,
            n_workers=1,
            spy_df=spy_df,
        )
        if rel_strength is not None:
            result = result.merge(rel_strength, on=["ts", "symbol"], how="left")
            del rel_strength
            gc.collect()

    # Final cleanup
    result = result.drop(columns=["date"])

    # MEMORY FIX: Clean up date column from original df if we added it
    # This prevents memory accumulation in the calling code
    if not had_date_col and "date" in df.columns:
        del df["date"]

    return result
