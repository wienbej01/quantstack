#!/usr/bin/env python3
"""
Debug script for analyzing the vectorized labeling process.
"""

import sys
from pathlib import Path

import pandas as pd
import yaml

# --- Path Setup ---
sys.path.insert(0, str(Path(__file__).parent / "qx-data" / "src"))

from extensions.intraday_ml.labeling_vectorized import VectorizedIntradayMLLabeler
from qx_data.gold_loader import load_bars


def debug_labeling():
    print("--- Starting Labeling Debugger ---")

    # --- Config ---
    SYMBOLS = ["BAC"]
    DATE = "2023-01-03"  # A single day from the training set
    targets_config = yaml.safe_load(open("configs/extensions/intraday_ml/targets.yaml"))

    # --- Load Data ---
    # Load a bit more than one day to have future data for labels
    print(f"Loading data for {DATE}...")
    df = load_bars(
        root="/home/jacobw/gcs-mount",
        family="bars_1m",
        symbols=SYMBOLS,
        dates=[DATE, "2023-01-04"],
    )
    if df.empty:
        print("No data loaded. Exiting.")
        return

    # --- Run Labeling ---
    print("Running vectorized labeler...")
    labeler = VectorizedIntradayMLLabeler(targets_config)

    # --- Modified compute_labels to return intermediate values for debugging ---
    df_out = df.copy()
    df_out["label"] = 0

    high_low = df_out["high"] - df_out["low"]
    high_prev_close = (df_out["high"] - df_out.groupby("symbol")["close"].shift(1)).abs()
    low_prev_close = (df_out["low"] - df_out.groupby("symbol")["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
    atr = (
        tr.groupby(df_out["symbol"])
        .rolling(labeler.atr_window, min_periods=1)
        .mean()
        .reset_index(level=0, drop=True)
    )

    df_out["atr"] = atr
    df_out["threshold"] = df_out["atr"] * labeler.atr_multiplier

    future_highs_grouped = (
        df_out.groupby("symbol")["high"].rolling(window=labeler.horizon, min_periods=1).max()
    )
    future_highs = (
        future_highs_grouped.groupby(level="symbol")
        .shift(-labeler.horizon)
        .reset_index(level=0, drop=True)
    )
    future_lows_grouped = (
        df_out.groupby("symbol")["low"].rolling(window=labeler.horizon, min_periods=1).min()
    )
    future_lows = (
        future_lows_grouped.groupby(level="symbol")
        .shift(-labeler.horizon)
        .reset_index(level=0, drop=True)
    )
    df_out["future_high"] = future_highs
    df_out["future_low"] = future_lows

    upper_barrier = df_out["close"] + df_out["threshold"]
    lower_barrier = df_out["close"] - df_out["threshold"]
    df_out["upper_barrier"] = upper_barrier
    df_out["lower_barrier"] = lower_barrier

    hit_up = future_highs >= upper_barrier
    hit_down = future_lows <= lower_barrier

    df_out.loc[hit_up, "label"] = 1
    df_out.loc[hit_down, "label"] = -1
    df_out.loc[hit_up & hit_down, "label"] = 1

    # --- Analysis ---
    print("\n--- Label Distribution ---")
    print(df_out["label"].value_counts())

    print("\n--- Debugging Sample (where label is 0) ---")
    debug_sample = df_out[df_out["label"] == 0].sample(5, random_state=42)
    debug_cols = [
        "ts",
        "close",
        "atr",
        "threshold",
        "upper_barrier",
        "lower_barrier",
        "future_high",
        "future_low",
    ]
    print(debug_sample[debug_cols])

    print("\n--- Analysis of a Sample Row ---")
    sample_row = debug_sample.iloc[0]
    print(f"Timestamp: {sample_row['ts']}")
    print(f"Close Price: {sample_row['close']:.4f}")
    print(f"ATR: {sample_row['atr']:.4f}")
    print(f"ATR Multiplier: {labeler.atr_multiplier}")
    print(f"Calculated Threshold: {sample_row['threshold']:.4f}")
    print(f"Upper Barrier (Price to Hit for BUY): {sample_row['upper_barrier']:.4f}")
    print(f"Lower Barrier (Price to Hit for SELL): {sample_row['lower_barrier']:.4f}")
    print(f"Actual Future High in next {labeler.horizon} mins: {sample_row['future_high']:.4f}")
    print(f"Actual Future Low in next {labeler.horizon} mins: {sample_row['future_low']:.4f}")

    if sample_row["future_high"] < sample_row["upper_barrier"]:
        print("==> Conclusion: Future high did NOT cross the upper barrier.")
    if sample_row["future_low"] > sample_row["lower_barrier"]:
        print("==> Conclusion: Future low did NOT cross the lower barrier.")


if __name__ == "__main__":
    debug_labeling()
