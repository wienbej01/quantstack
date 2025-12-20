#!/usr/bin/env python3
"""Reprocess raw L2 data to add mid/spread features."""

import glob
import pandas as pd
import numpy as np
from pathlib import Path

RAW_DIR = Path("/home/jacobw/quantstack/data/l2_maximum/raw")
OUT_DIR = Path("/home/jacobw/quantstack/data/l2_maximum/features_v2")


def compute_features(df: pd.DataFrame, levels: int = 10) -> pd.DataFrame:
    """Compute L2 features from raw snapshot data."""
    df = df.sort_values("ts_epoch").reset_index(drop=True)

    # Mid and spread from L2 top-of-book
    df["mid"] = (df["bid_px_1"] + df["ask_px_1"]) / 2
    df["spread"] = df["ask_px_1"] - df["bid_px_1"]

    # Microprice
    total_sz = df["bid_sz_1"] + df["ask_sz_1"]
    df["microprice"] = np.where(
        total_sz > 0,
        (df["bid_px_1"] * df["ask_sz_1"] + df["ask_px_1"] * df["bid_sz_1"]) / total_sz,
        df["mid"],
    )
    df["micro_off"] = df["microprice"] - df["mid"]

    # Depth aggregation
    bid_cols = [f"bid_sz_{i}" for i in range(1, levels + 1)]
    ask_cols = [f"ask_sz_{i}" for i in range(1, levels + 1)]
    df["depth_bid_k"] = df[bid_cols].fillna(0).sum(axis=1)
    df["depth_ask_k"] = df[ask_cols].fillna(0).sum(axis=1)
    total_depth = df["depth_bid_k"] + df["depth_ask_k"]
    df["depth_imb_k"] = np.where(
        total_depth > 0, (df["depth_bid_k"] - df["depth_ask_k"]) / total_depth, 0
    )
    df["pressure_k"] = df["depth_bid_k"] - df["depth_ask_k"]

    # OBI at multiple levels
    for level in [1, 2, 3, 5, 10]:
        if level <= levels:
            bid_sz = df[f"bid_sz_{level}"].fillna(0)
            ask_sz = df[f"ask_sz_{level}"].fillna(0)
            total = bid_sz + ask_sz
            df[f"obi_{level}"] = np.where(total > 0, (bid_sz - ask_sz) / total, 0)

    # Time deltas (at 2Hz: 5s=10 rows, 15s=30, 30s=60, 60s=120)
    for window_sec, lag in [(5, 10), (15, 30), (30, 60), (60, 120)]:
        for field in ["mid", "spread", "obi_1", "micro_off"]:
            if field in df.columns:
                df[f"d_{field}_{window_sec}s"] = df[field] - df[field].shift(lag)
                df[f"d_{field}_{window_sec}s"] = df[f"d_{field}_{window_sec}s"].fillna(0)

    # Select output columns
    out_cols = [
        "ts_utc", "ts_epoch", "date_et", "symbol", "exchange", "smart_depth", "has_depth",
        "mid", "spread", "microprice", "micro_off",
        "depth_bid_k", "depth_ask_k", "depth_imb_k", "pressure_k",
        "obi_1", "obi_2", "obi_3", "obi_5", "obi_10",
        "d_mid_5s", "d_spread_5s", "d_obi_1_5s", "d_micro_off_5s",
        "d_mid_15s", "d_spread_15s", "d_obi_1_15s", "d_micro_off_15s",
        "d_mid_30s", "d_spread_30s", "d_obi_1_30s", "d_micro_off_30s",
        "d_mid_60s", "d_spread_60s", "d_obi_1_60s", "d_micro_off_60s",
    ]
    return df[[c for c in out_cols if c in df.columns]]


def main():
    print("Reprocessing raw L2 data with mid/spread features...")

    for date_dir in sorted(RAW_DIR.glob("date=*")):
        date_str = date_dir.name
        print(f"\nProcessing {date_str}...")

        for symbol_dir in sorted(date_dir.glob("symbol=*")):
            symbol = symbol_dir.name.split("=")[1]
            raw_files = list(symbol_dir.glob("*.parquet"))

            if not raw_files:
                continue

            # Load all raw data for symbol
            df = pd.concat([pd.read_parquet(f) for f in raw_files], ignore_index=True)
            df["symbol"] = symbol

            # Compute features
            features_df = compute_features(df)

            # Save
            out_path = OUT_DIR / date_str / f"symbol={symbol}"
            out_path.mkdir(parents=True, exist_ok=True)
            out_file = out_path / "features.parquet"
            features_df.to_parquet(out_file, index=False)

            print(f"  {symbol}: {len(features_df):,} records → {out_file}")

    print("\nDone! Features saved to:", OUT_DIR)


if __name__ == "__main__":
    main()
