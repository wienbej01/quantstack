#!/usr/bin/env python3
"""Generate predictions using v4 simple models."""

import logging
from pathlib import Path

import lightgbm as lgb
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def main():
    LOGGER.info("=" * 80)
    LOGGER.info("Generating v4 Predictions")
    LOGGER.info("=" * 80)

    # Load models
    model_long = lgb.Booster(model_file="models/v4_sip_smb_simple_long.txt")
    model_short = lgb.Booster(model_file="models/v4_sip_smb_simple_short.txt")
    LOGGER.info("Models loaded")

    # Load data
    df = pd.read_parquet("artefacts/extensions/intraday_ml/v4_sip_smb_simple/training_data.parquet")
    LOGGER.info(f"Loaded {len(df):,} rows")

    # Engineer features
    df = df.sort_values(["symbol", "ts"]).copy()
    df["returns"] = df.groupby("symbol")["close"].pct_change()
    df["range_pct"] = (df["high"] - df["low"]) / df["close"]
    df["volume_ma5"] = df.groupby("symbol")["volume"].transform(
        lambda x: x.rolling(5, min_periods=1).mean()
    )
    df["volume_ratio"] = df["volume"] / df["volume_ma5"]
    df["returns_5"] = df.groupby("symbol")["close"].pct_change(5)
    df["returns_10"] = df.groupby("symbol")["close"].pct_change(10)
    df = df.fillna(0)

    feature_cols = ["returns", "range_pct", "volume_ratio", "returns_5", "returns_10"]
    X = df[feature_cols]

    # Predict
    LOGGER.info("Generating predictions...")
    prob_long = model_long.predict(X)
    prob_short = model_short.predict(X)

    df["prob_long"] = prob_long
    df["prob_short"] = prob_short

    # Apply threshold
    threshold = 0.50  # Lower threshold for small dataset
    df["prediction"] = 0  # Default: neutral
    df.loc[df["prob_long"] >= threshold, "prediction"] = 1  # LONG
    df.loc[df["prob_short"] >= threshold, "prediction"] = -1  # SHORT

    # Stats
    pred_counts = df["prediction"].value_counts().sort_index()
    LOGGER.info("=" * 80)
    LOGGER.info(f"Prediction Distribution (threshold={threshold}):")
    for pred, count in pred_counts.items():
        pred_name = {-1: "SHORT", 0: "NEUTRAL", 1: "LONG"}[pred]
        LOGGER.info(f"  {pred_name:8s} ({pred:2d}): {count:,} ({count/len(df)*100:.1f}%)")

    # Save
    output_path = Path("run/predictions_v4_simple.parquet")
    df[["symbol", "ts", "open", "high", "low", "close", "volume", "prob_long", "prob_short", "prediction"]].to_parquet(
        output_path, index=False
    )

    LOGGER.info("=" * 80)
    LOGGER.info(f"Saved to: {output_path}")
    LOGGER.info("SUCCESS!")


if __name__ == "__main__":
    main()
