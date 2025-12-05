#!/usr/bin/env python3
"""Retrain models with price action features."""

import logging
from pathlib import Path

import pandas as pd

from extensions.intraday_ml.price_action_features import add_all_price_action_features
from extensions.intraday_ml_models.bigmove_training_utils import (
    TrainingSettings,
    compute_hashes,
    load_yaml,
    prepare_feature_matrix,
    save_training_artifacts,
    train_binary_model,
)
from extensions.intraday_ml_models.feature_performance import log_feature_performance

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def build_training_settings(config: dict) -> TrainingSettings:
    """Build training settings from config."""
    training_cfg = config.get("training", {}) or {}
    seed = int(training_cfg.get("seed", config.get("seed", 17)))
    n_folds = int(training_cfg.get("n_folds", 5))
    threshold = float(training_cfg.get("decision_threshold", 0.5))
    
    class_weight = config.get("class_weights") or training_cfg.get("class_weight")
    if isinstance(class_weight, dict) and "auto_balance" in class_weight:
        auto_cfg = class_weight["auto_balance"]
        if auto_cfg.get("enabled", False):
            class_weight = "balanced"
    
    return TrainingSettings(
        seed=seed,
        n_folds=max(2, n_folds),
        decision_threshold=threshold,
        class_weight=class_weight,
    )


def main():
    training_data_path = Path("artefacts/extensions/intraday_ml/phaseA_full_sip_v2/training_data.parquet")
    model_config = Path("configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml")
    output_root = Path("artefacts/extensions/intraday_ml/phaseA_full_sip_v3")
    
    LOGGER.info("=" * 60)
    LOGGER.info("Retraining with Price Action Features")
    LOGGER.info("=" * 60)
    
    # Load training data
    LOGGER.info("Loading training data...")
    dataset = pd.read_parquet(training_data_path)
    LOGGER.info("Loaded %d rows", len(dataset))
    
    # Add price action features
    LOGGER.info("Adding price action features...")
    dataset = add_all_price_action_features(dataset)
    
    # Count new features
    new_features = [c for c in dataset.columns if c.startswith("f__") and 
                   ("momentum" in c or "trend" in c or "dir__" in c or "vol__momentum" in c or "vol__trend" in c or "vol__price_corr" in c)]
    LOGGER.info("Added %d price action features", len(new_features))
    
    # Save enhanced training data
    output_root.mkdir(parents=True, exist_ok=True)
    enhanced_path = output_root / "training_data.parquet"
    dataset.to_parquet(enhanced_path)
    LOGGER.info("Saved enhanced training data to: %s", enhanced_path)
    
    # Get all feature columns
    feature_columns = sorted([c for c in dataset.columns if c.startswith("f__")])
    LOGGER.info("Total features: %d", len(feature_columns))
    
    # Prepare features
    features = prepare_feature_matrix(dataset, feature_columns)
    
    # Get labels
    bigmove = pd.to_numeric(dataset["y_bigmove"], errors="coerce").astype(int)
    direction = pd.to_numeric(dataset["y_bigmove_direction"], errors="coerce")
    
    # Train LONG model
    LOGGER.info("=" * 60)
    LOGGER.info("Training LONG Model (with price action)")
    LOGGER.info("=" * 60)
    
    labels_long = ((bigmove == 1) & (direction == 1)).astype(int)
    LOGGER.info("LONG samples: %d positive, %d negative", labels_long.sum(), (labels_long == 0).sum())
    
    model_cfg = load_yaml(model_config)
    settings = build_training_settings(model_cfg)
    model_params = dict(model_cfg.get("lgbm_params", {}) or {})
    
    model_long, metrics_long, cv_result_long = train_binary_model(
        features,
        labels_long,
        params=model_params,
        settings=settings,
    )
    
    output_dir_long = output_root / "model_long"
    
    LOGGER.info("Analyzing LONG model feature performance...")
    feature_perf_long = log_feature_performance(
        features=features,
        labels=labels_long,
        model=model_long,
        feature_columns=feature_columns,
        output_dir=output_dir_long,
    )
    
    features_hash_long, targets_hash_long = compute_hashes(features, labels_long)
    
    metadata_long = {
        "stage": "price_action_long",
        "target_name": "long_vs_rest",
        "training_samples": int(len(labels_long)),
        "feature_count": int(len(feature_columns)),
        "class_distribution": {int(k): int(v) for k, v in labels_long.value_counts().to_dict().items()},
        "metrics": metrics_long,
        "cv_metrics": cv_result_long,
        "feature_performance": feature_perf_long,
        "features_hash": features_hash_long,
        "targets_hash": targets_hash_long,
        "price_action_features": True,
    }
    
    save_training_artifacts(
        model=model_long,
        output_dir=output_dir_long,
        feature_columns=feature_columns,
        metadata=metadata_long,
    )
    
    LOGGER.info("LONG model complete: ROC AUC=%.4f", metrics_long.get("roc_auc", 0))
    
    # Train SHORT model
    LOGGER.info("=" * 60)
    LOGGER.info("Training SHORT Model (with price action)")
    LOGGER.info("=" * 60)
    
    labels_short = ((bigmove == 1) & (direction == -1)).astype(int)
    LOGGER.info("SHORT samples: %d positive, %d negative", labels_short.sum(), (labels_short == 0).sum())
    
    model_short, metrics_short, cv_result_short = train_binary_model(
        features,
        labels_short,
        params=model_params,
        settings=settings,
    )
    
    output_dir_short = output_root / "model_short"
    
    LOGGER.info("Analyzing SHORT model feature performance...")
    feature_perf_short = log_feature_performance(
        features=features,
        labels=labels_short,
        model=model_short,
        feature_columns=feature_columns,
        output_dir=output_dir_short,
    )
    
    features_hash_short, targets_hash_short = compute_hashes(features, labels_short)
    
    metadata_short = {
        "stage": "price_action_short",
        "target_name": "short_vs_rest",
        "training_samples": int(len(labels_short)),
        "feature_count": int(len(feature_columns)),
        "class_distribution": {int(k): int(v) for k, v in labels_short.value_counts().to_dict().items()},
        "metrics": metrics_short,
        "cv_metrics": cv_result_short,
        "feature_performance": feature_perf_short,
        "features_hash": features_hash_short,
        "targets_hash": targets_hash_short,
        "price_action_features": True,
    }
    
    save_training_artifacts(
        model=model_short,
        output_dir=output_dir_short,
        feature_columns=feature_columns,
        metadata=metadata_short,
    )
    
    LOGGER.info("SHORT model complete: ROC AUC=%.4f", metrics_short.get("roc_auc", 0))
    
    LOGGER.info("=" * 60)
    LOGGER.info("Price action retraining complete!")
    LOGGER.info("=" * 60)
    LOGGER.info("Output: %s", output_root)


if __name__ == "__main__":
    main()
