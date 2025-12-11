#!/usr/bin/env python3
"""Add 30 ICT features to existing intraday feature store."""

import logging
from pathlib import Path

import numpy as np
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def add_ict_features(df):
    """Add ICT and VPA features to intraday data."""
    df = df.sort(["symbol", "timestamp"])

    # Convert to pandas for complex calculations
    df_pd = df.to_pandas()

    # Wicks
    df_pd["candle_top"] = df_pd[["open", "close"]].max(axis=1)
    df_pd["candle_bottom"] = df_pd[["open", "close"]].min(axis=1)
    df_pd["upper_wick"] = (df_pd["high"] - df_pd["candle_top"]) / df_pd["close"]
    df_pd["lower_wick"] = (df_pd["candle_bottom"] - df_pd["low"]) / df_pd["close"]

    # ICT: Fair Value Gap
    df_pd["prev_high"] = df_pd.groupby("symbol")["high"].shift(1)
    df_pd["prev_low"] = df_pd.groupby("symbol")["low"].shift(1)
    df_pd["next_low"] = df_pd.groupby("symbol")["low"].shift(-1)
    df_pd["next_high"] = df_pd.groupby("symbol")["high"].shift(-1)

    df_pd["fvg_up"] = (df_pd["prev_high"] < df_pd["next_low"]).astype(int)
    df_pd["fvg_down"] = (df_pd["prev_low"] > df_pd["next_high"]).astype(int)
    df_pd["fvg_size"] = np.where(
        df_pd["fvg_up"],
        df_pd["next_low"] - df_pd["prev_high"],
        np.where(df_pd["fvg_down"], df_pd["prev_low"] - df_pd["next_high"], 0),
    )
    df_pd["fvg_size_pct"] = df_pd["fvg_size"] / df_pd["close"]

    # ICT: Displacement
    df_pd["displacement_up"] = (
        (df_pd["returns"] > 0) & (df_pd["returns"].abs() > df_pd["volatility_5"] * 2)
    ).astype(int)
    df_pd["displacement_down"] = (
        (df_pd["returns"] < 0) & (df_pd["returns"].abs() > df_pd["volatility_5"] * 2)
    ).astype(int)

    # ICT: Order Blocks
    df_pd["is_bullish"] = (df_pd["close"] > df_pd["open"]).astype(int)
    df_pd["is_bearish"] = (df_pd["close"] < df_pd["open"]).astype(int)
    df_pd["prev_bearish"] = df_pd.groupby("symbol")["is_bearish"].shift(1)
    df_pd["prev_bullish"] = df_pd.groupby("symbol")["is_bullish"].shift(1)

    df_pd["order_block_bull"] = (
        (df_pd["prev_bearish"] == 1) & (df_pd["displacement_up"] == 1)
    ).astype(int)
    df_pd["order_block_bear"] = (
        (df_pd["prev_bullish"] == 1) & (df_pd["displacement_down"] == 1)
    ).astype(int)

    # ICT: Liquidity Grabs
    df_pd["high_5"] = df_pd.groupby("symbol")["high"].transform(
        lambda x: x.rolling(5, min_periods=1).max()
    )
    df_pd["low_5"] = df_pd.groupby("symbol")["low"].transform(
        lambda x: x.rolling(5, min_periods=1).min()
    )
    df_pd["prev_high_5"] = df_pd.groupby("symbol")["high_5"].shift(1)
    df_pd["prev_low_5"] = df_pd.groupby("symbol")["low_5"].shift(1)

    df_pd["liquidity_grab_high"] = (
        (df_pd["high"] > df_pd["prev_high_5"]) & (df_pd["close"] < df_pd["prev_high_5"])
    ).astype(int)
    df_pd["liquidity_grab_low"] = (
        (df_pd["low"] < df_pd["prev_low_5"]) & (df_pd["close"] > df_pd["prev_low_5"])
    ).astype(int)

    # ICT: Break of Structure
    df_pd["bos_up"] = (df_pd["close"] > df_pd["prev_high_5"]).astype(int)
    df_pd["bos_down"] = (df_pd["close"] < df_pd["prev_low_5"]).astype(int)

    # VPA: Pressure Ratio
    df_pd["up_volume"] = np.where(df_pd["close"] > df_pd["open"], df_pd["volume"], 0)
    df_pd["down_volume"] = np.where(df_pd["close"] < df_pd["open"], df_pd["volume"], 0)
    df_pd["up_volume_5"] = df_pd.groupby("symbol")["up_volume"].transform(
        lambda x: x.rolling(5, min_periods=1).sum()
    )
    df_pd["down_volume_5"] = df_pd.groupby("symbol")["down_volume"].transform(
        lambda x: x.rolling(5, min_periods=1).sum()
    )
    df_pd["pressure_ratio"] = df_pd["up_volume_5"] / (df_pd["down_volume_5"] + 1)

    # VPA: VWAP
    df_pd["typical_price"] = (df_pd["high"] + df_pd["low"] + df_pd["close"]) / 3
    df_pd["vwap_num"] = df_pd.groupby("symbol")["typical_price"].transform(
        lambda x: (x * df_pd.loc[x.index, "volume"]).rolling(20, min_periods=1).sum()
    )
    df_pd["vwap_den"] = df_pd.groupby("symbol")["volume"].transform(
        lambda x: x.rolling(20, min_periods=1).sum()
    )
    df_pd["vwap"] = df_pd["vwap_num"] / (df_pd["vwap_den"] + 1)
    df_pd["distance_from_vwap"] = (df_pd["close"] - df_pd["vwap"]) / df_pd["vwap"]

    # VPA: Volume Momentum
    df_pd["volume_momentum"] = df_pd.groupby("symbol")["volume"].transform(
        lambda x: x.pct_change(5)
    )

    # VPA: Price-Volume Divergence
    df_pd["price_change_5"] = df_pd.groupby("symbol")["close"].transform(
        lambda x: x.pct_change(5)
    )
    df_pd["volume_change_5"] = df_pd.groupby("symbol")["volume"].transform(
        lambda x: x.pct_change(5)
    )
    df_pd["pv_divergence"] = df_pd["price_change_5"] - df_pd["volume_change_5"]

    return pl.from_pandas(df_pd)


def main():
    logging.info("=" * 80)
    logging.info("ADDING 30 ICT FEATURES TO INTRADAY DATA")
    logging.info("=" * 80)

    # Load existing features
    features_path = Path("run/intraday_features_sip_6months/features.parquet")
    logging.info(f"Loading: {features_path}")
    df = pl.read_parquet(features_path)
    logging.info(f"Loaded: {len(df):,} bars")

    # Add ICT features
    logging.info("Adding ICT features...")
    df_enhanced = add_ict_features(df)

    # Save
    output_path = Path("run/intraday_features_sip_6months/features_30ict.parquet")
    df_enhanced.write_parquet(output_path)
    logging.info(f"Saved: {output_path}")
    logging.info(f"Columns: {len(df_enhanced.columns)}")

    logging.info("")
    logging.info("=" * 80)
    logging.info("COMPLETE")
    logging.info("=" * 80)


if __name__ == "__main__":
    main()
