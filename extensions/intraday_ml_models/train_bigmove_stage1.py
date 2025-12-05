"""Train the Stage 1 big-move probability model."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from extensions.intraday_ml.utils.heartbeat import HeartbeatLogger

from .bigmove_training_utils import (
    TrainingSettings,
    attach_bigmove_labels,
    build_split_dataset,
    compute_hashes,
    load_master_and_includes,
    load_yaml,
    prepare_feature_matrix,
    save_training_artifacts,
    select_feature_columns,
    train_binary_model,
)
from .feature_performance import log_feature_performance

DEFAULT_DATASET_CONFIG = Path("configs/extensions/intraday_ml/phaseA_sip_full.yaml")
DEFAULT_TARGETS_CONFIG = Path("configs/extensions/intraday_ml/targets_bigmove.yaml")
DEFAULT_OUTPUT_ROOT = Path("artefacts/extensions/intraday_ml/bigmove_stage1")

LOGGER = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Train Stage 1 big-move probability model"
    )
    parser.add_argument(
        "--dataset-config",
        type=Path,
        default=DEFAULT_DATASET_CONFIG,
        help="Master dataset config (Phase A).",
    )
    parser.add_argument(
        "--model-config",
        type=Path,
        required=True,
        help="Model hyperparameter config for Stage 1.",
    )
    parser.add_argument(
        "--targets-config",
        type=Path,
        default=DEFAULT_TARGETS_CONFIG,
        help="Targets config defining big-move labels.",
    )
    parser.add_argument(
        "--split",
        default="train",
        help="Dataset split to train on (default: train).",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Directory to store model artefacts.",
    )
    parser.add_argument(
        "--label-buffer-days",
        type=int,
        default=None,
        help="Optional override for label buffer days when building datasets.",
    )
    return parser.parse_args()


def build_training_settings(config: dict[str, Any]) -> TrainingSettings:
    training_cfg = config.get("training", {}) or {}
    seed = int(training_cfg.get("seed", config.get("seed", 17)))
    n_folds = int(training_cfg.get("n_folds", 5))
    threshold = float(training_cfg.get("decision_threshold", 0.5))

    # Handle both class_weight and class_weights (plural)
    class_weight = config.get("class_weights") or training_cfg.get("class_weight")

    # If class_weights has auto_balance config, convert to "balanced"
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


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
    )
    with HeartbeatLogger("bigmove_stage1_training", interval_seconds=60):
        LOGGER.info("Loading master/targets/model configs ...")
        master_config, includes = load_master_and_includes(args.dataset_config)
        targets_cfg = load_yaml(args.targets_config)
        model_cfg = load_yaml(args.model_config)

        LOGGER.info("Building dataset for split=%s ...", args.split)
        dataset, dataset_meta = build_split_dataset(
            master_config=master_config,
            includes=includes,
            targets_config=targets_cfg,
            split=args.split,
            label_buffer_days=args.label_buffer_days,
        )
        LOGGER.info("Attaching big-move labels ...")
        dataset, label_config = attach_bigmove_labels(dataset, targets_cfg)

        feature_columns = select_feature_columns(dataset)
        features = prepare_feature_matrix(dataset, feature_columns)

        target_col = label_config.label_name
        labels = pd.to_numeric(dataset[target_col], errors="coerce").astype(int)

        valid_mask = labels.isin({0, 1})
        features = features.loc[valid_mask].reset_index(drop=True)
        labels = labels.loc[valid_mask].reset_index(drop=True)

        if labels.empty:
            raise RuntimeError("No valid big-move samples available for training.")

        LOGGER.info(
            "Training Stage 1 LightGBM model (samples=%d, features=%d)...",
            len(labels),
            len(feature_columns),
        )
        model_params = dict(model_cfg.get("lgbm_params", {}) or {})
        settings = build_training_settings(model_cfg)

        model, metrics, cv_result = train_binary_model(
            features,
            labels,
            params=model_params,
            settings=settings,
        )

        LOGGER.info("Analyzing feature performance...")
        feature_perf = log_feature_performance(
            features=features,
            labels=labels,
            model=model,
            feature_columns=feature_columns,
            output_dir=args.output_root,
        )

        features_hash, targets_hash = compute_hashes(features, labels)

        class_distribution = {
            int(k): int(v) for k, v in labels.value_counts().to_dict().items()
        }
        metadata = {
            "stage": "stage1_probability",
            "target_name": target_col,
            "training_samples": int(len(labels)),
            "feature_count": int(len(feature_columns)),
            "class_distribution": class_distribution,
            "metrics": metrics,
            "cv_metrics": cv_result,
            "feature_performance": feature_perf,
            "features_hash": features_hash,
            "targets_hash": targets_hash,
            "dataset": {
                "config": str(args.dataset_config),
                "split": args.split,
                **dataset_meta,
            },
            "config_paths": {
                "model": str(args.model_config),
                "targets": str(args.targets_config),
            },
            "generated_at": datetime.utcnow().isoformat(),
            "decision_threshold": settings.decision_threshold,
        }

        LOGGER.info("Persisting artefacts to %s ...", args.output_root)
        save_training_artifacts(
            model=model,
            output_dir=args.output_root,
            feature_columns=feature_columns,
            metadata=metadata,
        )

    LOGGER.info(
        "Stage 1 training complete: samples=%d positive_rate=%.4f",
        len(labels),
        metrics["positive_rate"],
    )
    LOGGER.info("Model path: %s", args.output_root / "model.pkl")


if __name__ == "__main__":
    main()

# Example CLI:
# python -m extensions.intraday_ml_models.train_bigmove_stage1 \
#   --dataset-config configs/extensions/intraday_ml/phaseA_sip_full.yaml \
#   --targets-config configs/extensions/intraday_ml/targets_bigmove.yaml \
#   --model-config configs/extensions/intraday_ml/model_bigmove_stage1.yaml \
#   --output-root artefacts/extensions/intraday_ml/bigmove_stage1
