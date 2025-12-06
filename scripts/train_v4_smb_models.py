#!/usr/bin/env python3
"""Train v4 LONG/SHORT models on SMB catalyst-driven universe."""

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

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
LOGGER = logging.getLogger(__name__)


def load_smb_sip_universe(
    sip_path: str = "/home/jacobw/quantstack/run/sip_membership_smb",
) -> set[str]:
    """Load unique symbols from SMB SIP data."""
    sip_dir = Path(sip_path)

    if not sip_dir.exists():
        raise FileNotFoundError(f"SMB SIP path not found: {sip_path}")

    all_symbols = set()

    # Read all partitions
    for partition_dir in sip_dir.glob("trade_date=*"):
        data_file = partition_dir / "data.parquet"
        if data_file.exists():
            df = pd.read_parquet(data_file)
            all_symbols.update(df["symbol"].unique())

    LOGGER.info("Loaded %d unique symbols from SMB SIP", len(all_symbols))
    return all_symbols


def filter_training_data_by_smb_universe(
    training_data: pd.DataFrame, smb_symbols: set[str]
) -> pd.DataFrame:
    """Filter training data to only include SMB universe symbols."""

    initial_count = len(training_data)
    filtered = training_data[training_data["symbol"].isin(smb_symbols)].copy()
    final_count = len(filtered)

    LOGGER.info(
        "Filtered training data: %d → %d rows (%.1f%%)",
        initial_count,
        final_count,
        100 * final_count / initial_count,
    )

    return filtered


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
    training_data_path = Path(
        "artefacts/extensions/intraday_ml/phaseA_full_sip_v2/training_data.parquet"
    )
    model_config = Path("configs/extensions/intraday_ml/model_bigmove_stage2_dir.yaml")
    smb_sip_path = "/home/jacobw/quantstack/run/sip_membership_smb"
    output_root = Path("artefacts/extensions/intraday_ml/v4_smb")

    LOGGER.info("=" * 80)
    LOGGER.info("Training v4 SMB Models (LONG/SHORT)")
    LOGGER.info("=" * 80)

    # Load SMB universe
    LOGGER.info("Loading SMB universe...")
    smb_symbols = load_smb_sip_universe(smb_sip_path)

    # Load training data
    LOGGER.info("Loading training data from: %s", training_data_path)
    dataset = pd.read_parquet(training_data_path)
    LOGGER.info("Loaded %d rows", len(dataset))

    # Filter to SMB universe
    LOGGER.info("Filtering to SMB universe...")
    dataset = filter_training_data_by_smb_universe(dataset, smb_symbols)

    if len(dataset) == 0:
        LOGGER.error("No training data after SMB filtering!")
        return

    # Prepare features
    feature_columns = select_feature_columns(dataset)
    features = prepare_feature_matrix(dataset, feature_columns)

    # Get labels
    bigmove_col = "y_bigmove"
    direction_col = "y_bigmove_direction"

    bigmove = pd.to_numeric(dataset[bigmove_col], errors="coerce").astype(int)
    direction = pd.to_numeric(dataset[direction_col], errors="coerce")

    # Load config
    model_cfg = load_yaml(model_config)
    settings = build_training_settings(model_cfg)
    model_params = dict(model_cfg.get("lgbm_params", {}) or {})

    # Train LONG Model
    LOGGER.info("=" * 80)
    LOGGER.info("Training LONG Model (v4 SMB)")
    LOGGER.info("=" * 80)

    labels_long = ((bigmove == 1) & (direction == 1)).astype(int)
    LOGGER.info(
        "LONG samples: %d positive, %d negative",
        labels_long.sum(),
        (labels_long == 0).sum(),
    )

    model_long, metrics_long, cv_result_long = train_binary_model(
        features,
        labels_long,
        params=model_params,
        settings=settings,
    )

    output_dir_long = output_root / "model_long"

    feature_perf_long = log_feature_performance(
        features=features,
        labels=labels_long,
        model=model_long,
        feature_columns=feature_columns,
        output_dir=output_dir_long,
    )

    features_hash_long, targets_hash_long = compute_hashes(features, labels_long)

    metadata_long = {
        "stage": "v4_smb_long",
        "target_name": "long_vs_rest",
        "universe": "smb_catalyst_driven",
        "universe_size": len(smb_symbols),
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

    save_training_artifacts(
        model=model_long,
        output_dir=output_dir_long,
        feature_columns=feature_columns,
        metadata=metadata_long,
    )

    LOGGER.info("LONG model complete: ROC AUC=%.4f", metrics_long.get("roc_auc", 0))

    # Train SHORT Model
    LOGGER.info("=" * 80)
    LOGGER.info("Training SHORT Model (v4 SMB)")
    LOGGER.info("=" * 80)

    labels_short = ((bigmove == 1) & (direction == -1)).astype(int)
    LOGGER.info(
        "SHORT samples: %d positive, %d negative",
        labels_short.sum(),
        (labels_short == 0).sum(),
    )

    model_short, metrics_short, cv_result_short = train_binary_model(
        features,
        labels_short,
        params=model_params,
        settings=settings,
    )

    output_dir_short = output_root / "model_short"

    feature_perf_short = log_feature_performance(
        features=features,
        labels=labels_short,
        model=model_short,
        feature_columns=feature_columns,
        output_dir=output_dir_short,
    )

    features_hash_short, targets_hash_short = compute_hashes(features, labels_short)

    metadata_short = {
        "stage": "v4_smb_short",
        "target_name": "short_vs_rest",
        "universe": "smb_catalyst_driven",
        "universe_size": len(smb_symbols),
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
        model=model_short,
        output_dir=output_dir_short,
        feature_columns=feature_columns,
        metadata=metadata_short,
    )

    LOGGER.info("SHORT model complete: ROC AUC=%.4f", metrics_short.get("roc_auc", 0))

    LOGGER.info("=" * 80)
    LOGGER.info("v4 SMB models training complete!")
    LOGGER.info("=" * 80)
    LOGGER.info("Universe: %d SMB catalyst-driven symbols", len(smb_symbols))
    LOGGER.info("LONG ROC AUC: %.4f", metrics_long.get("roc_auc", 0))
    LOGGER.info("SHORT ROC AUC: %.4f", metrics_short.get("roc_auc", 0))
    LOGGER.info("Output: %s", output_root)


if __name__ == "__main__":
    main()
