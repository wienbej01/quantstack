#!/usr/bin/env python3
"""Fast feature optimization analysis."""

import logging
import warnings
from pathlib import Path

import lightgbm as lgb
import pandas as pd
from sklearn.feature_selection import mutual_info_classif
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def main():
    logging.info("Loading data...")
    data_dir = Path("artefacts/extensions/intraday_ml/v4_6months")
    val_df = pd.read_parquet(data_dir / "val.parquet")

    # Engineer comprehensive features
    logging.info("Engineering features...")
    from train_v4_6months_comprehensive_features import engineer_comprehensive_features

    val_comp = engineer_comprehensive_features(val_df.copy())
    val_comp = val_comp.dropna()

    # Prepare data
    exclude_cols = {
        "symbol",
        "ts",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "label",
        "hour",
        "minute",
        "tr",
    }
    features = [c for c in val_comp.columns if c not in exclude_cols]

    X = val_comp[features]
    y_long = (val_comp["label"] == 1).astype(int)

    logging.info(f"Analyzing {len(features)} features")

    # 1. Correlation analysis
    logging.info("1. Correlation analysis...")
    corr_matrix = X.corr(method="spearman").abs()

    # Find redundant pairs
    redundant_pairs = []
    for i in range(len(corr_matrix.columns)):
        for j in range(i + 1, len(corr_matrix.columns)):
            if corr_matrix.iloc[i, j] > 0.9:
                redundant_pairs.append(
                    (
                        corr_matrix.columns[i],
                        corr_matrix.columns[j],
                        corr_matrix.iloc[i, j],
                    )
                )

    # 2. Mutual information
    logging.info("2. Mutual information...")
    mi_scores = mutual_info_classif(X, y_long, random_state=42, n_neighbors=3)
    mi_df = pd.DataFrame({"feature": features, "mi": mi_scores}).sort_values(
        "mi", ascending=False
    )

    # 3. Test different feature set sizes
    logging.info("3. Testing feature set sizes...")
    size_results = []

    for n_features in [10, 15, 20, 25, 30, 40, 50, 75, 100]:
        top_features = mi_df.head(n_features)["feature"].tolist()
        X_subset = X[top_features]

        train_data = lgb.Dataset(X_subset, label=y_long)
        params = {
            "objective": "binary",
            "metric": "auc",
            "verbose": -1,
            "seed": 42,
            "num_leaves": 31,
        }
        model = lgb.train(params, train_data, num_boost_round=200)

        auc = roc_auc_score(y_long, model.predict(X_subset))
        size_results.append({"n_features": n_features, "auc": auc})
        logging.info(f"   {n_features} features: AUC={auc:.4f}")

    size_df = pd.DataFrame(size_results)

    # 4. Remove redundant features iteratively
    logging.info("4. Removing redundant features...")

    # Start with top 50 by MI
    selected = mi_df.head(50)["feature"].tolist()

    # Remove redundant pairs
    removed = []
    for feat1, feat2, corr in sorted(redundant_pairs, key=lambda x: x[2], reverse=True):
        if feat1 in selected and feat2 in selected:
            # Remove the one with lower MI
            mi1 = mi_df[mi_df["feature"] == feat1]["mi"].values[0]
            mi2 = mi_df[mi_df["feature"] == feat2]["mi"].values[0]

            to_remove = feat1 if mi1 < mi2 else feat2
            selected.remove(to_remove)
            removed.append((feat1, feat2, corr, to_remove))

    logging.info(f"   Removed {len(removed)} redundant features")
    logging.info(f"   Final set: {len(selected)} features")

    # Test optimized set
    X_optimized = X[selected]
    train_data = lgb.Dataset(X_optimized, label=y_long)
    model_opt = lgb.train(params, train_data, num_boost_round=200)
    auc_opt = roc_auc_score(y_long, model_opt.predict(X_optimized))

    # === REPORT ===
    print("\n" + "=" * 100)
    print("FEATURE OPTIMIZATION ANALYSIS")
    print("=" * 100)

    print("\n--- 1. CORRELATION ANALYSIS ---")
    print(f"Total features: {len(features)}")
    print(f"Highly correlated pairs (>0.9): {len(redundant_pairs)}")

    print("\nTop 15 most correlated pairs:")
    print(f"{'Feature 1':<35} {'Feature 2':<35} {'Correlation':>12}")
    print("-" * 100)
    for feat1, feat2, corr in sorted(redundant_pairs, key=lambda x: x[2], reverse=True)[
        :15
    ]:
        print(f"{feat1:<35} {feat2:<35} {corr:>12.3f}")

    print("\n--- 2. MUTUAL INFORMATION (Top 30) ---")
    print(f"{'Feature':<40} {'MI Score':>12}")
    print("-" * 100)
    for _, row in mi_df.head(30).iterrows():
        print(f"{row['feature']:<40} {row['mi']:>12.4f}")

    print("\n--- 3. FEATURE SET SIZE ANALYSIS ---")
    print(f"{'N Features':>12} {'AUC':>10} {'Marginal Gain':>15}")
    print("-" * 100)
    prev_auc = 0
    for _, row in size_df.iterrows():
        marginal = row["auc"] - prev_auc
        print(f"{row['n_features']:>12} {row['auc']:>10.4f} {marginal:>15.4f}")
        prev_auc = row["auc"]

    # Find optimal size
    size_df["marginal"] = size_df["auc"].diff()
    optimal_idx = size_df["marginal"].idxmax()
    optimal_size = size_df.loc[optimal_idx, "n_features"]
    optimal_auc = size_df.loc[optimal_idx, "auc"]

    print(
        f"\nOptimal size (max marginal gain): {optimal_size} features (AUC={optimal_auc:.4f})"
    )

    # Diminishing returns threshold
    threshold_idx = (
        size_df[size_df["marginal"] < 0.001].index[0]
        if any(size_df["marginal"] < 0.001)
        else len(size_df) - 1
    )
    threshold_size = size_df.loc[threshold_idx, "n_features"]
    threshold_auc = size_df.loc[threshold_idx, "auc"]

    print(
        f"Diminishing returns (<0.001 gain): {threshold_size} features (AUC={threshold_auc:.4f})"
    )

    print("\n--- 4. OPTIMIZED FEATURE SET (Redundancy Removed) ---")
    print("Original: 50 features")
    print(f"Removed: {len(removed)} redundant features")
    print(f"Final: {len(selected)} features")
    print(f"AUC: {auc_opt:.4f}")

    print("\nRemoved redundant pairs:")
    print(f"{'Feature 1':<35} {'Feature 2':<35} {'Corr':>8} {'Removed':>35}")
    print("-" * 100)
    for feat1, feat2, corr, removed_feat in removed[:20]:
        print(f"{feat1:<35} {feat2:<35} {corr:>8.3f} {removed_feat:>35}")

    print("\n--- 5. FINAL OPTIMIZED FEATURE SET ---")
    print(f"Features: {len(selected)}")
    print(f"AUC: {auc_opt:.4f}")
    print("\nFeatures (ranked by MI):")
    for i, feat in enumerate(selected, 1):
        mi_score = mi_df[mi_df["feature"] == feat]["mi"].values[0]
        print(f"  {i:2d}. {feat:<40} (MI={mi_score:.4f})")

    # === SAVE RESULTS ===
    output_dir = Path("run")

    # Save results
    mi_df.to_csv(output_dir / "mutual_information_fast.csv", index=False)
    size_df.to_csv(output_dir / "feature_size_analysis.csv", index=False)

    pd.DataFrame(
        redundant_pairs, columns=["feature1", "feature2", "correlation"]
    ).to_csv(output_dir / "redundant_pairs.csv", index=False)

    with open(output_dir / "optimized_features.txt", "w") as f:
        for feat in selected:
            f.write(f"{feat}\n")

    # Create summary report
    with open(output_dir / "optimization_summary.txt", "w") as f:
        f.write("FEATURE OPTIMIZATION SUMMARY\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Total features analyzed: {len(features)}\n")
        f.write(f"Redundant pairs (>0.9 corr): {len(redundant_pairs)}\n")
        f.write(f"Optimal feature set size: {optimal_size} (AUC={optimal_auc:.4f})\n")
        f.write(
            f"Diminishing returns at: {threshold_size} features (AUC={threshold_auc:.4f})\n"
        )
        f.write(
            f"Optimized set (redundancy removed): {len(selected)} features (AUC={auc_opt:.4f})\n"
        )
        f.write("\n")
        f.write("RECOMMENDATION:\n")
        f.write(f"Use {len(selected)} features with redundancy removed\n")
        f.write(f"Expected AUC: {auc_opt:.4f}\n")

    logging.info(f"Analysis complete. Results saved to {output_dir}/")

    print("\n" + "=" * 100)
    print("RECOMMENDATIONS")
    print("=" * 100)
    print(f"1. Optimal feature set size: {optimal_size} features (max marginal gain)")
    print(f"2. Diminishing returns at: {threshold_size} features")
    print(f"3. Optimized set (redundancy removed): {len(selected)} features")
    print(f"4. Expected AUC: {auc_opt:.4f}")
    print(f"5. Remove {len(redundant_pairs)} highly correlated pairs")
    print("=" * 100)


if __name__ == "__main__":
    main()
