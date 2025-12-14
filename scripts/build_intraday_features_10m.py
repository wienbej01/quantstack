#!/usr/bin/env python3
"""Build intraday features on 10m bars, execute on 1m bars."""

import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

DATA_ROOT = Path("/home/jacobw/gcs-mount/gold/stocks/1m")


def load_sip():
    """Load SIP membership."""
    sip_file = Path("run/sip_membership_rolling/sip_membership.parquet")
    return pl.read_parquet(sip_file)


def load_intraday_bars(symbol, date):
    """Load 1m bars and resample to 10m."""

    if isinstance(date, str):
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    else:
        date_obj = date

    symbol_path = DATA_ROOT / symbol
    if not symbol_path.exists():
        return None, None

    year = date_obj.year
    month = date_obj.strftime("%Y-%m")
    parquet_file = symbol_path / str(year) / f"{month}.parquet"

    if not parquet_file.exists():
        return None, None

    try:
        df = pl.read_parquet(parquet_file)
        if "ts" in df.columns:
            df = df.rename({"ts": "timestamp"})

        # Filter to target date
        df = df.filter(pl.col("timestamp").dt.date() == date_obj)

        if len(df) == 0:
            return None, None

        # Market hours only
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

        if len(df) == 0:
            return None, None

        # Keep 1m bars for execution
        df_1m = df.clone()

        # Resample to 10m bars
        df = df.sort("timestamp")
        df_pd = df.to_pandas()
        df_pd.set_index("timestamp", inplace=True)

        # Resample OHLCV to 10m
        resampled = (
            df_pd.resample("10min")
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
            .dropna()
        )

        resampled = resampled.reset_index()
        return pl.from_pandas(resampled), df_1m
    except Exception:
        return None, None


def engineer_features(df_10m, df_1m, target_date):
    """Engineer features on 10m bars, map to 1m execution."""
    if isinstance(target_date, str):
        target_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        target_date_obj = target_date

    df_pd = df_10m.to_pandas()

    # Base features on 10m bars
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

    # ATR on 10m bars
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

    # Map to 1m bars for execution
    # For each 10m signal bar, find the next 1m bar for entry
    df_1m_pd = df_1m.to_pandas()

    results = []
    for idx, row in df_pd.iterrows():
        signal_time = row["timestamp"]

        # Find first 1m bar after signal
        entry_bars = df_1m_pd[df_1m_pd["timestamp"] > signal_time]
        if len(entry_bars) == 0:
            continue

        entry_bar = entry_bars.iloc[0]
        entry_time = entry_bar["timestamp"]
        entry_price = entry_bar["close"]

        # Find exit bar (5 bars after entry on 1m = 5 minutes)
        exit_bars = df_1m_pd[df_1m_pd["timestamp"] > entry_time]
        if len(exit_bars) < 5:
            continue

        exit_bar = exit_bars.iloc[4]  # 5th bar after entry
        exit_time = exit_bar["timestamp"]
        exit_price = exit_bar["close"]

        # Check same day
        if entry_time.date() != target_date_obj or exit_time.date() != target_date_obj:
            continue

        # Forward return
        forward_return = (exit_price - entry_price) / entry_price

        # Create feature row
        feature_row = row.copy()
        feature_row["entry_timestamp"] = entry_time
        feature_row["entry_close"] = entry_price
        feature_row["exit_timestamp"] = exit_time
        feature_row["exit_close"] = exit_price
        feature_row["forward_return"] = forward_return
        feature_row["label_long"] = int(forward_return > 0.015)
        feature_row["label_short"] = int(forward_return < -0.015)
        feature_row["date"] = target_date_obj

        results.append(feature_row)

    if len(results) == 0:
        return pl.DataFrame()

    return pl.from_pandas(pd.DataFrame(results))


def main():
    logging.info("=" * 80)
    logging.info("BUILDING 10M INTRADAY FEATURES")
    logging.info("=" * 80)

    output_dir = Path("run/intraday_features_10m")
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
            f"Checkpoint contains {len(checkpoint_df):,} rows across {len(processed_dates)} dates"
        )

    for i, date in enumerate(dates, 1):
        if date in processed_dates:
            continue

        date_str = str(date)
        symbols = sip.filter(pl.col("date") == date)["symbol"].to_list()

        logging.info(f"[{i}/{len(dates)}] {date_str}: {len(symbols)} symbols")

        for symbol in symbols:
            try:
                # Load 10m and 1m bars
                df_10m, df_1m = load_intraday_bars(symbol, date)
                if df_10m is None or df_1m is None:
                    continue

                if len(df_10m) == 0 or len(df_1m) == 0:
                    continue

                # Engineer features
                df = engineer_features(df_10m, df_1m, date)
                if len(df) == 0:
                    continue

                df = df.with_columns(pl.lit(symbol).alias("symbol"))
                all_features.append(df)

            except Exception as e:
                logging.warning(f"  {symbol}: {e}")
                continue

        # Checkpoint every 10 dates
        if i % 10 == 0 and len(all_features) > 0:
            combined = pl.concat(all_features)
            combined.write_parquet(checkpoint_file)
            logging.info(f"  Saved intermediate: {len(combined):,} bars")

    # Final save
    if len(all_features) > 0:
        final_df = pl.concat(all_features)
        final_df.write_parquet(output_dir / "features.parquet")
        logging.info(f"Total bars: {len(final_df):,}")
        logging.info(f"Unique symbols: {final_df['symbol'].n_unique()}")
        logging.info(f"Unique dates: {final_df['date'].n_unique()}")
        logging.info(f"Saved to: {output_dir / 'features.parquet'}")

        if checkpoint_file.exists():
            checkpoint_file.unlink()
    else:
        logging.warning("No features generated!")


if __name__ == "__main__":
    main()
