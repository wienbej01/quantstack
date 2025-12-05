"""Feature performance analysis and logging for model training."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

LOGGER = logging.getLogger(__name__)

# Thresholds for feature quality assessment
ZERO_VARIANCE_THRESHOLD = 1e-10
STRONG_CORRELATION_THRESHOLD = 0.10
MODERATE_CORRELATION_THRESHOLD = 0.05


def compute_feature_correlations(
    features: pd.DataFrame,
    labels: pd.Series,
    top_k: int = 50,
) -> dict[str, Any]:
    """Compute correlation between each feature and target label."""

    correlations = []
    for col in features.columns:
        feat_vals = features[col].values
        if np.std(feat_vals) < ZERO_VARIANCE_THRESHOLD:
            correlations.append(
                {"feature": col, "pearson": 0.0, "spearman": 0.0, "abs_pearson": 0.0}
            )
            continue

        pearson = np.corrcoef(feat_vals, labels.values)[0, 1]
        spearman, _ = spearmanr(feat_vals, labels.values, nan_policy="omit")

        correlations.append(
            {
                "feature": col,
                "pearson": float(pearson) if not np.isnan(pearson) else 0.0,
                "spearman": float(spearman) if not np.isnan(spearman) else 0.0,
                "abs_pearson": float(abs(pearson)) if not np.isnan(pearson) else 0.0,
            }
        )

    df = pd.DataFrame(correlations).sort_values("abs_pearson", ascending=False)

    top_features = df.head(top_k).to_dict("records")
    bottom_features = df.tail(20).to_dict("records")

    stats = {
        "max_abs_correlation": float(df["abs_pearson"].max()),
        "mean_abs_correlation": float(df["abs_pearson"].mean()),
        "median_abs_correlation": float(df["abs_pearson"].median()),
        "features_above_0.10": int(
            (df["abs_pearson"] > STRONG_CORRELATION_THRESHOLD).sum()
        ),
        "features_above_0.05": int(
            (df["abs_pearson"] > MODERATE_CORRELATION_THRESHOLD).sum()
        ),
        "zero_variance_features": int((df["abs_pearson"] == 0.0).sum()),
    }

    return {
        "statistics": stats,
        "top_features": top_features,
        "bottom_features": bottom_features,
        "all_correlations": df.to_dict("records"),
    }


def compute_feature_importance(
    model: Any,
    feature_columns: list[str],
    top_k: int = 50,
) -> dict[str, Any]:
    """Extract feature importance from trained model."""

    if not hasattr(model, "feature_importances_"):
        return {"available": False}

    importances = model.feature_importances_
    importance_df = pd.DataFrame(
        {
            "feature": feature_columns,
            "importance": importances,
        }
    ).sort_values("importance", ascending=False)

    top_features = importance_df.head(top_k).to_dict("records")
    zero_importance = importance_df[importance_df["importance"] == 0]

    stats = {
        "max_importance": float(importance_df["importance"].max()),
        "mean_importance": float(importance_df["importance"].mean()),
        "median_importance": float(importance_df["importance"].median()),
        "zero_importance_count": int(len(zero_importance)),
        "total_features": int(len(feature_columns)),
    }

    return {
        "available": True,
        "statistics": stats,
        "top_features": top_features,
        "zero_importance_features": zero_importance["feature"].tolist()[:20],
    }


def log_feature_performance(
    features: pd.DataFrame,
    labels: pd.Series,
    model: Any,
    feature_columns: list[str],
    output_dir: Path,
) -> dict[str, Any]:
    """Compute and log comprehensive feature performance metrics."""

    LOGGER.info("Computing feature correlations with target...")
    correlations = compute_feature_correlations(features, labels)

    LOGGER.info("Extracting feature importance from model...")
    importance = compute_feature_importance(model, feature_columns)

    # Log summary statistics
    corr_stats = correlations["statistics"]
    LOGGER.info(
        "Feature Correlation Stats: max=%.4f mean=%.4f median=%.4f above_0.10=%d above_0.05=%d",
        corr_stats["max_abs_correlation"],
        corr_stats["mean_abs_correlation"],
        corr_stats["median_abs_correlation"],
        corr_stats["features_above_0.10"],
        corr_stats["features_above_0.05"],
    )

    if importance["available"]:
        imp_stats = importance["statistics"]
        LOGGER.info(
            "Feature Importance Stats: max=%.4f mean=%.4f zero_count=%d",
            imp_stats["max_importance"],
            imp_stats["mean_importance"],
            imp_stats["zero_importance_count"],
        )

    # Log top features
    LOGGER.info("Top 10 Features by Correlation:")
    for i, feat in enumerate(correlations["top_features"][:10], 1):
        LOGGER.info(
            "  %2d. %s: pearson=%.4f spearman=%.4f",
            i,
            feat["feature"],
            feat["pearson"],
            feat["spearman"],
        )

    if importance["available"]:
        LOGGER.info("Top 10 Features by Importance:")
        for i, feat in enumerate(importance["top_features"][:10], 1):
            LOGGER.info("  %2d. %s: %.4f", i, feat["feature"], feat["importance"])

    # Save to disk
    output_dir.mkdir(parents=True, exist_ok=True)

    corr_path = output_dir / "feature_correlations.json"
    with open(corr_path, "w") as f:
        json.dump(correlations, f, indent=2)
    LOGGER.info("Saved feature correlations to %s", corr_path)

    if importance["available"]:
        imp_path = output_dir / "feature_importance.json"
        with open(imp_path, "w") as f:
            json.dump(importance, f, indent=2)
        LOGGER.info("Saved feature importance to %s", imp_path)

    # Create summary report
    summary = {
        "correlation_stats": corr_stats,
        "importance_stats": imp_stats if importance["available"] else None,
        "top_10_by_correlation": correlations["top_features"][:10],
        "top_10_by_importance": (
            importance["top_features"][:10] if importance["available"] else None
        ),
    }

    summary_path = output_dir / "feature_performance_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    LOGGER.info("Saved feature performance summary to %s", summary_path)

    return summary
