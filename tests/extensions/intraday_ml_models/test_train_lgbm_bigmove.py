import numpy as np
import pandas as pd
import pytest

from extensions.intraday_ml_models.train_lgbm_bigmove import BigMoveModelTrainer


def _synth_data(sample_count: int = 80) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(123)
    features = pd.DataFrame(
        {
            "feat_close": rng.normal(loc=0.0, scale=1.0, size=sample_count),
            "feat_gap": rng.normal(loc=0.5, scale=0.25, size=sample_count),
            "feat_conv": rng.uniform(0, 1, size=sample_count),
        }
    )
    big_move = (np.arange(sample_count) % 3 == 0).astype(int)
    direction = np.zeros(sample_count, dtype=int)
    mask = big_move == 1
    direction[mask] = np.where(rng.random(mask.sum()) > 0.4, 1, -1)
    realized_r = rng.normal(loc=1.2, scale=0.6, size=sample_count)
    realized_r[big_move == 0] = 0.0

    labels = pd.DataFrame(
        {
            "y_bigmove": big_move,
            "y_bigmove_direction": direction,
            "realized_r_bigmove": realized_r,
        }
    )
    return features, labels


def test_trainer_runs_all_stages_and_reports_metrics():
    features, labels = _synth_data()
    trainer = BigMoveModelTrainer(
        {
            "random_state": 7,
            "stage1": {"lgbm_params": {"n_estimators": 32}},
            "stage2_direction": {"lgbm_params": {"n_estimators": 32}},
            "stage2_expected_r": {"lgbm_params": {"n_estimators": 32}},
            "regression": {"winsorize": {"floor": -2.0, "cap": 4.0}},
        }
    )
    results = trainer.train_all_stages(features, labels)

    assert set(results) == {"stage1", "stage2_direction", "stage2_expected_r"}
    assert "roc_auc" in results["stage1"].metrics
    assert "accuracy" in results["stage2_direction"].metrics
    assert results["stage2_expected_r"].metrics["mae"] >= 0.0


def test_missing_required_label_column_raises():
    features, labels = _synth_data()
    trainer = BigMoveModelTrainer()
    labels = labels.drop(columns=["y_bigmove"])
    with pytest.raises(KeyError):
        trainer.train_stage1_probability(features, labels)
