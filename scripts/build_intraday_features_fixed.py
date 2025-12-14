#!/usr/bin/env python3
"""Build intraday features with timezone normalization and clean features."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def detect_timezone(df):
    """Detect if data is UTC or ET based on first hour."""
    first_hour = df["timestamp"][0].hour
    return "UTC" if first_hour >= 13 else "ET"


def normalize_to_et(df):
    """Convert all timestamps to ET."""
    tz = detect_timezone(df)
    if tz == "UTC":
        # Convert UTC to ET (subtract 4 hours for EDT)
        df = df.with_columns(
            (pl.col("timestamp") - pl.duration(hours=4)).alias("timestamp")
        )
    return df


def engineer_clean_features(df, target_date):
    """Engineer features with only relative/normalized values."""
    if isinstance(target_date, str):
        target_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        target_date_obj = target_date

    # Normalize timestamps to ET first
    df = normalize_to_et(df)

    # Market hours filter (now in ET)
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

    # Filter to target date
    df_pd["date"] = df_pd["timestamp"].dt.date
    df_pd = df_pd[df_pd["date"] == target_date_obj]

    if len(df_pd) < 50:
        return pl.DataFrame()

    # ONLY RELATIVE FEATURES - NO RAW PRICES

    # Returns and volatility
    df_pd["returns"] = df_pd["close"].pct_change()
    df_pd["returns_5"] = df_pd["close"].pct_change(5)
    df_pd["returns_10"] = df_pd["close"].pct_change(10)
    df_pd["volatility_5"] = df_pd["returns"].rolling(5, min_periods=1).std()
    df_pd["volatility_20"] = df_pd["returns"].rolling(20, min_periods=1).std()

    # Range and body (normalized by close)
    df_pd["range_pct"] = (df_pd["high"] - df_pd["low"]) / df_pd["close"]
    df_pd["body_pct"] = abs(df_pd["close"] - df_pd["open"]) / df_pd["close"]
    df_pd["upper_wick_pct"] = (
        df_pd["high"] - df_pd[["open", "close"]].max(axis=1)
    ) / df_pd["close"]
    df_pd["lower_wick_pct"] = (
        df_pd[["open", "close"]].min(axis=1) - df_pd["low"]
    ) / df_pd["close"]

    # Volume ratios (normalized)
    df_pd["volume_ma5"] = df_pd["volume"].rolling(5, min_periods=1).mean()
    df_pd["volume_ma20"] = df_pd["volume"].rolling(20, min_periods=1).mean()
    df_pd["volume_ratio"] = df_pd["volume"] / (df_pd["volume_ma5"] + 1)
    df_pd["volume_ratio_20"] = df_pd["volume"] / (df_pd["volume_ma20"] + 1)
    df_pd["volume_momentum"] = df_pd["volume"].pct_change(5)

    # ATR normalized by price
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

    # Time features (now in ET)
    df_pd["hour_et"] = df_pd["timestamp"].dt.hour
    df_pd["minute"] = df_pd["timestamp"].dt.minute
    df_pd["is_morning"] = (df_pd["hour_et"] < 12).astype(int)
    df_pd["time_since_open"] = (df_pd["hour_et"] - 9) * 60 + (df_pd["minute"] - 30)
    df_pd["time_to_close"] = (16 - df_pd["hour_et"]) * 60 - df_pd["minute"]

    # Price position (relative to recent range)
    df_pd["high_5"] = df_pd["high"].rolling(5, min_periods=1).max()
    df_pd["low_5"] = df_pd["low"].rolling(5, min_periods=1).min()
    df_pd["price_position"] = (df_pd["close"] - df_pd["low_5"]) / (
        df_pd["high_5"] - df_pd["low_5"] + 1e-8
    )

    # VWAP distance (normalized)
    df_pd["typical_price"] = (df_pd["high"] + df_pd["low"] + df_pd["close"]) / 3
    df_pd["vwap_num"] = (
        (df_pd["typical_price"] * df_pd["volume"]).rolling(20, min_periods=1).sum()
    )
    df_pd["vwap_den"] = df_pd["volume"].rolling(20, min_periods=1).sum()
    df_pd["vwap"] = df_pd["vwap_num"] / (df_pd["vwap_den"] + 1)
    df_pd["distance_from_vwap"] = (df_pd["close"] - df_pd["vwap"]) / df_pd["vwap"]

    # VPA features (normalized)
    df_pd["up_volume"] = np.where(df_pd["close"] > df_pd["open"], df_pd["volume"], 0)
    df_pd["down_volume"] = np.where(df_pd["close"] < df_pd["open"], df_pd["volume"], 0)
    df_pd["up_volume_5"] = df_pd["up_volume"].rolling(5, min_periods=1).sum()
    df_pd["down_volume_5"] = df_pd["down_volume"].rolling(5, min_periods=1).sum()
    # Normalize pressure ratio
    raw_pressure = df_pd["up_volume_5"] / (df_pd["down_volume_5"] + 1)
    df_pd["pressure_ratio"] = np.clip(raw_pressure, 0.1, 10.0)  # Cap extreme values

    # ICT features (improved)
    df_pd["is_bullish"] = (df_pd["close"] > df_pd["open"]).astype(int)
    df_pd["is_bearish"] = (df_pd["close"] < df_pd["open"]).astype(int)

    # Displacement (significant moves)
    df_pd["displacement_up"] = (
        (df_pd["returns"] > 0) & (df_pd["returns"] > df_pd["volatility_5"] * 2)
    ).astype(int)
    df_pd["displacement_down"] = (
        (df_pd["returns"] < 0) & (abs(df_pd["returns"]) > df_pd["volatility_5"] * 2)
    ).astype(int)

    # Order blocks (improved)
    df_pd["prev_bearish"] = df_pd["is_bearish"].shift(1)
    df_pd["prev_bullish"] = df_pd["is_bullish"].shift(1)
    df_pd["order_block_bull"] = (
        (df_pd["prev_bearish"] == 1) & (df_pd["displacement_up"] == 1)
    ).astype(int)
    df_pd["order_block_bear"] = (
        (df_pd["prev_bullish"] == 1) & (df_pd["displacement_down"] == 1)
    ).astype(int)

    # Break of structure
    df_pd["prev_high_5"] = df_pd["high_5"].shift(1)
    df_pd["prev_low_5"] = df_pd["low_5"].shift(1)
    df_pd["bos_up"] = (df_pd["close"] > df_pd["prev_high_5"]).astype(int)
    df_pd["bos_down"] = (df_pd["close"] < df_pd["prev_low_5"]).astype(int)

    # Kill zones (NY session)
    df_pd["ny_open_killzone"] = (
        (df_pd["hour_et"] >= 9) & (df_pd["hour_et"] < 11)
    ).astype(int)
    df_pd["ny_close_killzone"] = (
        (df_pd["hour_et"] >= 14) & (df_pd["hour_et"] < 16)
    ).astype(int)

    # Labels with ATR normalization
    df_pd["entry_close"] = df_pd["close"].shift(-1)
    df_pd["entry_timestamp"] = df_pd["timestamp"].shift(-1)
    df_pd["exit_close"] = df_pd["close"].shift(-6)
    df_pd["exit_timestamp"] = df_pd["timestamp"].shift(-6)

    df_pd["forward_return"] = (df_pd["exit_close"] - df_pd["entry_close"]) / df_pd[
        "entry_close"
    ]
    df_pd["atr_threshold"] = df_pd["atr_pct"] * 1.5
    df_pd["label_long_atr"] = (df_pd["forward_return"] > df_pd["atr_threshold"]).astype(
        int
    )
    df_pd["label_short_atr"] = (
        df_pd["forward_return"] < -df_pd["atr_threshold"]
    ).astype(int)

    # Drop rows without valid same-day entry/exit
    df_pd = df_pd.dropna(subset=["entry_close", "exit_close"])
    df_pd["entry_date"] = df_pd["entry_timestamp"].dt.date
    df_pd["exit_date"] = df_pd["exit_timestamp"].dt.date
    df_pd = df_pd[
        (df_pd["entry_date"] == target_date_obj)
        & (df_pd["exit_date"] == target_date_obj)
    ]

    # Filter minimum ATR and avoid first/last periods
    df_pd = df_pd[df_pd["atr_pct"] >= 0.005]  # Min 0.5% ATR
    df_pd = df_pd[~((df_pd["hour_et"] == 9) & (df_pd["minute"] < 45))]  # Skip 9:30-9:45
    df_pd = df_pd[
        ~((df_pd["hour_et"] == 15) & (df_pd["minute"] >= 30))
    ]  # Skip 15:30-16:00

    # Clean up intermediate columns AND all raw price columns
    cols_to_drop = [
        "prev_close",
        "tr",
        "high_5",
        "low_5",
        "prev_high_5",
        "prev_low_5",
        "typical_price",
        "vwap_num",
        "vwap_den",
        "vwap",
        "up_volume",
        "down_volume",
        "up_volume_5",
        "down_volume_5",
        "volume_ma5",
        "volume_ma20",
        "prev_bearish",
        "prev_bullish",
        "entry_date",
        "exit_date",
        "minute",
        # Remove ALL raw price columns
        "open",
        "high",
        "low",
        "close",
        "entry_close",
        "exit_close",
        # Remove additional raw features from gold data
        "first_open",
        "vwap_session",
        "prev_session_close",
    ]
    df_pd = df_pd.drop(columns=[c for c in cols_to_drop if c in df_pd.columns])

    return pl.from_pandas(df_pd)


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
    logging.info(
        "BUILDING FIXED INTRADAY FEATURES: Timezone normalized, clean features"
    )
    logging.info("=" * 80)

    output_dir = Path("run/intraday_features_fixed")
    output_dir.mkdir(parents=True, exist_ok=True)

    sip = load_sip()
    sip_by_date = sip.group_by("date").agg(pl.col("symbol"))
    dates = sorted(sip_by_date["date"].to_list())

    all_features = []
    processed = 0

    for i, date in enumerate(dates, 1):
        symbols = sip_by_date.filter(pl.col("date") == date)["symbol"][0]

        date_features = []
        for symbol in symbols:
            df = load_intraday_bars(symbol, date)
            if df is None or len(df) == 0:
                continue

            try:
                features = engineer_clean_features(df, date)
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
    logging.info("FIXED FEATURES COMPLETE")
    logging.info("=" * 80)
    logging.info(f"Total bars: {len(combined):,}")
    logging.info(f"Unique symbols: {combined['symbol'].n_unique()}")
    logging.info(f"Date range: {combined['date'].min()} to {combined['date'].max()}")

    # Show hour distribution (should be balanced now)
    pdf = combined.to_pandas()
    pdf["hour"] = pdf["timestamp"].dt.hour
    logging.info("\nHour distribution (ET):")
    for h in sorted(pdf["hour"].unique()):
        count = len(pdf[pdf["hour"] == h])
        pct = count / len(pdf) * 100
        logging.info(f"  Hour {h}: {count:,} ({pct:.1f}%)")

    logging.info(f"\nSaved to: {output_file}")


if __name__ == "__main__":
    main()
