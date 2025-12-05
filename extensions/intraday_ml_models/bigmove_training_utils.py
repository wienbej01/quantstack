"""Shared helpers for big-move model training scripts."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml  # type: ignore[import-untyped]
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
    roc_auc_score,
)
from sklearn.model_selection import StratifiedKFold
from sklearn.utils.class_weight import compute_class_weight

from extensions.intraday_ml.data_prep import create_training_dataset
from extensions.intraday_ml.labeling.big_move_labels import (
    BigMoveLabelConfig,
    compute_big_move_labels,
)
from extensions.intraday_ml.sip_membership import get_phase_symbols_with_sip
from extensions.intraday_ml.utils.checksums import compute_data_hash

DEFAULT_BUFFER_DAYS = 5
MIN_CLASSES_REQUIRED = 2
MIN_CV_FOLDS = 2

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class TrainingSettings:
    """Configuration knob subset shared by Stage 1/2 scripts."""

    seed: int = 17
    n_folds: int = 5
    decision_threshold: float = 0.5
    class_weight: dict[int, float] | str | None = None


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file into a dictionary with helpful errors."""

    with open(path) as handle:
        data = yaml.safe_load(handle) or {}
    return data


def resolve_include_path(master_path: Path, include_value: str) -> Path:
    """Resolve include paths relative to repo root or master config."""

    candidate = Path(include_value)
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    if candidate.exists():
        return candidate

    fallback = (master_path.parent / include_value).resolve()
    if fallback.exists():
        return fallback

    raise FileNotFoundError(f"Unable to resolve include path '{include_value}'.")


def load_master_and_includes(
    config_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load the master Phase-A config plus its includes."""

    master_config = load_yaml(config_path)
    includes_cfg: dict[str, Any] = {}
    includes = master_config.get("includes", {}) or {}
    for name, include_path in includes.items():
        resolved = resolve_include_path(config_path, include_path)
        includes_cfg[name] = load_yaml(resolved)
    if not includes_cfg:
        raise ValueError("Master config must declare at least one include block.")
    return master_config, includes_cfg


def _ensure_candidate_symbols(includes: dict[str, Any]) -> list[str]:
    universe_cfg = includes.get("universe") or {}
    symbols = universe_cfg.get("symbols") or []
    if not symbols:
        raise ValueError("Universe config must contain a non-empty 'symbols' list.")
    return [str(symbol).upper() for symbol in symbols]


def build_split_dataset(
    *,
    master_config: dict[str, Any],
    includes: dict[str, Any],
    targets_config: dict[str, Any],
    split: str,
    label_buffer_days: int | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Build a dataset for the requested split mirroring Phase-A behavior."""

    splits_cfg = includes.get("splits") or {}
    if split not in splits_cfg:
        raise ValueError(f"Split '{split}' not present in splits configuration.")

    split_info = splits_cfg[split]
    start_date = str(split_info.get("start"))
    end_date = str(split_info.get("end"))
    if not start_date or not end_date:
        raise ValueError(f"Split '{split}' must define start/end dates.")

    buffer_days = label_buffer_days
    if buffer_days is None:
        buffer_days = int(master_config.get("label_buffer_days", DEFAULT_BUFFER_DAYS))
    buffer_days = max(buffer_days, 0)

    end_buffer = (
        datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=buffer_days)
    ).strftime("%Y-%m-%d")

    sip_config = master_config.get("sip_filter", {"enabled": False}) or {
        "enabled": False
    }
    candidate_symbols = _ensure_candidate_symbols(includes)
    resolved_symbols = get_phase_symbols_with_sip(
        splits_config=splits_cfg,
        sip_config=sip_config,
        candidate_symbols=candidate_symbols,
        phase=split,
        verbose=False,
    )
    if not resolved_symbols:
        raise RuntimeError(
            f"No symbols available for split '{split}' after SIP filtering."
        )

    loader_config = dict(master_config.get("data", {}) or {})
    loader_config.setdefault("dataset_kind", split)

    dataset = create_training_dataset(
        symbols=resolved_symbols,
        start_date=start_date,
        end_date=end_buffer,
        features_config=includes.get("features"),
        targets_config=targets_config,
        data_loader_config=loader_config,
        include_ohlcv=True,
    )
    if dataset.empty:
        raise RuntimeError(
            "Training dataset is empty; check data availability and symbols."
        )

    dataset = trim_dataset_to_window(dataset, start_date, end_date)
    return dataset, {
        "start_date": start_date,
        "end_date": end_date,
        "symbols": len(resolved_symbols),
    }


def trim_dataset_to_window(
    dataset: pd.DataFrame, start_date: str, end_date: str
) -> pd.DataFrame:
    """Trim dataset rows to the [start, end] inclusive interval."""

    timestamps = pd.to_datetime(dataset["ts"], errors="coerce")
    if timestamps.isna().any():
        raise ValueError("Dataset contains malformed timestamps after loading.")
    mask = (timestamps >= pd.to_datetime(start_date)) & (
        timestamps
        <= pd.to_datetime(end_date) + timedelta(days=1) - timedelta(seconds=1)
    )
    trimmed = dataset.loc[mask].copy()
    trimmed["ts"] = timestamps.loc[mask]
    if trimmed.empty:
        raise RuntimeError("Dataset is empty after trimming to requested window.")
    return trimmed.reset_index(drop=True)


def attach_bigmove_labels(
    dataset: pd.DataFrame,
    targets_config: dict[str, Any],
) -> tuple[pd.DataFrame, BigMoveLabelConfig]:
    """Compute and append big-move labels to the dataset."""

    config = BigMoveLabelConfig.from_targets_config(targets_config)
    required_columns = {"symbol", "ts", config.price_column, config.atr_column}
    missing = required_columns - set(dataset.columns)
    if missing:
        raise KeyError(
            "Dataset missing required columns for big-move labels: "
            + ", ".join(sorted(missing))
        )

    # Check for duplicates and deduplicate if needed
    dup_count = dataset.duplicated(subset=["symbol", "ts"]).sum()
    if dup_count > 0:
        LOGGER.warning(
            "Found %d duplicate (symbol, ts) pairs in dataset, keeping first occurrence",
            dup_count,
        )
        dataset = dataset.drop_duplicates(subset=["symbol", "ts"], keep="first")

    working = dataset[list(required_columns)].copy()
    working["ts"] = pd.to_datetime(working["ts"], errors="coerce")
    if working["ts"].isna().any():
        raise ValueError("Unable to parse timestamps while computing big-move labels.")

    working = working.sort_values(["symbol", "ts"]).reset_index(drop=True)
    result = compute_big_move_labels(working, targets_config)

    enriched = working[["symbol", "ts"]].copy()
    enriched[config.label_name] = result.labels.to_numpy(dtype=int, copy=False)
    enriched[config.direction_label_name] = result.directions.to_numpy(
        dtype=int, copy=False
    )
    enriched[config.forward_return_column] = result.forward_returns.to_numpy(copy=False)

    merged = dataset.merge(
        enriched, on=["symbol", "ts"], how="left", validate="one_to_one"
    )
    return merged, config


def select_feature_columns(dataset: pd.DataFrame) -> list[str]:
    """Return ordered feature columns (prefixed with f__)."""

    features = [col for col in dataset.columns if col.startswith("f__")]
    if not features:
        raise ValueError("Dataset contains no feature columns (expected prefix 'f__').")
    return sorted(features)


def prepare_feature_matrix(
    dataset: pd.DataFrame, feature_columns: list[str]
) -> pd.DataFrame:
    """Subset and coerce the feature matrix to numeric values."""

    matrix = dataset[feature_columns].copy()
    for column in matrix.columns:
        matrix[column] = pd.to_numeric(matrix[column], errors="coerce")
    return matrix.fillna(0.0)


def compute_hashes(features: pd.DataFrame, labels: pd.Series) -> tuple[str, str]:
    """Compute deterministic hashes for features and labels."""

    features_hash = compute_data_hash(features)
    targets_hash = compute_data_hash(labels)
    return features_hash, targets_hash


def train_binary_model(
    features: pd.DataFrame,
    labels: pd.Series,
    *,
    params: dict[str, Any],
    settings: TrainingSettings,
) -> tuple[lgb.LGBMClassifier, dict[str, Any], dict[str, Any]]:
    """Train a LightGBM binary classifier with optional CV metrics."""

    if labels.nunique() < MIN_CLASSES_REQUIRED:
        raise ValueError("Training labels must contain at least two classes.")

    training_params = params.copy()
    training_params.setdefault("objective", "binary")
    training_params.setdefault("random_state", settings.seed)
    training_params.setdefault("n_jobs", -1)
    training_params.pop("class_weight", None)

    sample_weights = build_sample_weights(labels, settings.class_weight)

    cv_result = run_cross_validation(
        features,
        labels,
        params=training_params,
        settings=settings,
        sample_weights=sample_weights,
    )

    model = lgb.LGBMClassifier(**training_params)
    model.fit(features, labels, sample_weight=sample_weights)
    probabilities = model.predict_proba(features)[:, 1]
    metrics = compute_binary_metrics(
        labels, probabilities, threshold=settings.decision_threshold
    )
    return model, metrics, cv_result


def run_cross_validation(
    features: pd.DataFrame,
    labels: pd.Series,
    *,
    params: dict[str, Any],
    settings: TrainingSettings,
    sample_weights: np.ndarray | None = None,
) -> dict[str, Any]:
    """Execute stratified CV when feasible."""

    if labels.nunique() < MIN_CLASSES_REQUIRED:
        return {"enabled": False, "folds": 0, "fold_metrics": [], "summary": {}}

    min_class = labels.value_counts().min()
    folds = min(settings.n_folds, int(min_class))
    if folds < MIN_CV_FOLDS:
        return {"enabled": False, "folds": 0, "fold_metrics": [], "summary": {}}

    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=settings.seed)
    fold_metrics: list[dict[str, Any]] = []
    metric_keys = ["roc_auc", "precision", "recall", "f1", "accuracy"]
    aggregates: dict[str, list[float]] = {key: [] for key in metric_keys}

    for fold_id, (train_idx, val_idx) in enumerate(
        splitter.split(features, labels), start=1
    ):
        cv_params = params.copy()
        model = lgb.LGBMClassifier(**cv_params)
        fold_weights = sample_weights[train_idx] if sample_weights is not None else None
        model.fit(
            features.iloc[train_idx], labels.iloc[train_idx], sample_weight=fold_weights
        )
        probabilities = model.predict_proba(features.iloc[val_idx])[:, 1]
        metrics = compute_binary_metrics(
            labels.iloc[val_idx],
            probabilities,
            threshold=settings.decision_threshold,
        )
        fold_metrics.append(
            {"fold": fold_id, "samples": int(len(val_idx)), "metrics": metrics}
        )
        for key in metric_keys:
            value = metrics.get(key)
            if value is not None:
                aggregates[key].append(float(value))

    summary = {
        key: {
            "mean": float(np.mean(values)) if values else None,
            "std": float(np.std(values)) if values else None,
        }
        for key, values in aggregates.items()
    }
    return {
        "enabled": True,
        "folds": folds,
        "fold_metrics": fold_metrics,
        "summary": summary,
    }


def compute_binary_metrics(
    y_true: pd.Series,
    probabilities: np.ndarray,
    *,
    threshold: float,
) -> dict[str, Any]:
    """Return standard binary classification metrics."""

    y_array = y_true.to_numpy(dtype=int, copy=False)
    probs = np.asarray(probabilities, dtype=float)
    preds = (probs >= threshold).astype(int)

    precision, recall, f1, support = precision_recall_fscore_support(
        y_array,
        preds,
        labels=[0, 1],
        zero_division=0,
    )
    tn, fp, fn, tp = confusion_matrix(y_array, preds, labels=[0, 1]).ravel()
    metrics: dict[str, Any] = {
        "accuracy": float(accuracy_score(y_array, preds)),
        "precision": float(precision[1]),
        "recall": float(recall[1]),
        "f1": float(f1[1]),
        "positive_rate": float(np.mean(y_array)),
        "confusion_matrix": {
            "tn": int(tn),
            "fp": int(fp),
            "fn": int(fn),
            "tp": int(tp),
        },
        "per_class": {
            "neg": {
                "precision": float(precision[0]),
                "recall": float(recall[0]),
                "support": int(support[0]),
            },
            "pos": {
                "precision": float(precision[1]),
                "recall": float(recall[1]),
                "support": int(support[1]),
            },
        },
        "threshold": float(threshold),
    }
    if len(np.unique(y_array)) > 1:
        metrics["roc_auc"] = float(roc_auc_score(y_array, probs))
    return metrics


def build_sample_weights(
    labels: pd.Series, class_weight: dict[int, float] | str | None
) -> np.ndarray | None:
    """Return per-sample weights mirroring sklearn/lightgbm semantics."""

    if class_weight is None:
        return None

    y = labels.to_numpy(dtype=int, copy=False)
    if isinstance(class_weight, str):
        mode = class_weight.lower()
        if mode != "balanced":
            raise ValueError(f"Unsupported class weight mode '{class_weight}'.")
        classes = np.unique(y)
        weights = compute_class_weight(class_weight="balanced", classes=classes, y=y)
        mapping = {
            int(cls): float(weight)
            for cls, weight in zip(classes, weights, strict=False)
        }
    elif isinstance(class_weight, dict):
        mapping = {int(cls): float(weight) for cls, weight in class_weight.items()}
    else:
        raise TypeError("class_weight must be a dict, 'balanced', or None.")

    default_weight = 1.0
    vector = np.array(
        [mapping.get(int(label), default_weight) for label in y], dtype=float
    )
    return vector


def save_training_artifacts(
    *,
    model: lgb.LGBMClassifier,
    output_dir: Path,
    feature_columns: list[str],
    metadata: dict[str, Any],
    model_filename: str = "model.pkl",
    features_filename: str = "features.json",
    metadata_filename: str = "train_meta.json",
) -> None:
    """Persist trained model, feature list, and metadata."""

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / model_filename
    joblib.dump(model, model_path)

    features_path = output_dir / features_filename
    with open(features_path, "w") as handle:
        json.dump(feature_columns, handle, indent=2)

    meta_path = output_dir / metadata_filename
    with open(meta_path, "w") as handle:
        json.dump(metadata, handle, indent=2, default=str)


__all__ = [
    "TrainingSettings",
    "attach_bigmove_labels",
    "build_split_dataset",
    "compute_binary_metrics",
    "compute_hashes",
    "load_master_and_includes",
    "load_yaml",
    "prepare_feature_matrix",
    "run_cross_validation",
    "save_training_artifacts",
    "select_feature_columns",
    "train_binary_model",
    "trim_dataset_to_window",
]
