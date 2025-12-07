#!/usr/bin/env python3
"""
Comprehensive feature optimization analysis:
- Cross-correlation analysis
- Mutual information
- Feature interactions (synergy/redundancy)
- Recursive feature elimination
- Forward/backward selection
- Optimal feature set size determination
"""

import logging
import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.feature_selection import mutual_info_classif
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def calculate_correlation_matrix(df, features):
    """Calculate Spearman correlation matrix."""
    return df[features].corr(method="spearman")


def find_redundant_features(corr_matrix, threshold=0.9):
    """Find highly correlated feature pairs."""
    redundant = []
    for i in range(len(corr_matrix.columns)):
        for j in range(i + 1, len(corr_matrix.columns)):
            if abs(corr_matrix.iloc[i, j]) > threshold:
                redundant.append(
                    (
                        corr_matrix.columns[i],
                        corr_matrix.columns[j],
                        corr_matrix.iloc[i, j],
                    )
                )
    return redundant


def calculate_mutual_information(X, y):
    """Calculate mutual information between features and target."""
    mi_scores = mutual_info_classif(X, y, random_state=42, n_neighbors=5)
    return pd.Series(mi_scores, index=X.columns)


def calculate_vif(df, features):
    """Calculate Variance Inflation Factor for multicollinearity."""
    from statsmodels.stats.outliers_influence import variance_inflation_factor

    vif_data = pd.DataFrame()
    vif_data["feature"] = features
    vif_data["VIF"] = [
        variance_inflation_factor(df[features].values, i) for i in range(len(features))
    ]
    return vif_data


def test_feature_interactions(X, y, features, top_n=20):
    """Test pairwise feature interactions for synergy/redundancy."""
    results = []

    # Train baseline model with all features
    train_data = lgb.Dataset(X, label=y)
    params = {"objective": "binary", "metric": "auc", "verbose": -1, "seed": 42}
    baseline_model = lgb.train(params, train_data, num_boost_round=100)
    baseline_auc = roc_auc_score(y, baseline_model.predict(X))

    # Test removing pairs
    feature_list = list(features)
    for i, feat1 in enumerate(feature_list[:top_n]):
        for feat2 in feature_list[i + 1 : top_n]:
            # Remove both features
            remaining = [f for f in features if f not in [feat1, feat2]]
            X_reduced = X[remaining]

            train_data_reduced = lgb.Dataset(X_reduced, label=y)
            model_reduced = lgb.train(params, train_data_reduced, num_boost_round=100)
            reduced_auc = roc_auc_score(y, model_reduced.predict(X_reduced))

            # Synergy: removing both hurts more than expected
            # Redundancy: removing both hurts less than expected
            impact = baseline_auc - reduced_auc

            results.append(
                {
                    "feature1": feat1,
                    "feature2": feat2,
                    "impact": impact,
                    "type": (
                        "synergy"
                        if impact > 0.001
                        else "redundancy" if impact < -0.001 else "independent"
                    ),
                }
            )

    return pd.DataFrame(results)


def recursive_feature_elimination_analysis(X, y, n_features_range):
    """Perform RFE with different feature set sizes."""
    results = []

    for n_features in n_features_range:
        # Train model
        train_data = lgb.Dataset(X, label=y)
        params = {
            "objective": "binary",
            "metric": "auc",
            "verbose": -1,
            "seed": 42,
            "feature_fraction": min(1.0, n_features / len(X.columns)),
        }
        model = lgb.train(params, train_data, num_boost_round=200)

        # Get feature importance
        importance = model.feature_importance(importance_type="gain")
        top_features = [X.columns[i] for i in np.argsort(importance)[-n_features:]]

        # Evaluate with top features only
        X_selected = X[top_features]
        train_data_selected = lgb.Dataset(X_selected, label=y)
        model_selected = lgb.train(params, train_data_selected, num_boost_round=200)
        auc = roc_auc_score(y, model_selected.predict(X_selected))

        results.append({"n_features": n_features, "auc": auc, "features": top_features})

    return pd.DataFrame(results)


def forward_selection(X, y, max_features=50):
    """Forward feature selection."""
    selected = []
    remaining = list(X.columns)
    best_auc = 0

    params = {"objective": "binary", "metric": "auc", "verbose": -1, "seed": 42}

    for i in range(min(max_features, len(remaining))):
        best_feature = None
        best_iter_auc = best_auc

        for feature in remaining:
            current_features = selected + [feature]
            X_current = X[current_features]

            train_data = lgb.Dataset(X_current, label=y)
            model = lgb.train(params, train_data, num_boost_round=100)
            auc = roc_auc_score(y, model.predict(X_current))

            if auc > best_iter_auc:
                best_iter_auc = auc
                best_feature = feature

        if best_feature is None:
            break

        selected.append(best_feature)
        remaining.remove(best_feature)
        best_auc = best_iter_auc

        logging.info(f"Forward selection: {len(selected)} features, AUC={best_auc:.4f}")

    return selected, best_auc


def backward_elimination(X, y, min_features=10):
    """Backward feature elimination."""
    features = list(X.columns)

    params = {"objective": "binary", "metric": "auc", "verbose": -1, "seed": 42}

    # Baseline
    train_data = lgb.Dataset(X, label=y)
    model = lgb.train(params, train_data, num_boost_round=100)
    best_auc = roc_auc_score(y, model.predict(X))

    while len(features) > min_features:
        worst_feature = None
        best_iter_auc = 0

        for feature in features:
            current_features = [f for f in features if f != feature]
            X_current = X[current_features]

            train_data = lgb.Dataset(X_current, label=y)
            model = lgb.train(params, train_data, num_boost_round=100)
            auc = roc_auc_score(y, model.predict(X_current))

            if auc > best_iter_auc:
                best_iter_auc = auc
                worst_feature = feature

        if best_iter_auc < best_auc - 0.001:  # Stop if AUC drops significantly
            break

        features.remove(worst_feature)
        best_auc = best_iter_auc

        logging.info(
            f"Backward elimination: {len(features)} features, AUC={best_auc:.4f}"
        )

    return features, best_auc


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
    y_short = (val_comp["label"] == -1).astype(int)

    logging.info(f"Analyzing {len(features)} features on {len(X):,} samples")

    # === 1. CORRELATION ANALYSIS ===
    logging.info("1. Calculating correlation matrix...")
    corr_matrix = calculate_correlation_matrix(val_comp, features)

    # Find redundant features
    redundant_90 = find_redundant_features(corr_matrix, threshold=0.9)
    redundant_80 = find_redundant_features(corr_matrix, threshold=0.8)
    redundant_70 = find_redundant_features(corr_matrix, threshold=0.7)

    logging.info(f"   Redundant pairs (>0.9 corr): {len(redundant_90)}")
    logging.info(f"   Redundant pairs (>0.8 corr): {len(redundant_80)}")
    logging.info(f"   Redundant pairs (>0.7 corr): {len(redundant_70)}")

    # === 2. MUTUAL INFORMATION ===
    logging.info("2. Calculating mutual information...")
    mi_long = calculate_mutual_information(X, y_long)
    mi_short = calculate_mutual_information(X, y_short)
    mi_combined = (mi_long + mi_short) / 2

    # === 3. VIF ANALYSIS ===
    logging.info("3. Calculating VIF (multicollinearity)...")
    # Use top 50 features to avoid computational issues
    top_50_features = mi_combined.nlargest(50).index.tolist()
    try:
        vif_data = calculate_vif(val_comp, top_50_features)
    except:
        logging.warning(
            "   VIF calculation failed (likely due to perfect multicollinearity)"
        )
        vif_data = pd.DataFrame(
            {"feature": top_50_features, "VIF": [np.nan] * len(top_50_features)}
        )

    # === 4. FEATURE INTERACTIONS ===
    logging.info("4. Testing feature interactions (top 20)...")
    top_20_features = mi_combined.nlargest(20).index.tolist()
    X_top20 = X[top_20_features]
    interactions = test_feature_interactions(X_top20, y_long, top_20_features, top_n=20)

    # === 5. OPTIMAL FEATURE SET SIZE ===
    logging.info("5. Determining optimal feature set size...")
    n_features_range = [5, 10, 15, 20, 25, 30, 40, 50, 75, 100]
    rfe_results = recursive_feature_elimination_analysis(X, y_long, n_features_range)

    # === 6. FORWARD SELECTION ===
    logging.info("6. Forward feature selection...")
    forward_features, forward_auc = forward_selection(X, y_long, max_features=30)

    # === 7. BACKWARD ELIMINATION ===
    logging.info("7. Backward feature elimination...")
    backward_features, backward_auc = backward_elimination(X, y_long, min_features=20)

    # === GENERATE REPORT ===
    print("\n" + "=" * 100)
    print("COMPREHENSIVE FEATURE OPTIMIZATION ANALYSIS")
    print("=" * 100)

    print("\n--- 1. CORRELATION ANALYSIS ---")
    print(f"Total feature pairs: {len(features) * (len(features) - 1) // 2:,}")
    print(f"Highly redundant (>0.9 correlation): {len(redundant_90)} pairs")
    print(f"Moderately redundant (>0.8 correlation): {len(redundant_80)} pairs")
    print(f"Weakly redundant (>0.7 correlation): {len(redundant_70)} pairs")

    if len(redundant_90) > 0:
        print("\nTop 10 most correlated pairs (>0.9):")
        for feat1, feat2, corr in sorted(
            redundant_90, key=lambda x: abs(x[2]), reverse=True
        )[:10]:
            print(f"  {feat1:<35} <-> {feat2:<35} : {corr:6.3f}")

    print("\n--- 2. MUTUAL INFORMATION ANALYSIS ---")
    print(f"{'Feature':<35} {'MI Long':>10} {'MI Short':>10} {'MI Combined':>12}")
    print("-" * 100)
    for feat in mi_combined.nlargest(20).index:
        print(
            f"{feat:<35} {mi_long[feat]:>10.4f} {mi_short[feat]:>10.4f} {mi_combined[feat]:>12.4f}"
        )

    print("\n--- 3. MULTICOLLINEARITY (VIF) ANALYSIS ---")
    print("VIF > 10: High multicollinearity")
    print("VIF > 5: Moderate multicollinearity")
    print(f"\n{'Feature':<35} {'VIF':>10}")
    print("-" * 100)
    for _, row in vif_data.nlargest(20, "VIF").iterrows():
        print(f"{row['feature']:<35} {row['VIF']:>10.2f}")

    high_vif = vif_data[vif_data["VIF"] > 10]
    print(f"\nFeatures with VIF > 10: {len(high_vif)}")

    print("\n--- 4. FEATURE INTERACTION ANALYSIS ---")
    synergy = interactions[interactions["type"] == "synergy"].nlargest(10, "impact")
    redundancy = interactions[interactions["type"] == "redundancy"].nsmallest(
        10, "impact"
    )

    print("\nTop 10 Synergistic Pairs (removing both hurts performance):")
    print(f"{'Feature 1':<35} {'Feature 2':<35} {'Impact':>10}")
    print("-" * 100)
    for _, row in synergy.iterrows():
        print(f"{row['feature1']:<35} {row['feature2']:<35} {row['impact']:>10.4f}")

    print("\nTop 10 Redundant Pairs (removing both helps performance):")
    print(f"{'Feature 1':<35} {'Feature 2':<35} {'Impact':>10}")
    print("-" * 100)
    for _, row in redundancy.iterrows():
        print(f"{row['feature1']:<35} {row['feature2']:<35} {row['impact']:>10.4f}")

    print("\n--- 5. OPTIMAL FEATURE SET SIZE ---")
    print(f"{'N Features':>12} {'AUC':>10} {'Marginal Gain':>15}")
    print("-" * 100)
    prev_auc = 0
    for _, row in rfe_results.iterrows():
        marginal = row["auc"] - prev_auc
        print(f"{row['n_features']:>12} {row['auc']:>10.4f} {marginal:>15.4f}")
        prev_auc = row["auc"]

    # Find optimal size (diminishing returns)
    optimal_idx = rfe_results["auc"].diff().idxmax()
    optimal_size = rfe_results.loc[optimal_idx, "n_features"]
    optimal_auc = rfe_results.loc[optimal_idx, "auc"]

    print(
        f"\nOptimal feature set size: {optimal_size} features (AUC={optimal_auc:.4f})"
    )

    print("\n--- 6. FORWARD SELECTION RESULTS ---")
    print(f"Selected {len(forward_features)} features with AUC={forward_auc:.4f}")
    print("\nTop 20 features (in selection order):")
    for i, feat in enumerate(forward_features[:20], 1):
        print(f"  {i:2d}. {feat}")

    print("\n--- 7. BACKWARD ELIMINATION RESULTS ---")
    print(f"Retained {len(backward_features)} features with AUC={backward_auc:.4f}")
    print("\nRetained features:")
    for i, feat in enumerate(backward_features[:20], 1):
        print(f"  {i:2d}. {feat}")

    print("\n--- 8. CONSENSUS FEATURE SET ---")
    # Features selected by multiple methods
    forward_set = set(forward_features)
    backward_set = set(backward_features)
    optimal_set = set(
        rfe_results[rfe_results["n_features"] == optimal_size].iloc[0]["features"]
    )

    consensus = forward_set & backward_set & optimal_set
    print(f"Features selected by all 3 methods: {len(consensus)}")
    for feat in sorted(consensus):
        print(f"  - {feat}")

    # === SAVE RESULTS ===
    output_dir = Path("run")

    # Save correlation matrix
    corr_matrix.to_csv(output_dir / "feature_correlation_matrix.csv")

    # Save redundant pairs
    pd.DataFrame(redundant_90, columns=["feature1", "feature2", "correlation"]).to_csv(
        output_dir / "redundant_features_0.9.csv", index=False
    )

    # Save mutual information
    mi_df = pd.DataFrame(
        {
            "feature": mi_combined.index,
            "mi_long": mi_long.values,
            "mi_short": mi_short.values,
            "mi_combined": mi_combined.values,
        }
    ).sort_values("mi_combined", ascending=False)
    mi_df.to_csv(output_dir / "mutual_information.csv", index=False)

    # Save VIF
    vif_data.to_csv(output_dir / "vif_analysis.csv", index=False)

    # Save interactions
    interactions.to_csv(output_dir / "feature_interactions.csv", index=False)

    # Save RFE results
    rfe_results.to_csv(output_dir / "rfe_optimal_size.csv", index=False)

    # Save selected features
    with open(output_dir / "forward_selected_features.txt", "w") as f:
        for feat in forward_features:
            f.write(f"{feat}\n")

    with open(output_dir / "backward_selected_features.txt", "w") as f:
        for feat in backward_features:
            f.write(f"{feat}\n")

    with open(output_dir / "consensus_features.txt", "w") as f:
        for feat in sorted(consensus):
            f.write(f"{feat}\n")

    logging.info(f"Analysis complete. Results saved to {output_dir}/")

    print("\n" + "=" * 100)
    print("RECOMMENDATIONS")
    print("=" * 100)
    print(f"1. Optimal feature set size: {optimal_size} features")
    print(f"2. Remove {len(redundant_90)} highly correlated pairs (>0.9)")
    print(f"3. Focus on {len(consensus)} consensus features (selected by all methods)")
    print(f"4. Expected AUC: {optimal_auc:.4f}")
    print("=" * 100)


if __name__ == "__main__":
    main()
