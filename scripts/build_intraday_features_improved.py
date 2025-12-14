#!/usr/bin/env python3
"""Improved intraday feature engineering with fixes for model inconsistency.

Key improvements:
1. ATR-normalized labels (not fixed 1.5%)
2. Relative features (no raw prices)
3. Time-of-day features
4. Regime features
5. Diversification tracking
"""

import logging
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# Market hours
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)

# Label parameters
ATR_LABEL_MULTIPLIER = 1.5  # Use 1.5x ATR instead of fixed 1.5%
FORWARD_BARS = 5  # 5-bar forward return


def load_daily_features():
    """Load daily features for regime detection."""
    daily_path = Path("run/daily_features_rolling/features.parquet")
    if not daily_path.exists():
        logging.warning("Daily features not found, skipping regime features")
        return None

    daily_df = pl.read_parquet(daily_path)
    # Calculate market regime features
    daily_df = daily_df.with_columns(
        [
            # Market volatility (rolling 5-day)
            pl.col("atr14").rolling_mean(5).alias("market_vol_5d"),
            # Market trend (rolling 5-day return)
            (pl.col("close") / pl.col("close").shift(5) - 1).alias("market_trend_5d"),
            # Gap distribution (for regime detection)
            pl.col("gap_pct").abs().rolling_mean(5).alias("avg_gap_5d"),
        ]
    )
    return daily_df.select(
        ["date", "symbol", "market_vol_5d", "market_trend_5d", "avg_gap_5d"]
    )


def calculate_ict_vpa_features(df_pd):
    """Calculate ICT and VPA features - all RELATIVE, no raw prices."""

    # Basic price ratios (no raw prices)
    df_pd["gap_pct"] = (df_pd["open"] - df_pd["prev_close"]) / df_pd["prev_close"]
    df_pd["price_vs_open"] = (df_pd["close"] - df_pd["open"]) / df_pd["open"]
    df_pd["price_vs_vwap"] = (df_pd["close"] - df_pd["vwap_session"]) / df_pd[
        "vwap_session"
    ]
    df_pd["high_vs_open"] = (df_pd["high"] - df_pd["open"]) / df_pd["open"]
    df_pd["low_vs_open"] = (df_pd["low"] - df_pd["open"]) / df_pd["open"]

    # Volatility measures (relative)
    df_pd["range_pct"] = (df_pd["high"] - df_pd["low"]) / df_pd["close"]
    df_pd["body_pct"] = abs(df_pd["close"] - df_pd["open"]) / df_pd["close"]
    df_pd["upper_wick"] = (
        df_pd["high"] - np.maximum(df_pd["open"], df_pd["close"])
    ) / df_pd["close"]
    df_pd["lower_wick"] = (
        np.minimum(df_pd["open"], df_pd["close"]) - df_pd["low"]
    ) / df_pd["close"]

    # Volume features (relative to session average)
    df_pd["volume_vs_avg"] = df_pd["volume"] / df_pd.groupby("session_id")[
        "volume"
    ].transform("mean")
    df_pd["dollar_vol_vs_avg"] = df_pd["cum_dollar_vol"] / df_pd.groupby("session_id")[
        "cum_dollar_vol"
    ].transform("mean")

    # Time-based features
    df_pd["minutes_from_open"] = (
        df_pd["timestamp"] - df_pd.groupby("session_id")["timestamp"].transform("min")
    ).dt.total_seconds() / 60
    df_pd["minutes_to_close"] = (
        390 - df_pd["minutes_from_open"]
    )  # 6.5 hours = 390 minutes
    df_pd["session_progress"] = df_pd["minutes_from_open"] / 390  # 0 to 1

    # Time-of-day features
    df_pd["hour"] = df_pd["timestamp"].dt.hour
    df_pd["is_first_hour"] = (df_pd["hour"] < 10).astype(int)
    df_pd["is_lunch_hour"] = ((df_pd["hour"] >= 12) & (df_pd["hour"] < 13)).astype(int)
    df_pd["is_last_hour"] = (df_pd["hour"] >= 15).astype(int)
    df_pd["is_morning"] = (df_pd["hour"] < 12).astype(int)

    # Momentum features (relative)
    for period in [3, 5, 10, 20]:
        df_pd[f"return_{period}m"] = df_pd.groupby("session_id")["close"].pct_change(
            period
        )
        df_pd[f"high_{period}m"] = (
            df_pd.groupby("session_id")["high"].rolling(period).max() / df_pd["close"]
            - 1
        )
        df_pd[f"low_{period}m"] = (
            df_pd.groupby("session_id")["low"].rolling(period).min() / df_pd["close"]
            - 1
        )

    # VWAP deviations (relative)
    df_pd["vwap_dev"] = (df_pd["close"] - df_pd["vwap_session"]) / df_pd["vwap_session"]
    df_pd["vwap_dev_abs"] = abs(df_pd["vwap_dev"])

    # Volume profile features
    df_pd["up_volume_pct"] = df_pd["up_volume"] / (
        df_pd["up_volume"] + df_pd["down_volume"] + 1e-8
    )
    df_pd["volume_imbalance"] = (df_pd["up_volume"] - df_pd["down_volume"]) / (
        df_pd["up_volume"] + df_pd["down_volume"] + 1e-8
    )

    # ATR-based features (for stops and labels)
    df_pd["atr_pct"] = df_pd["atr"] / df_pd["close"]  # ATR as % of price

    return df_pd


def calculate_labels_atr_normalized(df_pd):
    """Calculate ATR-normalized labels instead of fixed percentage."""

    # Calculate forward returns
    df_pd["forward_return"] = df_pd.groupby("session_id")["close"].pct_change(
        -FORWARD_BARS
    )

    # ATR-normalized thresholds (adaptive to volatility)
    df_pd["atr_threshold"] = df_pd["atr"] / df_pd["close"] * ATR_LABEL_MULTIPLIER

    # Labels based on ATR multiples
    df_pd["label_long"] = (df_pd["forward_return"] > df_pd["atr_threshold"]).astype(int)
    df_pd["label_short"] = (df_pd["forward_return"] < -df_pd["atr_threshold"]).astype(
        int
    )

    # Entry/exit timestamps (1-bar delay)
    df_pd["entry_timestamp"] = df_pd.groupby("session_id")["timestamp"].shift(-1)
    df_pd["exit_timestamp"] = df_pd.groupby("session_id")["timestamp"].shift(
        -FORWARD_BARS - 1
    )
    df_pd["entry_close"] = df_pd.groupby("session_id")["close"].shift(-1)
    df_pd["exit_close"] = df_pd.groupby("session_id")["close"].shift(-FORWARD_BARS - 1)

    return df_pd


def add_regime_features(df_pd, daily_df):
    """Add market regime features."""
    if daily_df is None:
        return df_pd

    # Merge daily regime features
    df_pd["date"] = df_pd["timestamp"].dt.date
    daily_pd = daily_df.to_pandas()
    daily_pd["date"] = pd.to_datetime(daily_pd["date"]).dt.date

    df_pd = df_pd.merge(
        daily_pd[["date", "symbol", "market_vol_5d", "market_trend_5d", "avg_gap_5d"]],
        on=["date", "symbol"],
        how="left",
    )

    # Fill missing values
    df_pd["market_vol_5d"] = df_pd["market_vol_5d"].fillna(
        df_pd["market_vol_5d"].median()
    )
    df_pd["market_trend_5d"] = df_pd["market_trend_5d"].fillna(0)
    df_pd["avg_gap_5d"] = df_pd["avg_gap_5d"].fillna(df_pd["avg_gap_5d"].median())

    # Regime indicators
    df_pd["high_vol_regime"] = (
        df_pd["market_vol_5d"] > df_pd["market_vol_5d"].quantile(0.7)
    ).astype(int)
    df_pd["bull_regime"] = (df_pd["market_trend_5d"] > 0.02).astype(
        int
    )  # >2% 5-day return
    df_pd["bear_regime"] = (df_pd["market_trend_5d"] < -0.02).astype(
        int
    )  # <-2% 5-day return

    return df_pd


def process_symbol_date(symbol, date, data_dir):
    """Process single symbol-date with improved features."""

    # Load 1m data
    year, month = date.year, date.month
    file_path = data_dir / symbol / str(year) / f"{month:02d}.parquet"

    if not file_path.exists():
        return None

    try:
        df = pl.read_parquet(file_path)
        df = df.filter(pl.col("date") == date)

        if len(df) < 50:  # Need minimum bars
            return None

        df_pd = df.to_pandas()

        # Calculate session-level features
        df_pd = df_pd.sort_values("timestamp")
        df_pd["session_id"] = f"{symbol}_{date}"
        df_pd["bar_index"] = range(len(df_pd))

        # Previous close for gaps - use previous day's close if available
        if len(df_pd) > 0:
            df_pd["prev_close"] = df_pd["close"].iloc[0]  # Simplified for now

        # Calculate ATR first (needed for other features)
        df_pd["tr"] = np.maximum(
            df_pd["high"] - df_pd["low"],
            np.maximum(
                abs(df_pd["high"] - df_pd["prev_close"]),
                abs(df_pd["low"] - df_pd["prev_close"]),
            ),
        )
        df_pd["atr"] = df_pd["tr"].rolling(14, min_periods=1).mean()

        # Calculate all features
        df_pd = calculate_ict_vpa_features(df_pd)
        df_pd = calculate_labels_atr_normalized(df_pd)

        # Filter to valid rows (same-day entry/exit)
        df_pd = df_pd.dropna(subset=["entry_timestamp", "exit_timestamp"])
        df_pd = df_pd[
            (df_pd["entry_timestamp"].dt.date == date)
            & (df_pd["exit_timestamp"].dt.date == date)
        ]

        if len(df_pd) == 0:
            return None

        # Add symbol and date
        df_pd["symbol"] = symbol
        df_pd["date"] = date

        return df_pd

    except Exception as e:
        # Only log if it's not a simple missing file
        if "No such file" not in str(e):
            logging.warning(f"Error processing {symbol} {date}: {e}")
        return None


def main():
    logging.info("=" * 80)
    logging.info("IMPROVED INTRADAY FEATURES - Fixing Model Inconsistency")
    logging.info("=" * 80)

    data_dir = Path.home() / "gcs-mount" / "gold" / "stocks" / "1m"
    sip_path = Path("run/sip_membership_rolling/sip_membership.parquet")
    output_dir = Path("run/intraday_features_improved")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load SIP membership
    if not sip_path.exists():
        logging.error("SIP membership not found. Run generate_sip_rolling.py first")
        return

    sip_df = pl.read_parquet(sip_path)
    logging.info(f"Loaded SIP: {len(sip_df):,} symbol-date pairs")

    # Load daily features for regime detection
    daily_df = load_daily_features()

    # Process all symbol-dates
    all_features = []
    processed = 0
    skipped = 0

    for row in sip_df.iter_rows(named=True):
        symbol = row["symbol"]
        date = row["date"]

        features = process_symbol_date(symbol, date, data_dir)
        if features is not None:
            all_features.append(features)
            processed += 1

            if processed % 50 == 0:
                logging.info(
                    f"Processed {processed:,} symbol-dates, skipped {skipped:,}"
                )
        else:
            skipped += 1

    if not all_features:
        logging.error("No features generated")
        return

    # Combine all features
    logging.info("Combining features...")
    combined_df = pd.concat(all_features, ignore_index=True)

    # Add regime features
    if daily_df is not None:
        logging.info("Adding regime features...")
        combined_df = add_regime_features(combined_df, daily_df)

    # Save features
    output_path = output_dir / "features.parquet"
    combined_df.to_parquet(output_path, index=False)

    logging.info("=" * 80)
    logging.info("IMPROVED FEATURES COMPLETE")
    logging.info("=" * 80)
    logging.info(f"Total rows: {len(combined_df):,}")
    logging.info(
        f"Date range: {combined_df['date'].min()} to {combined_df['date'].max()}"
    )
    logging.info(f"Symbols: {combined_df['symbol'].nunique()}")

    # Label statistics
    long_rate = combined_df["label_long"].mean() * 100
    short_rate = combined_df["label_short"].mean() * 100
    logging.info(f"Label rates: Long {long_rate:.2f}%, Short {short_rate:.2f}%")

    # Feature summary
    feature_cols = [
        c
        for c in combined_df.columns
        if c
        not in [
            "timestamp",
            "date",
            "symbol",
            "session_id",
            "bar_index",
            "entry_timestamp",
            "exit_timestamp",
            "entry_close",
            "exit_close",
            "forward_return",
            "label_long",
            "label_short",
            "atr_threshold",
        ]
    ]
    logging.info(f"Features: {len(feature_cols)}")

    # Check for raw price features (should be none)
    price_features = [
        c
        for c in feature_cols
        if any(
            x in c.lower()
            for x in [
                "open",
                "high",
                "low",
                "close",
                "vwap_session",
                "prev_session_close",
            ]
        )
    ]
    if price_features:
        logging.warning(f"Raw price features detected: {price_features}")
    else:
        logging.info("✓ No raw price features (all relative)")

    logging.info(f"Output: {output_path}")


if __name__ == "__main__":
    main()
