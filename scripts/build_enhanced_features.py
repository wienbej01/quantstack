#!/usr/bin/env python3
"""Enhanced feature builder implementing all recommendations."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def load_spy_data(date, data_root="/home/jacobw/gcs-mount/gold/stocks/1m"):
    """Load SPY data for market context."""
    spy_path = Path(data_root) / "SPY"
    if isinstance(date, str):
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    else:
        date_obj = date

    year = date_obj.year
    month = date_obj.strftime("%Y-%m")

    file_path = spy_path / str(year) / f"{month}.parquet"
    if not file_path.exists():
        return None

    try:
        df = pl.read_parquet(file_path)
        if "ts" in df.columns:
            df = df.rename({"ts": "timestamp"})
        df = df.with_columns(pl.col("timestamp").cast(pl.Datetime))

        # Load 30 days for context
        start_date = date_obj - timedelta(days=30)
        df = df.filter(
            (pl.col("timestamp").dt.date() >= start_date)
            & (pl.col("timestamp").dt.date() <= date_obj)
        )
        return df.sort("timestamp") if len(df) > 0 else None
    except:
        return None


def normalize_to_et(df):
    """Convert timestamps to ET."""
    first_hour = df["timestamp"][0].hour
    if first_hour >= 13:  # UTC data
        df = df.with_columns(
            (pl.col("timestamp") - pl.duration(hours=4)).alias("timestamp")
        )
    return df


def engineer_enhanced_features(df, spy_df, target_date):
    """Engineer enhanced features with all recommendations."""
    if isinstance(target_date, str):
        target_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        target_date_obj = target_date

    # Normalize timestamps
    df = normalize_to_et(df)
    if spy_df is not None:
        spy_df = normalize_to_et(spy_df)

    # Market hours filter
    df = df.filter(
        (
            (pl.col("timestamp").dt.hour() > 9)
            | (
                (pl.col("timestamp").dt.hour() == 9)
                & (pl.col("timestamp").dt.minute() >= 30)
            )
        )
        & (pl.col("timestamp").dt.hour() < 16)
    )

    df_pd = df.to_pandas()
    df_pd["date"] = df_pd["timestamp"].dt.date
    df_pd = df_pd[df_pd["date"] == target_date_obj]

    if len(df_pd) < 50:
        return pl.DataFrame()

    # Prepare SPY data for correlation
    spy_returns = None
    if spy_df is not None:
        spy_pd = spy_df.to_pandas()
        spy_pd = spy_pd[spy_pd["timestamp"].dt.date == target_date_obj]
        if len(spy_pd) > 0:
            spy_pd = spy_pd.sort_values("timestamp").reset_index(drop=True)
            spy_returns = spy_pd["close"].pct_change()

    # === BASIC FEATURES ===
    df_pd["returns"] = df_pd["close"].pct_change()
    df_pd["returns_5"] = df_pd["close"].pct_change(5)
    df_pd["returns_10"] = df_pd["close"].pct_change(10)

    # Volatility
    df_pd["volatility_5"] = df_pd["returns"].rolling(5, min_periods=1).std()
    df_pd["volatility_20"] = df_pd["returns"].rolling(20, min_periods=1).std()

    # Range and body (normalized)
    df_pd["range_pct"] = (df_pd["high"] - df_pd["low"]) / df_pd["close"]
    df_pd["body_pct"] = abs(df_pd["close"] - df_pd["open"]) / df_pd["close"]
    df_pd["upper_wick_pct"] = (
        df_pd["high"] - df_pd[["open", "close"]].max(axis=1)
    ) / df_pd["close"]
    df_pd["lower_wick_pct"] = (
        df_pd[["open", "close"]].min(axis=1) - df_pd["low"]
    ) / df_pd["close"]

    # ATR normalized
    df_pd["prev_close"] = df_pd["close"].shift(1).fillna(df_pd["close"].iloc[0])
    df_pd["tr"] = np.maximum(
        df_pd["high"] - df_pd["low"],
        np.maximum(
            abs(df_pd["high"] - df_pd["prev_close"]),
            abs(df_pd["low"] - df_pd["prev_close"]),
        ),
    )
    df_pd["atr"] = df_pd["tr"].rolling(14, min_periods=1).mean()
    df_pd["atr_pct"] = df_pd["atr"] / df_pd["close"]

    # === MULTI-TIMEFRAME FEATURES (5m aggregates) ===
    df_pd["timestamp_5m"] = df_pd["timestamp"].dt.floor("5min")

    # 5-minute aggregates
    agg_5m = (
        df_pd.groupby("timestamp_5m")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .reset_index()
    )

    agg_5m["returns_5m"] = agg_5m["close"].pct_change()
    agg_5m["volatility_5m"] = agg_5m["returns_5m"].rolling(3, min_periods=1).std()
    agg_5m["volume_5m"] = agg_5m["volume"]
    agg_5m["volume_ma5_5m"] = agg_5m["volume_5m"].rolling(5, min_periods=1).mean()
    agg_5m["volume_ratio_5m"] = agg_5m["volume_5m"] / (agg_5m["volume_ma5_5m"] + 1)
    agg_5m["range_5m"] = (agg_5m["high"] - agg_5m["low"]) / agg_5m["close"]

    # Merge back to 1m data
    df_pd = df_pd.merge(
        agg_5m[
            [
                "timestamp_5m",
                "returns_5m",
                "volatility_5m",
                "volume_ratio_5m",
                "range_5m",
            ]
        ],
        on="timestamp_5m",
        how="left",
    )

    # === SESSION CONTEXT FEATURES ===
    session_open = df_pd["open"].iloc[0]
    session_high = df_pd["high"].max()
    session_low = df_pd["low"].min()
    prev_session_close = df_pd["prev_close"].iloc[0]

    # Gap analysis
    df_pd["gap_pct"] = (session_open - prev_session_close) / prev_session_close
    gap_size = abs(session_open - prev_session_close)
    df_pd["gap_fill_pct"] = np.where(
        gap_size > 0, (df_pd["close"] - session_open) / gap_size, 0
    )

    # Session range
    session_range = session_high - session_low
    df_pd["session_range_pct"] = session_range / session_open
    df_pd["distance_to_high"] = (session_high - df_pd["close"]) / df_pd["close"]
    df_pd["distance_to_low"] = (df_pd["close"] - session_low) / df_pd["close"]

    # === IMPROVED ICT FEATURES ===

    # Multi-bar FVG detection
    df_pd["fvg_bullish"] = (df_pd["low"].shift(-1) > df_pd["high"].shift(1)).astype(int)
    df_pd["fvg_bearish"] = (df_pd["high"].shift(-1) < df_pd["low"].shift(1)).astype(int)
    df_pd["fvg_size_pct"] = np.where(
        df_pd["fvg_bullish"],
        (df_pd["low"].shift(-1) - df_pd["high"].shift(1)) / df_pd["close"],
        np.where(
            df_pd["fvg_bearish"],
            (df_pd["low"].shift(1) - df_pd["high"].shift(-1)) / df_pd["close"],
            0,
        ),
    )

    # Check if FVG is unfilled
    df_pd["fvg_unfilled_bull"] = (
        df_pd["fvg_bullish"] & (df_pd["close"] < df_pd["low"].shift(-1))
    ).astype(int)
    df_pd["fvg_unfilled_bear"] = (
        df_pd["fvg_bearish"] & (df_pd["close"] > df_pd["high"].shift(-1))
    ).astype(int)

    # Displacement with volume confirmation
    volume_ma = df_pd["volume"].rolling(10, min_periods=1).mean()
    df_pd["displacement_up"] = (
        (df_pd["returns"] > df_pd["volatility_5"] * 2)
        & (df_pd["volume"] > volume_ma * 1.2)
    ).astype(int)
    df_pd["displacement_down"] = (
        (df_pd["returns"] < -df_pd["volatility_5"] * 2)
        & (df_pd["volume"] > volume_ma * 1.2)
    ).astype(int)

    # Order blocks with volume confirmation
    df_pd["is_bullish"] = (df_pd["close"] > df_pd["open"]).astype(int)
    df_pd["is_bearish"] = (df_pd["close"] < df_pd["open"]).astype(int)
    df_pd["prev_bearish"] = df_pd["is_bearish"].shift(1)
    df_pd["prev_bullish"] = df_pd["is_bullish"].shift(1)

    df_pd["order_block_bull"] = (
        (df_pd["prev_bearish"] == 1)
        & (df_pd["displacement_up"] == 1)
        & (df_pd["volume"] > volume_ma * 1.5)
    ).astype(int)
    df_pd["order_block_bear"] = (
        (df_pd["prev_bullish"] == 1)
        & (df_pd["displacement_down"] == 1)
        & (df_pd["volume"] > volume_ma * 1.5)
    ).astype(int)

    # Market structure (higher highs/lows)
    df_pd["high_5"] = df_pd["high"].rolling(5, min_periods=1).max()
    df_pd["low_5"] = df_pd["low"].rolling(5, min_periods=1).min()
    df_pd["structure_bullish"] = (df_pd["high_5"] > df_pd["high_5"].shift(5)).astype(
        int
    )
    df_pd["structure_bearish"] = (df_pd["low_5"] < df_pd["low_5"].shift(5)).astype(int)

    # === ENHANCED VPA FEATURES ===

    # Up/down volume
    df_pd["up_volume"] = np.where(df_pd["close"] > df_pd["open"], df_pd["volume"], 0)
    df_pd["down_volume"] = np.where(df_pd["close"] < df_pd["open"], df_pd["volume"], 0)
    df_pd["up_volume_5"] = df_pd["up_volume"].rolling(5, min_periods=1).sum()
    df_pd["down_volume_5"] = df_pd["down_volume"].rolling(5, min_periods=1).sum()

    # Cumulative delta
    df_pd["volume_delta"] = df_pd["up_volume"] - df_pd["down_volume"]
    df_pd["cum_delta"] = df_pd["volume_delta"].cumsum()
    df_pd["delta_divergence"] = (
        (df_pd["cum_delta"].diff() > 0) != (df_pd["close"].diff() > 0)
    ).astype(int)

    # Normalized pressure ratio
    raw_pressure = df_pd["up_volume_5"] / (df_pd["down_volume_5"] + 1)
    df_pd["pressure_ratio"] = np.clip(raw_pressure, 0.1, 10.0)

    # Volume momentum
    df_pd["volume_momentum"] = df_pd["volume"].pct_change(5)
    df_pd["volume_ma20"] = df_pd["volume"].rolling(20, min_periods=1).mean()
    df_pd["volume_ratio"] = df_pd["volume"] / (df_pd["volume_ma20"] + 1)

    # === MARKET CONTEXT FEATURES (SPY) ===
    if spy_returns is not None and len(spy_returns) == len(df_pd):
        # SPY correlation
        df_pd["spy_returns"] = spy_returns.values
        df_pd["spy_correlation_20"] = (
            df_pd["returns"].rolling(20).corr(df_pd["spy_returns"])
        )

        # Relative performance vs SPY
        df_pd["relative_to_spy"] = df_pd["returns"] - df_pd["spy_returns"]
        df_pd["outperforming_spy"] = (df_pd["relative_to_spy"] > 0).astype(int)
    else:
        df_pd["spy_correlation_20"] = 0
        df_pd["relative_to_spy"] = 0
        df_pd["outperforming_spy"] = 0

    # === TIME FEATURES ===
    df_pd["hour_et"] = df_pd["timestamp"].dt.hour
    df_pd["minute"] = df_pd["timestamp"].dt.minute
    df_pd["is_morning"] = (df_pd["hour_et"] < 12).astype(int)
    df_pd["time_since_open"] = (df_pd["hour_et"] - 9) * 60 + (df_pd["minute"] - 30)
    df_pd["time_to_close"] = (16 - df_pd["hour_et"]) * 60 - df_pd["minute"]

    # Kill zones
    df_pd["ny_open_killzone"] = (
        (df_pd["hour_et"] >= 9) & (df_pd["hour_et"] < 11)
    ).astype(int)
    df_pd["ny_close_killzone"] = (
        (df_pd["hour_et"] >= 14) & (df_pd["hour_et"] < 16)
    ).astype(int)

    # === REGIME DETECTION ===
    df_pd["volatility_regime"] = np.where(
        df_pd["volatility_20"] > df_pd["volatility_20"].quantile(0.7),
        1,
        np.where(df_pd["volatility_20"] < df_pd["volatility_20"].quantile(0.3), -1, 0),
    )

    # === LABELS (LONGER HORIZON) ===

    # Test multiple exit horizons
    for bars in [10, 15, 30]:
        df_pd[f"forward_return_{bars}"] = df_pd["close"].pct_change(-bars)
        df_pd[f"label_long_{bars}"] = (
            df_pd[f"forward_return_{bars}"] > df_pd["atr_pct"] * 1.5
        ).astype(int)
        df_pd[f"label_short_{bars}"] = (
            df_pd[f"forward_return_{bars}"] < -df_pd["atr_pct"] * 1.5
        ).astype(int)

    # Multi-class labels
    forward_return = df_pd["forward_return_15"]  # Use 15-bar as default
    df_pd["label_multiclass"] = np.where(
        forward_return > df_pd["atr_pct"] * 2,
        2,
        np.where(
            forward_return > df_pd["atr_pct"],
            1,
            np.where(
                forward_return < -df_pd["atr_pct"] * 2,
                -2,
                np.where(forward_return < -df_pd["atr_pct"], -1, 0),
            ),
        ),
    )

    # Drop rows without valid labels
    df_pd = df_pd.dropna(subset=["forward_return_15"])

    # Filter minimum ATR and avoid first/last periods
    df_pd = df_pd[df_pd["atr_pct"] >= 0.005]
    df_pd = df_pd[~((df_pd["hour_et"] == 9) & (df_pd["minute"] < 45))]
    df_pd = df_pd[~((df_pd["hour_et"] == 15) & (df_pd["minute"] >= 30))]

    # Clean up intermediate columns and ensure consistent types
    cols_to_drop = [
        "prev_close",
        "tr",
        "high_5",
        "low_5",
        "timestamp_5m",
        "minute",
        "up_volume",
        "down_volume",
        "up_volume_5",
        "down_volume_5",
        "volume_ma20",
        "prev_bearish",
        "prev_bullish",
        "atr",
        "spy_returns",
    ]
    df_pd = df_pd.drop(columns=[c for c in cols_to_drop if c in df_pd.columns])

    # Convert to polars and ensure consistent schema
    result_df = pl.from_pandas(df_pd)

    # Cast all numeric columns to Float64 for consistency
    numeric_cols = [
        c
        for c in result_df.columns
        if result_df[c].dtype in [pl.Int64, pl.Int32, pl.Float32]
    ]
    if numeric_cols:
        result_df = result_df.with_columns(
            [pl.col(c).cast(pl.Float64) for c in numeric_cols]
        )

    return result_df


def load_intraday_bars(symbol, date, data_root="/home/jacobw/gcs-mount/gold/stocks/1m"):
    """Load intraday bars for symbol and date."""
    symbol_path = Path(data_root) / symbol
    if not symbol_path.exists():
        return None

    if isinstance(date, str):
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    else:
        date_obj = date

    year = date_obj.year
    month = date_obj.strftime("%Y-%m")
    prev_month = (date_obj.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    prev_year = (date_obj.replace(day=1) - timedelta(days=1)).year

    files_to_try = [
        symbol_path / str(year) / f"{month}.parquet",
        symbol_path / str(prev_year) / f"{prev_month}.parquet",
    ]

    dfs = []
    for file_path in files_to_try:
        if file_path.exists():
            try:
                df = pl.read_parquet(file_path)
                if "ts" in df.columns:
                    df = df.rename({"ts": "timestamp"})
                dfs.append(df)
            except:
                pass

    if not dfs:
        return None

    df = pl.concat(dfs)
    df = df.with_columns(pl.col("timestamp").cast(pl.Datetime))

    start_date = date_obj - timedelta(days=30)
    df = df.filter(
        (pl.col("timestamp").dt.date() >= start_date)
        & (pl.col("timestamp").dt.date() <= date_obj)
    )

    return df.sort("timestamp") if len(df) > 0 else None


def load_sip():
    """Load SIP membership."""
    sip_path = Path("run/sip_membership_rolling/sip_membership.parquet")
    return pl.read_parquet(sip_path)


def main():
    logging.info("=" * 80)
    logging.info("BUILDING ENHANCED FEATURES: All recommendations implemented")
    logging.info("=" * 80)

    output_dir = Path("run/enhanced_features")
    output_dir.mkdir(parents=True, exist_ok=True)

    sip = load_sip()
    sip_by_date = sip.group_by("date").agg(pl.col("symbol"))
    dates = sorted(sip_by_date["date"].to_list())

    all_features = []
    processed = 0

    for i, date in enumerate(dates, 1):
        symbols = sip_by_date.filter(pl.col("date") == date)["symbol"][0]

        # Load SPY data for this date
        spy_df = load_spy_data(date)

        date_features = []
        for symbol in symbols:
            df = load_intraday_bars(symbol, date)
            if df is None or len(df) == 0:
                continue

            try:
                features = engineer_enhanced_features(df, spy_df, date)
                if len(features) > 0:
                    features = features.with_columns(pl.lit(symbol).alias("symbol"))
                    date_features.append(features)
            except Exception as e:
                logging.debug(f"Error {symbol} {date}: {e}")

        if date_features:
            combined = pl.concat(date_features)
            all_features.append(combined)
            processed += len(combined)

        if i % 10 == 0:
            logging.info(f"[{i}/{len(dates)}] {date}: {processed:,} total features")

    if not all_features:
        logging.error("No features generated!")
        return

    combined = pl.concat(all_features)
    output_file = output_dir / "features.parquet"
    combined.write_parquet(output_file)

    logging.info("=" * 80)
    logging.info("ENHANCED FEATURES COMPLETE")
    logging.info("=" * 80)
    logging.info(f"Total bars: {len(combined):,}")
    logging.info(f"Unique symbols: {combined['symbol'].n_unique()}")
    logging.info(f"Date range: {combined['date'].min()} to {combined['date'].max()}")
    logging.info(f"Feature columns: {len(combined.columns)}")

    # Show feature count by category
    pdf = combined.to_pandas()
    feature_cols = [
        c
        for c in pdf.columns
        if c not in ["date", "symbol", "timestamp"]
        and not c.startswith("label_")
        and not c.startswith("forward_return")
    ]
    logging.info(f"Model features: {len(feature_cols)}")

    logging.info(f"Saved to: {output_file}")


if __name__ == "__main__":
    main()
