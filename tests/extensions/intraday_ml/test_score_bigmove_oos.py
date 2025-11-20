"""Tests for score_bigmove_oos wiring with models config."""

from __future__ import annotations

from pathlib import Path

import joblib
import json
import numpy as np
import pandas as pd
import yaml

from extensions.intraday_ml.experiments.score_bigmove_oos import score_bigmove_oos


class DummyBinaryModel:
    def __init__(self, proba: tuple[float, float]):
        self.proba = np.asarray(proba, dtype=float)
        self.classes_ = np.array([0, 1])

    def predict_proba(self, matrix: pd.DataFrame) -> np.ndarray:
        rows = len(matrix)
        tiled = np.tile(self.proba, (rows, 1))
        return tiled


def _write_parquet(df: pd.DataFrame, path: Path) -> Path:
    df.to_parquet(path)
    return path


def test_score_bigmove_oos_uses_models_config(tmp_path: Path) -> None:
    features_df = pd.DataFrame(
        {
            "ts": pd.date_range("2024-01-02", periods=3, freq="T"),
            "symbol": ["AAA", "AAA", "AAA"],
            "f__alpha": [0.1, 0.2, 0.3],
            "f__beta": [1.0, 1.1, 1.2],
        }
    )
    baseline_df = pd.DataFrame(
        {
            "ts": features_df["ts"],
            "symbol": features_df["symbol"],
            "prob_short": [0.2, 0.2, 0.2],
            "prob_neutral": [0.5, 0.5, 0.5],
            "prob_long": [0.3, 0.3, 0.3],
        }
    )
    baseline_df["ts"] = pd.to_datetime(baseline_df["ts"], utc=True)

    features_path = _write_parquet(features_df, tmp_path / "features.parquet")
    baseline_path = _write_parquet(baseline_df, tmp_path / "baseline.parquet")

    stage1_model = DummyBinaryModel((0.65, 0.35))
    stage2_model = DummyBinaryModel((0.3, 0.7))
    stage1_path = tmp_path / "stage1.pkl"
    stage2_path = tmp_path / "stage2.pkl"
    joblib.dump(stage1_model, stage1_path)
    joblib.dump(stage2_model, stage2_path)

    feature_list_path = tmp_path / "features.json"
    feature_list_path.write_text(json.dumps(["f__alpha", "f__beta"]))

    models_cfg = {
        "stage1": {
            "model_path": str(stage1_path),
            "feature_list_path": str(feature_list_path),
            "positive_labels": [1],
        },
        "stage2_direction": {
            "model_path": str(stage2_path),
            "feature_list_path": str(feature_list_path),
            "long_label": 1,
            "short_label": 0,
        },
    }
    models_cfg_path = tmp_path / "models.yaml"
    models_cfg_path.write_text(yaml.safe_dump(models_cfg))

    output_path = tmp_path / "signals.parquet"

    score_bigmove_oos(
        features_path,
        baseline_path,
        output_path,
        model_config_path=models_cfg_path,
        expected_r_floor=1.0,
    )

    scored = pd.read_parquet(output_path)
    assert {"prob_bigmove", "prob_bigmove_long"}.issubset(scored.columns)
    assert np.allclose(scored["prob_bigmove"], 0.35)
    assert np.allclose(scored["prob_bigmove_long"], 0.7)
    # Ensure baseline columns survived the merge
    assert np.allclose(scored["prob_long"], 0.3)
