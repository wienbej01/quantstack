#!/usr/bin/env python3
"""Train v4 models on 100-symbol subset."""

import logging
from pathlib import Path

import pandas as pd

from extensions.intraday_ml_models.bigmove_training_utils import (
    TrainingSettings,
    compute_hashes,
    load_yaml,
    prepare_feature_matrix,
    save_training_artifacts,
    select_feature_columns,
    train_binary_model,
)
from extensions.intraday_ml_models.feature_performance import log_feature_performance

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def main():
    training_data_path = Path(
        "artefacts/extensions/intraday_ml/v4_subset_100/training_data.parquet"
    )
    model_config = Path("configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml")
    output_root = Path("artefacts/extensions/intraday_ml/v4_subset_100")

    LOGGER.info("=" * 80)
    LOGGER.info("Training v4 Models on 100-Symbol Subset")
    LOGGER.info("=" * 80)

    # Load data
    dataset = pd.read_parquet(training_data_path)
    LOGGER.info(f"Loaded {len(dataset)} rows, {dataset['symbol'].nunique()} symbols")

    # Prepare features
    feature_columns = select_feature_columns(dataset)
    features = prepare_feature_matrix(dataset, feature_columns)

    # Labels
    bigmove = pd.to_numeric(dataset["y_bigmove"], errors="coerce").astype(int)
    direction = pd.to_numeric(dataset["y_bigmove_direction"], errors="coerce")

    # Config
    model_cfg = load_yaml(model_config)
    settings = TrainingSettings(
        seed=17, n_folds=5, decision_threshold=0.5, class_weight="balanced"
    )
    model_params = dict(model_cfg.get("lgbm_params", {}) or {})

    # LONG
    LOGGER.info("Training LONG model...")
    labels_long = ((bigmove == 1) & (direction == 1)).astype(int)
    LOGGER.info(
        f"LONG: {labels_long.sum()} positive, {(labels_long == 0).sum()} negative"
    )

    model_long, metrics_long, cv_long = train_binary_model(
        features, labels_long, params=model_params, settings=settings
    )

    output_dir_long = output_root / "model_long"
    feature_perf_long = log_feature_performance(
        features, labels_long, model_long, feature_columns, output_dir_long
    )
    features_hash_long, targets_hash_long = compute_hashes(features, labels_long)

    metadata_long = {
        "stage": "v4_subset_100_long",
        "universe_size": 100,
        "training_samples": int(len(labels_long)),
        "feature_count": int(len(feature_columns)),
        "class_distribution": {
            int(k): int(v) for k, v in labels_long.value_counts().to_dict().items()
        },
        "metrics": metrics_long,
        "cv_metrics": cv_long,
        "feature_performance": feature_perf_long,
        "features_hash": features_hash_long,
        "targets_hash": targets_hash_long,
    }

    save_training_artifacts(model_long, output_dir_long, feature_columns, metadata_long)
    LOGGER.info(f"LONG ROC AUC: {metrics_long.get('roc_auc', 0):.4f}")

    # SHORT
    LOGGER.info("Training SHORT model...")
    labels_short = ((bigmove == 1) & (direction == -1)).astype(int)
    LOGGER.info(
        f"SHORT: {labels_short.sum()} positive, {(labels_short == 0).sum()} negative"
    )

    model_short, metrics_short, cv_short = train_binary_model(
        features, labels_short, params=model_params, settings=settings
    )

    output_dir_short = output_root / "model_short"
    feature_perf_short = log_feature_performance(
        features, labels_short, model_short, feature_columns, output_dir_short
    )
    features_hash_short, targets_hash_short = compute_hashes(features, labels_short)

    metadata_short = {
        "stage": "v4_subset_100_short",
        "universe_size": 100,
        "training_samples": int(len(labels_short)),
        "feature_count": int(len(feature_columns)),
        "class_distribution": {
            int(k): int(v) for k, v in labels_short.value_counts().to_dict().items()
        },
        "metrics": metrics_short,
        "cv_metrics": cv_short,
        "feature_performance": feature_perf_short,
        "features_hash": features_hash_short,
        "targets_hash": targets_hash_short,
    }

    save_training_artifacts(
        model_short, output_dir_short, feature_columns, metadata_short
    )
    LOGGER.info(f"SHORT ROC AUC: {metrics_short.get('roc_auc', 0):.4f}")

    LOGGER.info("=" * 80)
    LOGGER.info("Training Complete!")
    LOGGER.info("Universe: 100 symbols (vs 27 in v3)")
    LOGGER.info(f"LONG ROC AUC: {metrics_long.get('roc_auc', 0):.4f}")
    LOGGER.info(f"SHORT ROC AUC: {metrics_short.get('roc_auc', 0):.4f}")
    LOGGER.info("=" * 80)


if __name__ == "__main__":
    main()
