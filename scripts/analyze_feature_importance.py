#!/usr/bin/env python3
"""Analyze feature importance for v4 ICT models."""

import logging
import sys
from pathlib import Path

import lightgbm as lgb
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def analyze_model(model_path: Path, direction: str) -> pd.DataFrame:
    """Load model and extract feature importance."""
    model = lgb.Booster(model_file=str(model_path))

    # Get feature importance (split-based)
    importance = model.feature_importance(importance_type="split")
    feature_names = model.feature_name()

    df = pd.DataFrame(
        {"feature": feature_names, "importance": importance, "direction": direction}
    )

    # Calculate percentage
    df["pct"] = 100 * df["importance"] / df["importance"].sum()

    return df.sort_values("importance", ascending=False)


def main():
    models_dir = Path("models")

    long_model = models_dir / "v4_6months_ict_long.txt"
    short_model = models_dir / "v4_6months_ict_short.txt"

    if not long_model.exists() or not short_model.exists():
        logging.error("Models not found")
        sys.exit(1)

    logging.info("Analyzing LONG model...")
    long_df = analyze_model(long_model, "LONG")

    logging.info("Analyzing SHORT model...")
    short_df = analyze_model(short_model, "SHORT")

    # Print top 15 features for each
    print("\n" + "=" * 80)
    print("LONG MODEL - Top 15 Features")
    print("=" * 80)
    for idx, row in long_df.head(15).iterrows():
        print(f"{row['feature']:30s} {row['importance']:8.0f} ({row['pct']:5.1f}%)")

    print("\n" + "=" * 80)
    print("SHORT MODEL - Top 15 Features")
    print("=" * 80)
    for idx, row in short_df.head(15).iterrows():
        print(f"{row['feature']:30s} {row['importance']:8.0f} ({row['pct']:5.1f}%)")

    # Compare top features
    print("\n" + "=" * 80)
    print("Feature Comparison (Top 10 by Combined Importance)")
    print("=" * 80)

    # Merge and sum importance
    combined = pd.concat([long_df, short_df])
    combined_agg = (
        combined.groupby("feature")["importance"].sum().sort_values(ascending=False)
    )

    print(f"{'Feature':30s} {'LONG Rank':>10s} {'SHORT Rank':>10s} {'Combined':>10s}")
    print("-" * 80)

    for feature in combined_agg.head(10).index:
        long_rank = long_df[long_df["feature"] == feature].index[0] + 1
        short_rank = short_df[short_df["feature"] == feature].index[0] + 1
        combined_imp = combined_agg[feature]
        print(f"{feature:30s} {long_rank:10d} {short_rank:10d} {combined_imp:10.0f}")

    # Save full results
    output_dir = Path("run")
    output_dir.mkdir(exist_ok=True)

    long_df.to_csv(output_dir / "feature_importance_long.csv", index=False)
    short_df.to_csv(output_dir / "feature_importance_short.csv", index=False)

    logging.info(f"Full results saved to {output_dir}/feature_importance_*.csv")


if __name__ == "__main__":
    main()
