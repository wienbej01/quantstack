#!/usr/bin/env python3
"""Build intraday features for rolling period with 30 ICT features."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    handlers=[
        logging.FileHandler("/tmp/build_intraday_rolling.log"),
        logging.StreamHandler(),
    ],
)


def load_sip():
    sip_path = Path("run/sip_membership_rolling/sip_membership.parquet")
    sip = pl.read_parquet(sip_path)
    logging.info(f"Loaded SIP: {len(sip)} selections")
    return sip


def load_intraday_bars(symbol, date, data_root="/home/jacobw/gcs-mount/gold/stocks/1m"):
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


def engineer_features(df, target_date):
    if isinstance(target_date, str):
        target_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        target_date_obj = target_date

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

    # Base features
    df_pd["returns"] = df_pd["close"].pct_change()
    df_pd["returns_5"] = df_pd["close"].pct_change(5)
    df_pd["returns_10"] = df_pd["close"].pct_change(10)
    df_pd["returns_20"] = df_pd["close"].pct_change(20)
    df_pd["range_pct"] = (df_pd["high"] - df_pd["low"]) / df_pd["close"]
    df_pd["body_pct"] = abs(df_pd["close"] - df_pd["open"]) / df_pd["close"]

    df_pd["candle_top"] = df_pd[["open", "close"]].max(axis=1)
    df_pd["candle_bottom"] = df_pd[["open", "close"]].min(axis=1)
    df_pd["upper_wick"] = (df_pd["high"] - df_pd["candle_top"]) / df_pd["close"]
    df_pd["lower_wick"] = (df_pd["candle_bottom"] - df_pd["low"]) / df_pd["close"]

    df_pd["volume_ma5"] = df_pd["volume"].rolling(5, min_periods=1).mean()
    df_pd["volume_ma20"] = df_pd["volume"].rolling(20, min_periods=1).mean()
    df_pd["volume_ratio"] = df_pd["volume"] / (df_pd["volume_ma5"] + 1)
    df_pd["volume_ratio_20"] = df_pd["volume"] / (df_pd["volume_ma20"] + 1)

    df_pd["volatility_5"] = df_pd["returns"].rolling(5, min_periods=1).std()
    df_pd["volatility_20"] = df_pd["returns"].rolling(20, min_periods=1).std()

    # ATR for stop loss calculation
    df_pd["prev_close"] = df_pd["close"].shift(1)
    df_pd["tr1"] = df_pd["high"] - df_pd["low"]
    df_pd["tr2"] = abs(df_pd["high"] - df_pd["prev_close"])
    df_pd["tr3"] = abs(df_pd["low"] - df_pd["prev_close"])
    df_pd["tr"] = df_pd[["tr1", "tr2", "tr3"]].max(axis=1)
    df_pd["atr"] = df_pd["tr"].rolling(14, min_periods=1).mean()
    df_pd = df_pd.drop(columns=["prev_close", "tr1", "tr2", "tr3", "tr"])

    df_pd["time_since_open"] = (df_pd["timestamp"].dt.hour - 9) * 60 + (
        df_pd["timestamp"].dt.minute - 30
    )
    df_pd["time_to_close"] = (16 - df_pd["timestamp"].dt.hour) * 60 - df_pd[
        "timestamp"
    ].dt.minute

    df_pd["high_5"] = df_pd["high"].rolling(5, min_periods=1).max()
    df_pd["low_5"] = df_pd["low"].rolling(5, min_periods=1).min()
    df_pd["price_position"] = (df_pd["close"] - df_pd["low_5"]) / (
        df_pd["high_5"] - df_pd["low_5"] + 1e-8
    )

    # ICT features
    df_pd["prev_high"] = df_pd["high"].shift(1)
    df_pd["prev_low"] = df_pd["low"].shift(1)
    df_pd["next_low"] = df_pd["low"].shift(-1)
    df_pd["next_high"] = df_pd["high"].shift(-1)
    df_pd["fvg_up"] = (df_pd["prev_high"] < df_pd["next_low"]).astype(int)
    df_pd["fvg_down"] = (df_pd["prev_low"] > df_pd["next_high"]).astype(int)
    df_pd["fvg_size"] = np.where(
        df_pd["fvg_up"],
        df_pd["next_low"] - df_pd["prev_high"],
        np.where(df_pd["fvg_down"], df_pd["prev_low"] - df_pd["next_high"], 0),
    )
    df_pd["fvg_size_pct"] = df_pd["fvg_size"] / df_pd["close"]

    df_pd["displacement_up"] = (
        (df_pd["returns"] > 0) & (df_pd["returns"].abs() > df_pd["volatility_5"] * 2)
    ).astype(int)
    df_pd["displacement_down"] = (
        (df_pd["returns"] < 0) & (df_pd["returns"].abs() > df_pd["volatility_5"] * 2)
    ).astype(int)

    df_pd["is_bullish"] = (df_pd["close"] > df_pd["open"]).astype(int)
    df_pd["is_bearish"] = (df_pd["close"] < df_pd["open"]).astype(int)
    df_pd["prev_bearish"] = df_pd["is_bearish"].shift(1)
    df_pd["prev_bullish"] = df_pd["is_bullish"].shift(1)
    df_pd["order_block_bull"] = (
        (df_pd["prev_bearish"] == 1) & (df_pd["displacement_up"] == 1)
    ).astype(int)
    df_pd["order_block_bear"] = (
        (df_pd["prev_bullish"] == 1) & (df_pd["displacement_down"] == 1)
    ).astype(int)

    df_pd["prev_high_5"] = df_pd["high_5"].shift(1)
    df_pd["prev_low_5"] = df_pd["low_5"].shift(1)
    df_pd["liquidity_grab_high"] = (
        (df_pd["high"] > df_pd["prev_high_5"]) & (df_pd["close"] < df_pd["prev_high_5"])
    ).astype(int)
    df_pd["liquidity_grab_low"] = (
        (df_pd["low"] < df_pd["prev_low_5"]) & (df_pd["close"] > df_pd["prev_low_5"])
    ).astype(int)
    df_pd["bos_up"] = (df_pd["close"] > df_pd["prev_high_5"]).astype(int)
    df_pd["bos_down"] = (df_pd["close"] < df_pd["prev_low_5"]).astype(int)

    # VPA features
    df_pd["up_volume"] = np.where(df_pd["close"] > df_pd["open"], df_pd["volume"], 0)
    df_pd["down_volume"] = np.where(df_pd["close"] < df_pd["open"], df_pd["volume"], 0)
    df_pd["up_volume_5"] = df_pd["up_volume"].rolling(5, min_periods=1).sum()
    df_pd["down_volume_5"] = df_pd["down_volume"].rolling(5, min_periods=1).sum()
    df_pd["pressure_ratio"] = df_pd["up_volume_5"] / (df_pd["down_volume_5"] + 1)

    df_pd["typical_price"] = (df_pd["high"] + df_pd["low"] + df_pd["close"]) / 3
    df_pd["vwap_num"] = (
        (df_pd["typical_price"] * df_pd["volume"]).rolling(20, min_periods=1).sum()
    )
    df_pd["vwap_den"] = df_pd["volume"].rolling(20, min_periods=1).sum()
    df_pd["vwap"] = df_pd["vwap_num"] / (df_pd["vwap_den"] + 1)
    df_pd["distance_from_vwap"] = (df_pd["close"] - df_pd["vwap"]) / (
        df_pd["vwap"] + 1e-8
    )

    df_pd["volume_momentum"] = df_pd["volume"].pct_change(5)
    df_pd["price_change_5"] = df_pd["close"].pct_change(5)
    df_pd["volume_change_5"] = df_pd["volume"].pct_change(5)
    df_pd["pv_divergence"] = df_pd["price_change_5"] - df_pd["volume_change_5"]

    # Filter to target date first, then compute forward-looking labels within the day
    df_pd["date"] = df_pd["timestamp"].dt.date
    df_pd = df_pd[df_pd["date"] == target_date_obj]

    # Labels: Use NEXT bar for entry (prevent leakage), then 5-bar exit from entry
    df_pd["entry_close"] = df_pd["close"].shift(-1)  # Next bar entry
    df_pd["entry_timestamp"] = df_pd["timestamp"].shift(-1)
    df_pd["exit_close"] = df_pd["close"].shift(-6)  # 5 bars after entry
    df_pd["exit_timestamp"] = df_pd["timestamp"].shift(-6)

    # Forward return from entry to exit
    df_pd["forward_return"] = (df_pd["exit_close"] - df_pd["entry_close"]) / df_pd[
        "entry_close"
    ]
    df_pd["label_long"] = (df_pd["forward_return"] > 0.015).astype(int)
    df_pd["label_short"] = (df_pd["forward_return"] < -0.015).astype(int)

    # Drop rows without valid same-day entry and exit
    df_pd = df_pd.dropna(
        subset=["entry_close", "entry_timestamp", "exit_close", "exit_timestamp"]
    )
    df_pd["entry_date"] = df_pd["entry_timestamp"].dt.date
    df_pd["exit_date"] = df_pd["exit_timestamp"].dt.date
    df_pd = df_pd[
        (df_pd["entry_date"] == target_date_obj)
        & (df_pd["exit_date"] == target_date_obj)
    ]
    df_pd = df_pd.drop(columns=["entry_date", "exit_date"])

    # Apply trade filters
    df_pd = df_pd[df_pd["atr"] >= 0.50]  # Min ATR filter

    # Avoid first 15 min and last 30 min
    hour = df_pd["timestamp"].dt.hour
    minute = df_pd["timestamp"].dt.minute
    df_pd = df_pd[
        ~((hour == 9) & (minute < 45))  # Skip 9:30-9:45
        & ~((hour == 15) & (minute >= 30))  # Skip 15:30-16:00
    ]

    return pl.from_pandas(df_pd)


def main():
    logging.info("=" * 80)
    logging.info("BUILDING INTRADAY FEATURES: 2023-01 to 2025-09")
    logging.info("=" * 80)

    output_dir = Path("run/intraday_features_rolling")
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = output_dir / "features_temp.parquet"

    sip = load_sip()
    sip_by_date = sip.group_by("date").agg(pl.col("symbol"))
    dates = sorted(sip_by_date["date"].to_list())

    all_features = []
    processed_dates = set()

    if checkpoint_file.exists():
        logging.info(f"Resuming from checkpoint: {checkpoint_file}")
        checkpoint_df = pl.read_parquet(checkpoint_file)
        all_features.append(checkpoint_df)
        processed_dates = set(checkpoint_df["date"].unique())
        logging.info(
            f"Checkpoint contains {len(checkpoint_df):,} rows across "
            f"{len(processed_dates)} dates"
        )

    logging.info(f"Processing {len(dates)} dates")

    for i, date in enumerate(dates, 1):
        if date in processed_dates:
            if i % 50 == 0:
                logging.info(f"[{i}/{len(dates)}] {date}: already processed, skipping")
            continue

        symbols = sip_by_date.filter(pl.col("date") == date)["symbol"][0]
        logging.info(f"[{i}/{len(dates)}] {date}: {len(symbols)} symbols")

        for symbol in symbols:
            df = load_intraday_bars(symbol, date)
            if df is None or len(df) == 0:
                continue

            try:
                df = engineer_features(df, date)
                if len(df) == 0:
                    continue

                df = df.with_columns(
                    [
                        pl.lit(symbol).alias("symbol"),
                    ]
                )
                all_features.append(df)
            except Exception as e:
                logging.debug(f"Error {symbol} {date}: {e}")

        if i % 10 == 0 and all_features:
            combined = pl.concat(all_features)
            combined.write_parquet(output_dir / "features_temp.parquet")
            logging.info(f"  Saved intermediate: {len(combined):,} bars")

    if not all_features:
        logging.error("No features generated!")
        return

    combined = pl.concat(all_features)
    output_file = output_dir / "features.parquet"
    combined.write_parquet(output_file)

    logging.info("")
    logging.info("=" * 80)
    logging.info("INTRADAY FEATURES COMPLETE")
    logging.info("=" * 80)
    logging.info(f"Total bars: {len(combined):,}")
    logging.info(f"Unique symbols: {combined['symbol'].n_unique()}")
    logging.info(f"Unique dates: {combined['date'].n_unique()}")
    logging.info(f"Saved to: {output_file}")


if __name__ == "__main__":
    main()
