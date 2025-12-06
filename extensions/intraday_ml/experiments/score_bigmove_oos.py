"""Score big-move models on frozen OOS features and merge with baseline signals."""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml

from extensions.intraday_ml.utils.heartbeat import HeartbeatLogger

# Default artefact locations for the Phase A SIP run.
DEFAULT_FEATURES_PATH = Path("artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet")
DEFAULT_BASELINE_SIGNALS_PATH = Path(
    "artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions.parquet"
)
DEFAULT_OUTPUT_PATH = Path(
    "artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet"
)
DEFAULT_EXPECTED_R_FLOOR = 1.0
DEFAULT_MODELS_CONFIG = Path("configs/extensions/intraday_ml/bigmove_models_config.yaml")

# Common filename fragments for the stage models. Used when auto-discovering artefacts.
DEFAULT_MODEL_SEARCH_ROOT = Path("artefacts/extensions/intraday_ml")
MODEL_PATTERNS = {
    "stage1": ("*bigmove*stage1*.pkl", "*stage1*bigmove*.pkl", "*stage1_prob*.pkl"),
    "stage2_direction": (
        "*bigmove*stage2_direction*.pkl",
        "*stage2_direction*bigmove*.pkl",
        "*direction_bigmove*.pkl",
    ),
    "stage2_expected_r": (
        "*bigmove*stage2_expected_r*.pkl",
        "*stage2_expected_r*bigmove*.pkl",
        "*expected_r_bigmove*.pkl",
    ),
}

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class StageModelSpec:
    """Configuration payload describing how to load a stage model."""

    name: str
    path: Path
    features: list[str] | None = None
    positive_labels: list[Any] | None = None
    long_label: Any | None = None
    short_label: Any | None = None
    feature_list_path: Path | None = None
    target_name: str | None = None


@dataclass(frozen=True)
class LoadedStageModel:
    """Materialised model plus metadata."""

    name: str
    path: Path
    model: Any
    features: list[str]
    positive_labels: list[Any] | None = None
    long_label: Any | None = None
    short_label: Any | None = None
    target_name: str | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score big-move models on OOS features and augment baseline signals."
    )
    parser.add_argument(
        "--features",
        type=Path,
        default=DEFAULT_FEATURES_PATH,
        help="Path to the OOS features parquet.",
    )
    parser.add_argument(
        "--baseline-signals",
        type=Path,
        default=DEFAULT_BASELINE_SIGNALS_PATH,
        help="Path to the existing baseline signals parquet.",
    )
    parser.add_argument(
        "--output-signals",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Destination path for the combined signals parquet.",
    )
    parser.add_argument(
        "--models-config",
        type=Path,
        default=DEFAULT_MODELS_CONFIG,
        help=(
            "Optional JSON/YAML file describing stage model artefacts. "
            "If omitted, the script attempts to auto-discover models under artefacts/extensions/intraday_ml."
        ),
    )
    parser.add_argument(
        "--expected-r-floor",
        type=float,
        default=DEFAULT_EXPECTED_R_FLOOR,
        help="Optional floor applied to expected-r predictions.",
    )
    return parser.parse_args()


def load_models_config(path: Path | None) -> dict[str, StageModelSpec]:
    """Return model specs from a config file or discovery fallback."""
    resolved_path = path
    if resolved_path and not resolved_path.exists() and resolved_path == DEFAULT_MODELS_CONFIG:
        LOGGER.info("Models config missing at default path; falling back to discovery.")
        resolved_path = None

    if resolved_path:
        LOGGER.info("Loading model configuration from %s", resolved_path)
        with open(resolved_path) as handle:
            if resolved_path.suffix.lower() in {".yaml", ".yml"}:
                raw = yaml.safe_load(handle) or {}
            else:
                raw = json.load(handle)
        specs = build_model_specs_from_dict(raw)
    else:
        LOGGER.info("No model config supplied. Attempting auto-discovery under %s", DEFAULT_MODEL_SEARCH_ROOT)
        specs = discover_model_specs(DEFAULT_MODEL_SEARCH_ROOT)

    if "stage1" not in specs or "stage2_direction" not in specs:
        raise RuntimeError(
            "Unable to discover required big-move models. "
            "Provide --models-config pointing at the stage artefacts."
        )
    return specs


def build_model_specs_from_dict(raw: dict[str, Any]) -> dict[str, StageModelSpec]:
    specs: dict[str, StageModelSpec] = {}
    for stage in ("stage1", "stage2_direction", "stage2_expected_r"):
        stage_cfg = raw.get(stage)
        if not stage_cfg:
            continue
        model_path = stage_cfg.get("path") or stage_cfg.get("model_path")
        if not model_path:
            raise ValueError(f"Stage '{stage}' is missing a 'path' entry.")
        features = stage_cfg.get("features")
        if features is not None and isinstance(features, (str, bytes)):
            raise ValueError(f"Stage '{stage}' features must be provided as a list, not a string.")
        if features is not None and not isinstance(features, Iterable):
            raise ValueError(f"Stage '{stage}' features must be an iterable of strings.")
        feature_list_path = stage_cfg.get("feature_list_path")
        if feature_list_path:
            feature_list_path = Path(feature_list_path)
        specs[stage] = StageModelSpec(
            name=stage,
            path=Path(model_path),
            features=[str(col) for col in features] if features else None,
            positive_labels=_normalize_iterable(stage_cfg.get("positive_labels")),
            long_label=stage_cfg.get("long_label"),
            short_label=stage_cfg.get("short_label"),
            feature_list_path=feature_list_path,
            target_name=stage_cfg.get("target_name"),
        )
    return specs


def _normalize_iterable(value: Any) -> list[Any] | None:
    if value is None:
        return None
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return [item for item in value]
    raise ValueError("Expected a list/iterable value.")


def discover_model_specs(root: Path) -> dict[str, StageModelSpec]:
    """Heuristically locate stage models under the artefacts directory."""
    specs: dict[str, StageModelSpec] = {}
    if not root.exists():
        return specs

    for stage, patterns in MODEL_PATTERNS.items():
        for pattern in patterns:
            matches = sorted(root.rglob(pattern))
            if matches:
                specs[stage] = StageModelSpec(name=stage, path=matches[0])
                break
    return specs


def load_stage_models(specs: dict[str, StageModelSpec]) -> dict[str, LoadedStageModel]:
    """Load the configured models and infer their feature lists."""
    loaded: dict[str, LoadedStageModel] = {}
    for name, spec in specs.items():
        LOGGER.info("Loading %s model from %s", name, spec.path)
        if not spec.path.exists():
            raise FileNotFoundError(f"Model file not found: {spec.path}")
        model = joblib.load(spec.path)
        features = spec.features or load_feature_list(spec.feature_list_path) or infer_feature_names(model)
        if not features:
            raise RuntimeError(
                f"Unable to infer feature columns for {name}. "
                "Provide them explicitly via --models-config."
            )
        loaded[name] = LoadedStageModel(
            name=name,
            path=spec.path,
            model=model,
            features=features,
            positive_labels=spec.positive_labels,
            long_label=spec.long_label,
            short_label=spec.short_label,
            target_name=spec.target_name,
        )
    return loaded


def load_feature_list(path: Path | None) -> list[str] | None:
    """Read ordered feature names from a text or JSON file."""

    if path is None:
        return None
    if not path.exists():
        raise FileNotFoundError(f"Feature list file not found: {path}")
    if path.suffix.lower() in {".json", ".js"}:
        with open(path) as handle:
            data = json.load(handle)
        if isinstance(data, list):
            return [str(item) for item in data]
        raise ValueError(f"Feature list JSON at {path} must contain an array.")
    with open(path) as handle:
        lines = [line.strip() for line in handle.readlines() if line.strip()]
    return lines


def infer_feature_names(model: Any) -> list[str]:
    """Extract the feature names recorded by the trained model."""
    for attr in ("feature_name_", "feature_names_in_"):
        names = getattr(model, attr, None)
        if isinstance(names, Iterable) and not isinstance(names, (str, bytes)):
            as_list = [str(item) for item in names if item]
            if as_list:
                return as_list

    booster = getattr(model, "booster_", None)
    if booster is not None and hasattr(booster, "feature_name"):
        names = booster.feature_name()
        if names:
            return [str(name) for name in names]

    if hasattr(model, "feature_name"):
        names = model.feature_name()
        if names:
            return [str(name) for name in names]

    return []


def score_bigmove_oos(
    features_path: Path,
    baseline_signals_path: Path,
    output_path: Path,
    model_config_path: Path | None = None,
    expected_r_floor: float = DEFAULT_EXPECTED_R_FLOOR,
) -> Path:
    """Entry point for CLI and tests."""
    df_features = load_parquet(features_path, frame_name="features")
    df_signals = load_parquet(baseline_signals_path, frame_name="baseline signals")

    ensure_columns(df_features, ["ts", "symbol"], frame_name="features")
    ensure_columns(df_signals, ["ts", "symbol"], frame_name="baseline signals")

    model_specs = load_models_config(model_config_path)
    loaded_models = load_stage_models(model_specs)

    bigmove_scores = build_bigmove_scores(df_features, loaded_models, expected_r_floor=expected_r_floor)
    combined = combine_signals(df_signals, bigmove_scores)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(output_path, index=False)
    LOGGER.info(
        "✅ Combined signals written to %s (%d rows, %d columns)",
        output_path,
        len(combined),
        len(combined.columns),
    )
    return output_path


def load_parquet(path: Path, *, frame_name: str) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"{frame_name.title()} file not found: {path}")
    LOGGER.info("Loading %s from %s", frame_name, path)
    return pd.read_parquet(path)


def ensure_columns(df: pd.DataFrame, columns: Iterable[str], *, frame_name: str) -> None:
    missing = [col for col in columns if col not in df.columns]
    if missing:
        raise KeyError(f"{frame_name.title()} frame is missing required columns: {missing}")


def build_bigmove_scores(
    df_features: pd.DataFrame,
    models: dict[str, LoadedStageModel],
    *,
    expected_r_floor: float = DEFAULT_EXPECTED_R_FLOOR,
) -> pd.DataFrame:
    """Run stage predictions and return a ts/symbol aligned DataFrame of scores."""
    indexed = df_features.reset_index(drop=True)
    base = indexed[["ts", "symbol"]].copy()
    base["ts"] = pd.to_datetime(base["ts"], utc=True)

    probability_model = models.get("stage1")
    direction_model = models.get("stage2_direction")
    if probability_model is None or direction_model is None:
        raise RuntimeError("Both stage1 and stage2_direction models are required.")

    prob_matrix = prepare_feature_matrix(indexed, probability_model.features, stage_name="stage1")
    prob_bigmove = predict_binary_probability(
        probability_model.model,
        prob_matrix,
        positive_labels=probability_model.positive_labels,
    )
    base["prob_bigmove"] = np.clip(prob_bigmove, 0.0, 1.0)
    log_series_stats("prob_bigmove", base["prob_bigmove"])

    direction_matrix = prepare_feature_matrix(indexed, direction_model.features, stage_name="stage2_direction")
    prob_short, prob_long = predict_direction_probabilities(
        direction_model.model,
        direction_matrix,
        long_label=direction_model.long_label,
        short_label=direction_model.short_label,
    )
    base["prob_bigmove_long"] = np.clip(prob_long, 0.0, 1.0)
    base["prob_bigmove_short"] = np.clip(prob_short, 0.0, 1.0)
    log_series_stats("prob_bigmove_long", base["prob_bigmove_long"])

    expected_r_model = models.get("stage2_expected_r")
    if expected_r_model:
        reg_matrix = prepare_feature_matrix(indexed, expected_r_model.features, stage_name="stage2_expected_r")
        expected_r = predict_regression(expected_r_model.model, reg_matrix)
        base["expected_r_bigmove"] = np.maximum(expected_r_floor, np.asarray(expected_r, dtype=float))
        log_series_stats("expected_r_bigmove", base["expected_r_bigmove"])

    return base


def prepare_feature_matrix(
    df: pd.DataFrame,
    feature_columns: Iterable[str],
    *,
    stage_name: str,
) -> pd.DataFrame:
    columns = list(feature_columns)
    missing = [col for col in columns if col not in df.columns]
    if missing:
        raise KeyError(f"{stage_name} features missing from OOS dataset: {missing[:8]}")

    subset = df[columns].copy()
    for column in subset.columns:
        subset[column] = pd.to_numeric(subset[column], errors="coerce")
    return subset.fillna(0.0)


def predict_binary_probability(
    model: Any,
    matrix: pd.DataFrame,
    *,
    positive_labels: list[Any] | None = None,
) -> np.ndarray:
    """Return probability of the positive class."""
    labels = positive_labels or [1]
    if hasattr(model, "predict_proba"):
        proba = np.asarray(model.predict_proba(matrix), dtype=float)
        if proba.ndim == 1:
            if len(labels) != 1:
                raise ValueError("Single-column probabilities require exactly one positive label.")
            return proba
        result = np.zeros(proba.shape[0], dtype=float)
        for label in labels:
            idx = resolve_class_index(model, label=label)
            result += proba[:, idx]
        return result

    if hasattr(model, "predict"):
        preds = np.asarray(model.predict(matrix), dtype=float)
        if preds.ndim == 2:
            result = np.zeros(preds.shape[0], dtype=float)
            for label in labels:
                idx = resolve_class_index(model, label=label, default_index=-1)
                result += preds[:, idx]
            return result
        return preds

    raise AttributeError("Provided model lacks predict/predict_proba methods.")


def predict_direction_probabilities(
    model: Any,
    matrix: pd.DataFrame,
    *,
    long_label: Any | None = None,
    short_label: Any | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (prob_short, prob_long) from the direction model."""
    if hasattr(model, "predict_proba"):
        proba = np.asarray(model.predict_proba(matrix), dtype=float)
    elif hasattr(model, "predict"):
        proba = np.asarray(model.predict(matrix), dtype=float)
    else:
        raise AttributeError("Stage 2 direction model must expose predict or predict_proba.")

    if proba.ndim == 1:
        prob_long = proba
        prob_short = 1.0 - prob_long
        return prob_short, prob_long

    long_idx = resolve_class_index(model, label=long_label if long_label is not None else 1)
    short_idx = resolve_class_index(model, label=short_label if short_label is not None else 0, default_index=0)
    prob_long = proba[:, long_idx]
    prob_short = proba[:, short_idx]
    return prob_short, prob_long


def predict_regression(model: Any, matrix: pd.DataFrame) -> np.ndarray:
    if not hasattr(model, "predict"):
        raise AttributeError("Expected-R model must expose predict().")
    values = model.predict(matrix)
    if isinstance(values, pd.Series):
        return values.to_numpy(dtype=float)
    return np.asarray(values, dtype=float)


def resolve_class_index(model: Any, *, label: Any, default_index: int = -1) -> int:
    classes = getattr(model, "classes_", None)
    if classes is not None and len(classes) > 0:
        for idx, value in enumerate(classes):
            if value == label:
                return idx
    if default_index >= 0:
        return default_index
    if classes is not None and len(classes) > 0:
        return max(len(classes) - 1, 0)
    return 0


def combine_signals(baseline: pd.DataFrame, bigmove_scores: pd.DataFrame) -> pd.DataFrame:
    """Inner-join the baseline signals with the big-move columns."""
    key = ["ts", "symbol"]
    merged = pd.merge(
        baseline,
        bigmove_scores,
        on=key,
        how="inner",
        validate="one_to_one",
        suffixes=("", "_bigmove"),
    )
    dropped_baseline = len(baseline) - len(merged)
    dropped_features = len(bigmove_scores) - len(merged)
    if dropped_baseline:
        LOGGER.warning("Dropped %d baseline rows with no big-move matches.", dropped_baseline)
    if dropped_features:
        LOGGER.warning("Dropped %d big-move rows with no baseline matches.", dropped_features)
    return merged


def log_series_stats(name: str, series: pd.Series) -> None:
    clean = pd.to_numeric(series, errors="coerce")
    clean = clean.replace([np.inf, -np.inf], np.nan).dropna()
    if clean.empty:
        LOGGER.warning("%s contains no finite values.", name)
        return
    LOGGER.info(
        "%s stats -> rows=%d min=%.4f max=%.4f mean=%.4f std=%.4f",
        name,
        len(clean),
        float(clean.min()),
        float(clean.max()),
        float(clean.mean()),
        float(clean.std(ddof=0)),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    args = parse_args()
    with HeartbeatLogger("score_bigmove_oos", interval_seconds=60):
        score_bigmove_oos(
            args.features,
            args.baseline_signals,
            args.output_signals,
            args.models_config,
            expected_r_floor=args.expected_r_floor,
        )


if __name__ == "__main__":
    main()
