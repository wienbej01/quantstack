#!/usr/bin/env python3
"""Fast retraining by reusing existing features and only recomputing labels."""

import logging
from pathlib import Path

import pandas as pd

from extensions.intraday_ml_models.bigmove_training_utils import (
    TrainingSettings,
    attach_bigmove_labels,
    compute_hashes,
    load_yaml,
    prepare_feature_matrix,
    save_training_artifacts,
    select_feature_columns,
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
    # Paths
    old_training_data = Path("artefacts/extensions/intraday_ml/phaseA_full_sip/training_data.parquet")
    new_targets_config = Path("configs/extensions/intraday_ml/targets_bigmove.yaml")
    model_config_s1 = Path("configs/extensions/intraday_ml/model_bigmove_stage1.yaml")
    model_config_s2 = Path("configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml")
    output_root = Path("artefacts/extensions/intraday_ml/phaseA_full_sip_v2")
    
    LOGGER.info("Fast retraining using existing features from: %s", old_training_data)
    
    # Load existing training data (has features already computed)
    LOGGER.info("Loading existing training data...")
    dataset = pd.read_parquet(old_training_data)
    LOGGER.info("Loaded %d rows with %d columns", len(dataset), len(dataset.columns))
    
    # Load new targets config
    targets_cfg = load_yaml(new_targets_config)
    
    # Recompute labels with new horizons
    LOGGER.info("Recomputing labels with new horizons (15-30-45min)...")
    dataset, label_config = attach_bigmove_labels(dataset, targets_cfg)
    
    # Save updated training data
    output_root.mkdir(parents=True, exist_ok=True)
    training_data_path = output_root / "training_data.parquet"
    dataset.to_parquet(training_data_path)
    LOGGER.info("Saved updated training data to: %s", training_data_path)
    
    # Stage 1: Probability Model
    LOGGER.info("=" * 60)
    LOGGER.info("Stage 1: Training probability model")
    LOGGER.info("=" * 60)
    
    feature_columns = select_feature_columns(dataset)
    features = prepare_feature_matrix(dataset, feature_columns)
    
    target_col = label_config.label_name
    labels = pd.to_numeric(dataset[target_col], errors="coerce").astype(int)
    
    valid_mask = labels.isin({0, 1})
    features_s1 = features.loc[valid_mask].reset_index(drop=True)
    labels_s1 = labels.loc[valid_mask].reset_index(drop=True)
    
    LOGGER.info("Training samples: %d, Features: %d", len(labels_s1), len(feature_columns))
    
    model_cfg_s1 = load_yaml(model_config_s1)
    settings_s1 = build_training_settings(model_cfg_s1)
    model_params_s1 = dict(model_cfg_s1.get("lgbm_params", {}) or {})
    
    model_s1, metrics_s1, cv_result_s1 = train_binary_model(
        features_s1,
        labels_s1,
        params=model_params_s1,
        settings=settings_s1,
    )
    
    LOGGER.info("Analyzing Stage 1 feature performance...")
    feature_perf_s1 = log_feature_performance(
        features=features_s1,
        labels=labels_s1,
        model=model_s1,
        feature_columns=feature_columns,
        output_dir=output_root,
    )
    
    features_hash_s1, targets_hash_s1 = compute_hashes(features_s1, labels_s1)
    
    metadata_s1 = {
        "stage": "stage1_probability",
        "target_name": target_col,
        "training_samples": int(len(labels_s1)),
        "feature_count": int(len(feature_columns)),
        "class_distribution": {int(k): int(v) for k, v in labels_s1.value_counts().to_dict().items()},
        "metrics": metrics_s1,
        "cv_metrics": cv_result_s1,
        "feature_performance": feature_perf_s1,
        "features_hash": features_hash_s1,
        "targets_hash": targets_hash_s1,
        "fast_retrain": True,
        "reused_features_from": str(old_training_data),
    }
    
    save_training_artifacts(
        model=model_s1,
        output_dir=output_root,
        feature_columns=feature_columns,
        metadata=metadata_s1,
    )
    
    LOGGER.info("Stage 1 complete: ROC AUC=%.4f", metrics_s1.get("roc_auc", 0))
    
    # Stage 2: Direction Model
    LOGGER.info("=" * 60)
    LOGGER.info("Stage 2: Training direction model")
    LOGGER.info("=" * 60)
    
    direction_col = label_config.direction_label_name
    bigmove_mask = dataset[target_col] == 1
    direction = pd.to_numeric(dataset.loc[bigmove_mask, direction_col], errors="coerce")
    
    features_s2 = features.loc[bigmove_mask].reset_index(drop=True)
    labels_s2 = direction.map({-1: 0, 1: 1}).astype(int).reset_index(drop=True)
    
    min_classes_required = 2
    if labels_s2.nunique() < min_classes_required:
        raise RuntimeError("Direction training requires both long and short samples.")
    
    LOGGER.info("Training samples: %d, Features: %d", len(labels_s2), len(feature_columns))
    
    model_cfg_s2 = load_yaml(model_config_s2)
    settings_s2 = build_training_settings(model_cfg_s2)
    model_params_s2 = dict(model_cfg_s2.get("lgbm_params", {}) or {})
    
    model_s2, metrics_s2, cv_result_s2 = train_binary_model(
        features_s2,
        labels_s2,
        params=model_params_s2,
        settings=settings_s2,
    )
    
    output_dir_s2 = output_root / "bigmove_stage2_dir"
    
    LOGGER.info("Analyzing Stage 2 feature performance...")
    feature_perf_s2 = log_feature_performance(
        features=features_s2,
        labels=labels_s2,
        model=model_s2,
        feature_columns=feature_columns,
        output_dir=output_dir_s2,
    )
    
    features_hash_s2, targets_hash_s2 = compute_hashes(features_s2, labels_s2)
    
    metadata_s2 = {
        "stage": "stage2_direction",
        "target_name": direction_col,
        "training_samples": int(len(labels_s2)),
        "feature_count": int(len(feature_columns)),
        "class_distribution": {int(k): int(v) for k, v in labels_s2.value_counts().to_dict().items()},
        "metrics": metrics_s2,
        "cv_metrics": cv_result_s2,
        "feature_performance": feature_perf_s2,
        "features_hash": features_hash_s2,
        "targets_hash": targets_hash_s2,
        "fast_retrain": True,
    }
    
    save_training_artifacts(
        model=model_s2,
        output_dir=output_dir_s2,
        feature_columns=feature_columns,
        metadata=metadata_s2,
    )
    
    LOGGER.info("Stage 2 complete: ROC AUC=%.4f", metrics_s2.get("roc_auc", 0))
    
    LOGGER.info("=" * 60)
    LOGGER.info("Fast retraining complete!")
    LOGGER.info("=" * 60)


if __name__ == "__main__":
    main()
