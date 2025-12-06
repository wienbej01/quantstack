#!/usr/bin/env python3
"""Train v4 models on FULL 1,108-symbol universe (SMB approach)."""

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


def load_full_universe(
    universe_file: str = "/home/jacobw/quantstack/run/smb_universe.txt",
) -> list[str]:
    """Load full 1,108-symbol universe."""
    with open(universe_file) as f:
        symbols = [line.strip() for line in f if line.strip()]
    return symbols


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
    universe_file = "/home/jacobw/quantstack/run/smb_universe.txt"
    model_config = Path("configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml")
    output_root = Path("artefacts/extensions/intraday_ml/v4_full_universe")

    LOGGER.info("=" * 80)
    LOGGER.info("Training v4 Models on Full Universe (1,108 symbols)")
    LOGGER.info("=" * 80)

    # Load full universe
    LOGGER.info("Loading full universe...")
    symbols = load_full_universe(universe_file)
    LOGGER.info(f"Loaded {len(symbols)} symbols")

    # Check if training data exists, if not create it
    training_data_path = output_root / "training_data.parquet"

    if training_data_path.exists():
        LOGGER.info(f"Loading existing training data from: {training_data_path}")
        dataset = pd.read_parquet(training_data_path)
    else:
        LOGGER.info(
            "Training data not found. Use existing training data with full universe symbols."
        )
        LOGGER.info(
            "Loading from: artefacts/extensions/intraday_ml/phaseA_full_sip_v2/training_data.parquet"
        )
        dataset = pd.read_parquet(
            "artefacts/extensions/intraday_ml/phaseA_full_sip_v2/training_data.parquet"
        )

        # Filter to symbols in full universe
        LOGGER.info("Filtering to full universe symbols...")
        initial_count = len(dataset)
        dataset = dataset[dataset["symbol"].isin(symbols)].copy()
        final_count = len(dataset)
        LOGGER.info(
            f"Filtered: {initial_count} → {final_count} rows ({100*final_count/initial_count:.1f}%)"
        )

        # Save for future use
        output_root.mkdir(parents=True, exist_ok=True)
        dataset.to_parquet(training_data_path, index=False)
        LOGGER.info(f"Saved training data to: {training_data_path}")

    LOGGER.info(
        f"Training data: {len(dataset)} rows, {dataset['symbol'].nunique()} unique symbols"
    )

    # Prepare features
    feature_columns = select_feature_columns(dataset)
    features = prepare_feature_matrix(dataset, feature_columns)

    # Get labels
    bigmove = pd.to_numeric(dataset["y_bigmove"], errors="coerce").astype(int)
    direction = pd.to_numeric(dataset["y_bigmove_direction"], errors="coerce")

    # Load config
    model_cfg = load_yaml(model_config)
    settings = build_training_settings(model_cfg)
    model_params = dict(model_cfg.get("lgbm_params", {}) or {})

    # Train LONG Model
    LOGGER.info("=" * 80)
    LOGGER.info("Training LONG Model (v4 Full Universe)")
    LOGGER.info("=" * 80)

    labels_long = ((bigmove == 1) & (direction == 1)).astype(int)
    LOGGER.info(
        f"LONG: {labels_long.sum()} positive, {(labels_long == 0).sum()} negative"
    )

    model_long, metrics_long, cv_result_long = train_binary_model(
        features, labels_long, params=model_params, settings=settings
    )

    output_dir_long = output_root / "model_long"
    feature_perf_long = log_feature_performance(
        features, labels_long, model_long, feature_columns, output_dir_long
    )

    features_hash_long, targets_hash_long = compute_hashes(features, labels_long)

    metadata_long = {
        "stage": "v4_full_universe_long",
        "universe": "full_1108_symbols",
        "universe_size": len(symbols),
        "training_samples": int(len(labels_long)),
        "feature_count": int(len(feature_columns)),
        "class_distribution": {
            int(k): int(v) for k, v in labels_long.value_counts().to_dict().items()
        },
        "metrics": metrics_long,
        "cv_metrics": cv_result_long,
        "feature_performance": feature_perf_long,
        "features_hash": features_hash_long,
        "targets_hash": targets_hash_long,
    }

    save_training_artifacts(model_long, output_dir_long, feature_columns, metadata_long)
    LOGGER.info(f"LONG model: ROC AUC={metrics_long.get('roc_auc', 0):.4f}")

    # Train SHORT Model
    LOGGER.info("=" * 80)
    LOGGER.info("Training SHORT Model (v4 Full Universe)")
    LOGGER.info("=" * 80)

    labels_short = ((bigmove == 1) & (direction == -1)).astype(int)
    LOGGER.info(
        f"SHORT: {labels_short.sum()} positive, {(labels_short == 0).sum()} negative"
    )

    model_short, metrics_short, cv_result_short = train_binary_model(
        features, labels_short, params=model_params, settings=settings
    )

    output_dir_short = output_root / "model_short"
    feature_perf_short = log_feature_performance(
        features, labels_short, model_short, feature_columns, output_dir_short
    )

    features_hash_short, targets_hash_short = compute_hashes(features, labels_short)

    metadata_short = {
        "stage": "v4_full_universe_short",
        "universe": "full_1108_symbols",
        "universe_size": len(symbols),
        "training_samples": int(len(labels_short)),
        "feature_count": int(len(feature_columns)),
        "class_distribution": {
            int(k): int(v) for k, v in labels_short.value_counts().to_dict().items()
        },
        "metrics": metrics_short,
        "cv_metrics": cv_result_short,
        "feature_performance": feature_perf_short,
        "features_hash": features_hash_short,
        "targets_hash": targets_hash_short,
    }

    save_training_artifacts(
        model_short, output_dir_short, feature_columns, metadata_short
    )
    LOGGER.info(f"SHORT model: ROC AUC={metrics_short.get('roc_auc', 0):.4f}")

    LOGGER.info("=" * 80)
    LOGGER.info("v4 Full Universe Training Complete!")
    LOGGER.info(f"Universe: {len(symbols)} symbols (vs 97 in v3)")
    LOGGER.info(f"LONG ROC AUC: {metrics_long.get('roc_auc', 0):.4f}")
    LOGGER.info(f"SHORT ROC AUC: {metrics_short.get('roc_auc', 0):.4f}")
    LOGGER.info(f"Output: {output_root}")
    LOGGER.info("=" * 80)


if __name__ == "__main__":
    main()
