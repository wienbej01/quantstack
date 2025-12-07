#!/usr/bin/env python3
"""Analyze predictive power of all features and propose optimal feature set."""

import logging
import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def calculate_ic(feature_values, labels):
    """Calculate Information Coefficient (Spearman correlation)."""
    mask = ~(np.isnan(feature_values) | np.isnan(labels))
    if mask.sum() < 10:
        return 0.0
    return spearmanr(feature_values[mask], labels[mask])[0]


def calculate_feature_metrics(df, feature_cols):
    """Calculate predictive power metrics for each feature."""
    results = []

    # Convert labels to numeric for correlation
    label_long = (df["label"] == 1).astype(int)
    label_short = (df["label"] == -1).astype(int)

    for feat in feature_cols:
        values = df[feat].values

        # Information Coefficient
        ic_long = calculate_ic(values, label_long.values)
        ic_short = calculate_ic(values, label_short.values)
        ic_combined = (abs(ic_long) + abs(ic_short)) / 2

        # Basic statistics
        mean_val = np.nanmean(values)
        std_val = np.nanstd(values)
        null_pct = np.isnan(values).sum() / len(values) * 100

        # Correlation with other features (will calculate later)
        results.append(
            {
                "feature": feat,
                "ic_long": ic_long,
                "ic_short": ic_short,
                "ic_combined": ic_combined,
                "mean": mean_val,
                "std": std_val,
                "null_pct": null_pct,
            }
        )

    return pd.DataFrame(results)


def calculate_feature_correlations(df, feature_cols):
    """Calculate pairwise feature correlations."""
    corr_matrix = df[feature_cols].corr(method="spearman").abs()
    return corr_matrix


def select_optimal_features(
    feature_metrics, corr_matrix, min_ic=0.01, max_corr=0.8, top_n=50
):
    """Select optimal feature set based on IC and correlation."""

    # Sort by combined IC
    sorted_features = feature_metrics.sort_values("ic_combined", ascending=False)

    selected = []
    for _, row in sorted_features.iterrows():
        feat = row["feature"]

        # Skip if IC too low
        if row["ic_combined"] < min_ic:
            continue

        # Check correlation with already selected features
        if len(selected) > 0:
            max_corr_with_selected = corr_matrix.loc[feat, selected].max()
            if max_corr_with_selected > max_corr:
                continue

        selected.append(feat)

        if len(selected) >= top_n:
            break

    return selected


def main():
    logging.info("Loading models and data...")

    # Load both models
    models_dir = Path("models")

    # ICT model (30 features)
    model_ict_long = lgb.Booster(model_file=str(models_dir / "v4_6months_ict_long.txt"))
    model_ict_short = lgb.Booster(
        model_file=str(models_dir / "v4_6months_ict_short.txt")
    )

    # Comprehensive model (209 features)
    model_comp_long = lgb.Booster(
        model_file=str(models_dir / "v4_6months_comprehensive_long.txt")
    )
    model_comp_short = lgb.Booster(
        model_file=str(models_dir / "v4_6months_comprehensive_short.txt")
    )

    # Get feature importance from both models
    ict_features = model_ict_long.feature_name()
    comp_features = model_comp_long.feature_name()

    ict_importance_long = dict(
        zip(ict_features, model_ict_long.feature_importance(importance_type="gain"), strict=False)
    )
    ict_importance_short = dict(
        zip(ict_features, model_ict_short.feature_importance(importance_type="gain"), strict=False)
    )

    comp_importance_long = dict(
        zip(comp_features, model_comp_long.feature_importance(importance_type="gain"), strict=False)
    )
    comp_importance_short = dict(
        zip(comp_features, model_comp_short.feature_importance(importance_type="gain"), strict=False)
    )

    # Load validation data for IC calculation
    logging.info("Loading validation data...")
    data_dir = Path("artefacts/extensions/intraday_ml/v4_6months")
    val_df = pd.read_parquet(data_dir / "val.parquet")

    # Engineer features for comprehensive model
    logging.info("Engineering comprehensive features...")
    from train_v4_6months_comprehensive_features import engineer_comprehensive_features

    val_comp = engineer_comprehensive_features(val_df.copy())
    val_comp = val_comp.dropna()

    # Engineer features for ICT model
    logging.info("Engineering ICT features...")
    from train_v4_6months_ict_features import engineer_features_ict

    val_ict = engineer_features_ict(val_df.copy())
    val_ict = val_ict.dropna()

    # Calculate metrics for comprehensive features
    logging.info("Calculating predictive power for 209 features...")
    comp_metrics = calculate_feature_metrics(val_comp, comp_features)

    logging.info("Calculating feature correlations...")
    comp_corr = calculate_feature_correlations(val_comp, comp_features)

    # Add model importance to metrics
    comp_metrics["importance_long"] = (
        comp_metrics["feature"].map(comp_importance_long).fillna(0)
    )
    comp_metrics["importance_short"] = (
        comp_metrics["feature"].map(comp_importance_short).fillna(0)
    )
    comp_metrics["importance_combined"] = (
        comp_metrics["importance_long"] + comp_metrics["importance_short"]
    )

    # Calculate metrics for ICT features
    logging.info("Calculating predictive power for 30 features...")
    ict_metrics = calculate_feature_metrics(val_ict, ict_features)
    ict_metrics["importance_long"] = (
        ict_metrics["feature"].map(ict_importance_long).fillna(0)
    )
    ict_metrics["importance_short"] = (
        ict_metrics["feature"].map(ict_importance_short).fillna(0)
    )
    ict_metrics["importance_combined"] = (
        ict_metrics["importance_long"] + ict_metrics["importance_short"]
    )

    # Select optimal features
    logging.info("Selecting optimal feature set...")
    optimal_features = select_optimal_features(
        comp_metrics, comp_corr, min_ic=0.01, max_corr=0.8, top_n=50
    )

    # Generate report
    print("\n" + "=" * 80)
    print("FEATURE PREDICTIVE POWER ANALYSIS")
    print("=" * 80)

    print("\n--- TOP 20 FEATURES BY INFORMATION COEFFICIENT ---")
    top_ic = comp_metrics.nlargest(20, "ic_combined")
    print(
        f"{'Feature':<35} {'IC Long':>10} {'IC Short':>10} {'IC Comb':>10} {'Importance':>12}"
    )
    print("-" * 80)
    for _, row in top_ic.iterrows():
        print(
            f"{row['feature']:<35} {row['ic_long']:>10.4f} {row['ic_short']:>10.4f} {row['ic_combined']:>10.4f} {row['importance_combined']:>12.0f}"
        )

    print("\n--- TOP 20 FEATURES BY MODEL IMPORTANCE ---")
    top_imp = comp_metrics.nlargest(20, "importance_combined")
    print(
        f"{'Feature':<35} {'IC Long':>10} {'IC Short':>10} {'IC Comb':>10} {'Importance':>12}"
    )
    print("-" * 80)
    for _, row in top_imp.iterrows():
        print(
            f"{row['feature']:<35} {row['ic_long']:>10.4f} {row['ic_short']:>10.4f} {row['ic_combined']:>10.4f} {row['importance_combined']:>12.0f}"
        )

    print("\n--- ICT MODEL (30 FEATURES) ANALYSIS ---")
    print(
        f"{'Feature':<35} {'IC Long':>10} {'IC Short':>10} {'IC Comb':>10} {'Importance':>12}"
    )
    print("-" * 80)
    for _, row in ict_metrics.nlargest(30, "ic_combined").iterrows():
        print(
            f"{row['feature']:<35} {row['ic_long']:>10.4f} {row['ic_short']:>10.4f} {row['ic_combined']:>10.4f} {row['importance_combined']:>12.0f}"
        )

    print("\n--- OPTIMAL FEATURE SET (50 features, IC>0.01, Corr<0.8) ---")
    optimal_metrics = comp_metrics[comp_metrics["feature"].isin(optimal_features)]
    print(
        f"{'Feature':<35} {'IC Long':>10} {'IC Short':>10} {'IC Comb':>10} {'Importance':>12}"
    )
    print("-" * 80)
    for _, row in optimal_metrics.iterrows():
        print(
            f"{row['feature']:<35} {row['ic_long']:>10.4f} {row['ic_short']:>10.4f} {row['ic_combined']:>10.4f} {row['importance_combined']:>12.0f}"
        )

    print("\n--- FEATURE CATEGORY ANALYSIS ---")

    # Categorize features
    def categorize_feature(feat):
        if any(x in feat for x in ["sma", "ema", "ma_"]):
            return "Moving Averages"
        elif any(x in feat for x in ["rsi", "stoch", "williams", "cci", "mfi"]):
            return "Momentum Oscillators"
        elif any(x in feat for x in ["atr", "volatility", "bb_"]):
            return "Volatility"
        elif any(x in feat for x in ["volume", "obv"]):
            return "Volume"
        elif any(x in feat for x in ["macd"]):
            return "MACD"
        elif any(x in feat for x in ["adx", "plus_di", "minus_di"]):
            return "Trend Strength"
        elif any(x in feat for x in ["returns", "roc", "momentum"]):
            return "Returns/Momentum"
        elif any(x in feat for x in ["time_", "hour", "minute", "is_"]):
            return "Time-Based"
        elif any(
            x in feat
            for x in ["fvg", "order_block", "liquidity", "bos", "displacement"]
        ):
            return "ICT Concepts"
        elif any(
            x in feat
            for x in ["pressure", "buying", "selling", "vwap", "pv_divergence"]
        ):
            return "Volume-Price Analysis"
        elif any(x in feat for x in ["_ratio", "_product", "_diff"]):
            return "Feature Interactions"
        elif any(x in feat for x in ["rank", "percentile"]):
            return "Cross-Sectional"
        elif any(x in feat for x in ["skew", "kurt", "acceleration"]):
            return "Statistical"
        elif any(x in feat for x in ["dist_to", "price_position"]):
            return "Support/Resistance"
        else:
            return "Other"

    comp_metrics["category"] = comp_metrics["feature"].apply(categorize_feature)

    category_stats = (
        comp_metrics.groupby("category")
        .agg(
            {
                "ic_combined": ["mean", "max", "count"],
                "importance_combined": ["mean", "sum"],
            }
        )
        .round(4)
    )

    print(category_stats.to_string())

    # Save results
    output_dir = Path("run")
    comp_metrics.to_csv(output_dir / "feature_analysis_comprehensive.csv", index=False)
    ict_metrics.to_csv(output_dir / "feature_analysis_ict.csv", index=False)

    with open(output_dir / "optimal_features.txt", "w") as f:
        for feat in optimal_features:
            f.write(f"{feat}\n")

    logging.info(
        f"Analysis complete. Optimal feature set: {len(optimal_features)} features"
    )
    logging.info(f"Results saved to {output_dir}/")


if __name__ == "__main__":
    main()
