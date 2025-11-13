"""CLI for Bayesian LightGBM tuning with trading-aware CV metrics."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml

from extensions.intraday_ml_models.tune_lgbm import BayesianLightGBMTuner


def _load_yaml(path: Path) -> dict:
    with open(path) as handle:
        return yaml.safe_load(handle)


def _resolve_dataset_path(master_config: dict, override: str | None) -> Path:
    if override:
        return Path(override)
    artifacts_root = master_config.get("artifacts", "artefacts/extensions/intraday_ml/phaseA")
    return Path(artifacts_root) / "training_data.parquet"


def _prepare_data(dataset_path: Path) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame | None]:
    df = pd.read_parquet(dataset_path)
    if "symbol" not in df.columns or "ts" not in df.columns:
        raise ValueError("Dataset must include 'symbol' and 'ts' columns.")
    df = df.set_index(["symbol", "ts"])
    feature_columns = [col for col in df.columns if col.startswith("f__")]
    if not feature_columns:
        raise ValueError("Dataset does not contain feature columns prefixed with 'f__'.")
    if "label" not in df.columns:
        raise ValueError("Dataset missing 'label' column.")
    features = df[feature_columns]
    labels = df["label"]
    context_columns = [
        col for col in ["open", "high", "low", "close", "volume"] if col in df.columns
    ]
    context = df[context_columns] if context_columns else None
    return features, labels, context


def main() -> int:
    parser = argparse.ArgumentParser(description="Bayesian LightGBM tuning CLI.")
    parser.add_argument("--config", required=True, help="Master Phase-A config.")
    parser.add_argument(
        "--dataset",
        help="Path to training dataset parquet (defaults to artefacts/.../training_data.parquet).",
    )
    parser.add_argument(
        "--objective-config",
        default="configs/extensions/intraday_ml/tuning/objective_pnl.yaml",
        help="Objective configuration YAML.",
    )
    parser.add_argument(
        "--output-dir",
        default="artefacts/extensions/intraday_ml/tuning",
        help="Directory to store tuning outputs.",
    )

    args = parser.parse_args()

    master_config = _load_yaml(Path(args.config))
    includes = master_config.get("includes", {})
    if not includes:
        raise ValueError("Master config must define includes for model/cv.")

    model_config = _load_yaml(Path(includes["model"]))
    cv_config = _load_yaml(Path(includes["cv"]))
    objective_config = _load_yaml(Path(args.objective_config))

    dataset_path = _resolve_dataset_path(master_config, args.dataset)
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    print(f"[tuner] Loading dataset: {dataset_path}")
    features, labels, context = _prepare_data(dataset_path)

    tuner = BayesianLightGBMTuner(model_config, cv_config, objective_config)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("[tuner] Starting optimization...")
    tuner.optimize(
        features=features,
        labels=labels,
        output_dir=output_dir,
        context_data=context,
    )
    print(f"[tuner] Results saved under {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
