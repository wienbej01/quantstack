#!/usr/bin/env python3
"""Train v4 models with ICT and Volume-Price Analysis features."""

import logging
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def engineer_features_ict(df):
    """Create ICT and Volume-Price Analysis features."""
    df = df.sort_values(["symbol", "ts"]).copy()

    # === EXISTING FEATURES ===
    df["returns"] = df.groupby("symbol")["close"].pct_change()
    df["returns_5"] = df.groupby("symbol")["close"].pct_change(5)
    df["returns_10"] = df.groupby("symbol")["close"].pct_change(10)
    df["returns_20"] = df.groupby("symbol")["close"].pct_change(20)
    df["range_pct"] = (df["high"] - df["low"]) / df["close"]
    df["body_pct"] = abs(df["close"] - df["open"]) / df["close"]
    df["upper_wick"] = (df["high"] - df[["open", "close"]].max(axis=1)) / df["close"]
    df["lower_wick"] = (df[["open", "close"]].min(axis=1) - df["low"]) / df["close"]
    df["volume_ma5"] = df.groupby("symbol")["volume"].transform(
        lambda x: x.rolling(5, min_periods=1).mean()
    )
    df["volume_ma20"] = df.groupby("symbol")["volume"].transform(
        lambda x: x.rolling(20, min_periods=1).mean()
    )
    df["volume_ratio"] = df["volume"] / df["volume_ma5"]
    df["volume_ratio_20"] = df["volume"] / df["volume_ma20"]
    df["volatility_5"] = df.groupby("symbol")["returns"].transform(
        lambda x: x.rolling(5, min_periods=1).std()
    )
    df["volatility_20"] = df.groupby("symbol")["returns"].transform(
        lambda x: x.rolling(20, min_periods=1).std()
    )
    df["time_since_open"] = (df["ts"].dt.hour - 9) * 60 + (df["ts"].dt.minute - 30)
    df["time_to_close"] = (16 - df["ts"].dt.hour) * 60 - df["ts"].dt.minute
    df["high_5"] = df.groupby("symbol")["high"].transform(
        lambda x: x.rolling(5, min_periods=1).max()
    )
    df["low_5"] = df.groupby("symbol")["low"].transform(
        lambda x: x.rolling(5, min_periods=1).min()
    )
    df["price_position"] = (df["close"] - df["low_5"]) / (
        df["high_5"] - df["low_5"] + 1e-8
    )

    # === ICT FEATURES ===

    # Fair Value Gap (FVG) - price imbalance
    df["prev_high"] = df.groupby("symbol")["high"].shift(1)
    df["prev_low"] = df.groupby("symbol")["low"].shift(1)
    df["next_low"] = df.groupby("symbol")["low"].shift(-1)
    df["next_high"] = df.groupby("symbol")["high"].shift(-1)
    df["fvg_up"] = (df["prev_high"] < df["next_low"]).astype(int)  # Bullish FVG
    df["fvg_down"] = (df["prev_low"] > df["next_high"]).astype(int)  # Bearish FVG
    df["fvg_size"] = np.where(
        df["fvg_up"],
        df["next_low"] - df["prev_high"],
        np.where(df["fvg_down"], df["prev_low"] - df["next_high"], 0),
    )
    df["fvg_size_pct"] = df["fvg_size"] / df["close"]

    # Displacement - strong directional move
    df["displacement"] = abs(df["returns"]) > (df["volatility_5"] * 2)
    df["displacement_up"] = ((df["returns"] > 0) & df["displacement"]).astype(int)
    df["displacement_down"] = ((df["returns"] < 0) & df["displacement"]).astype(int)

    # Order Block - last opposite candle before displacement
    df["is_bullish_candle"] = (df["close"] > df["open"]).astype(int)
    df["is_bearish_candle"] = (df["close"] < df["open"]).astype(int)
    df["order_block_bull"] = (
        df["is_bearish_candle"].astype(bool)
        & df.groupby("symbol")["displacement_up"].shift(-1).fillna(0).astype(bool)
    ).astype(int)
    df["order_block_bear"] = (
        df["is_bullish_candle"].astype(bool)
        & df.groupby("symbol")["displacement_down"].shift(-1).fillna(0).astype(bool)
    ).astype(int)

    # Liquidity Grab - stop hunt above/below recent highs/lows
    df["high_20"] = df.groupby("symbol")["high"].transform(
        lambda x: x.rolling(20, min_periods=1).max()
    )
    df["low_20"] = df.groupby("symbol")["low"].transform(
        lambda x: x.rolling(20, min_periods=1).min()
    )
    df["liquidity_grab_high"] = (
        (df["high"] > df["high_20"].shift(1)) & (df["close"] < df["open"])
    ).astype(int)
    df["liquidity_grab_low"] = (
        (df["low"] < df["low_20"].shift(1)) & (df["close"] > df["open"])
    ).astype(int)

    # Break of Structure (BOS) - new high/low
    df["bos_up"] = (df["high"] > df["high_20"].shift(1)).astype(int)
    df["bos_down"] = (df["low"] < df["low_20"].shift(1)).astype(int)

    # === VOLUME-PRICE ANALYSIS ===

    # Buying/Selling Pressure
    df["buying_pressure"] = (
        (df["close"] - df["low"]) / (df["high"] - df["low"] + 1e-8)
    ) * df["volume"]
    df["selling_pressure"] = (
        (df["high"] - df["close"]) / (df["high"] - df["low"] + 1e-8)
    ) * df["volume"]
    df["pressure_ratio"] = df["buying_pressure"] / (df["selling_pressure"] + 1e-8)

    # Volume-Weighted Price
    df["vwap_5"] = (
        df.groupby("symbol")
        .apply(
            lambda x: (x["close"] * x["volume"]).rolling(5, min_periods=1).sum()
            / x["volume"].rolling(5, min_periods=1).sum()
        )
        .reset_index(level=0, drop=True)
    )
    df["distance_from_vwap"] = (df["close"] - df["vwap_5"]) / df["close"]

    # Volume Momentum
    df["volume_change"] = df.groupby("symbol")["volume"].pct_change()
    df["volume_momentum"] = df.groupby("symbol")["volume_change"].transform(
        lambda x: x.rolling(5, min_periods=1).mean()
    )

    # Price-Volume Divergence
    df["price_up"] = (df["returns"] > 0).astype(int)
    df["volume_up"] = (df["volume_change"] > 0).astype(int)
    df["pv_divergence"] = (df["price_up"] != df["volume_up"]).astype(int)

    # Drop intermediate columns
    drop_cols = [
        "prev_high",
        "prev_low",
        "next_low",
        "next_high",
        "is_bullish_candle",
        "is_bearish_candle",
        "displacement",
        "high_20",
        "low_20",
        "buying_pressure",
        "selling_pressure",
        "volume_change",
        "price_up",
        "volume_up",
    ]
    df = df.drop(columns=[c for c in drop_cols if c in df.columns])

    return df.fillna(0)


def main():
    LOGGER.info("=" * 80)
    LOGGER.info("Training v4 Models - ICT + VOLUME-PRICE FEATURES")
    LOGGER.info("=" * 80)

    data_dir = Path("artefacts/extensions/intraday_ml/v4_6months")
    train_df = pd.read_parquet(data_dir / "train.parquet")
    val_df = pd.read_parquet(data_dir / "val.parquet")

    LOGGER.info(f"Train: {len(train_df):,} rows")
    LOGGER.info(f"Val: {len(val_df):,} rows")

    LOGGER.info("Engineering ICT + Volume-Price features...")
    train_df = engineer_features_ict(train_df)
    val_df = engineer_features_ict(val_df)

    feature_cols = [
        "returns",
        "returns_5",
        "returns_10",
        "returns_20",
        "range_pct",
        "body_pct",
        "upper_wick",
        "lower_wick",
        "volume_ratio",
        "volume_ratio_20",
        "volatility_5",
        "volatility_20",
        "time_since_open",
        "time_to_close",
        "price_position",
        # ICT features
        "fvg_up",
        "fvg_down",
        "fvg_size_pct",
        "displacement_up",
        "displacement_down",
        "order_block_bull",
        "order_block_bear",
        "liquidity_grab_high",
        "liquidity_grab_low",
        "bos_up",
        "bos_down",
        # Volume-Price features
        "pressure_ratio",
        "distance_from_vwap",
        "volume_momentum",
        "pv_divergence",
    ]

    LOGGER.info(f"Features: {len(feature_cols)} (16 base + 10 ICT + 4 volume-price)")

    X_train = train_df[feature_cols]
    X_val = val_df[feature_cols]

    # Train LONG
    LOGGER.info("")
    LOGGER.info("Training LONG model...")
    y_train_long = (train_df["label"] == 1).astype(int)
    y_val_long = (val_df["label"] == 1).astype(int)

    model_long = lgb.LGBMClassifier(
        n_estimators=300,
        max_depth=7,
        learning_rate=0.03,
        num_leaves=64,
        min_child_samples=100,
        random_state=42,
        verbose=-1,
    )
    model_long.fit(X_train, y_train_long)

    train_auc_long = roc_auc_score(
        y_train_long, model_long.predict_proba(X_train)[:, 1]
    )
    val_auc_long = roc_auc_score(y_val_long, model_long.predict_proba(X_val)[:, 1])
    LOGGER.info(f"LONG - Train: {train_auc_long:.4f}, Val: {val_auc_long:.4f}")

    # Train SHORT
    LOGGER.info("")
    LOGGER.info("Training SHORT model...")
    y_train_short = (train_df["label"] == -1).astype(int)
    y_val_short = (val_df["label"] == -1).astype(int)

    model_short = lgb.LGBMClassifier(
        n_estimators=300,
        max_depth=7,
        learning_rate=0.03,
        num_leaves=64,
        min_child_samples=100,
        random_state=42,
        verbose=-1,
    )
    model_short.fit(X_train, y_train_short)

    train_auc_short = roc_auc_score(
        y_train_short, model_short.predict_proba(X_train)[:, 1]
    )
    val_auc_short = roc_auc_score(y_val_short, model_short.predict_proba(X_val)[:, 1])
    LOGGER.info(f"SHORT - Train: {train_auc_short:.4f}, Val: {val_auc_short:.4f}")

    # Save
    output_dir = Path("models")
    model_long.booster_.save_model(str(output_dir / "v4_6months_ict_long.txt"))
    model_short.booster_.save_model(str(output_dir / "v4_6months_ict_short.txt"))

    LOGGER.info("")
    LOGGER.info("=" * 80)
    LOGGER.info("Training Complete!")
    LOGGER.info(f"LONG: Train {train_auc_long:.4f}, Val {val_auc_long:.4f}")
    LOGGER.info(f"SHORT: Train {train_auc_short:.4f}, Val {val_auc_short:.4f}")
    LOGGER.info("Models saved to models/v4_6months_ict_*.txt")


if __name__ == "__main__":
    main()
