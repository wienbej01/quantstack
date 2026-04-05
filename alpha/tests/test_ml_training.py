"""Tests for Sprint 3: XGBoost Training."""

import json
import numpy as np
import pandas as pd
import pytest

from scripts.train_ml_model import (
    _align_training_rows_to_live_scoring,
    _augment_training_context_features,
    _apply_training_balance_weights,
    _build_training_dataframe_from_compact_cache,
    _derive_executable_edge_labels,
    _evaluate_test_accuracy,
    _select_training_universe,
)
from src.data.ml_labels import walk_forward_folds
from src.data.ml_labels import WalkForwardFold
from src.features.ml_features import get_side_aware_context_columns
from src.models.xgb_trainer import (
    MulticlassIsotonicCalibrator,
    QualityGate,
    select_confidence_threshold,
    TrainingResult,
    quality_gate_failures,
    load_model,
    resolve_training_folds,
    save_model,
    train_walk_forward,
)
from src.models.two_stage_trainer import train_two_stage_walk_forward
from src.models.two_stage_trainer import train_two_stage_xgb_walk_forward


def _make_training_data(n_dates: int = 10, n_per_date: int = 500) -> tuple:
    """Create synthetic labeled dataset for training tests."""
    rng = np.random.RandomState(42)
    dates = [f"2025-12-{d:02d}" for d in range(1, n_dates + 1)]
    frames = []
    for d in dates:
        feat1 = rng.randn(n_per_date)
        feat2 = rng.randn(n_per_date)
        feat3 = rng.randn(n_per_date)
        score = feat1 * 0.5 + feat2 * 0.3 + rng.randn(n_per_date) * 0.5
        labels = np.digitize(score, bins=[-0.3, 0.3]).astype(float)
        frames.append(
            pd.DataFrame(
                {
                    "date": d,
                    "f1": feat1,
                    "f2": feat2,
                    "f3": feat3,
                    "label_180s": labels,
                }
            )
        )
    df = pd.concat(frames, ignore_index=True)
    feature_cols = ["f1", "f2", "f3"]
    folds = walk_forward_folds(dates, n_folds=3, min_train=3)
    return df, feature_cols, folds


class TestTrainWalkForward:
    def test_returns_training_result(self):
        df, feat_cols, folds = _make_training_data()
        result = train_walk_forward(df, feat_cols, "label_180s", folds)
        assert isinstance(result, TrainingResult)
        assert len(result.fold_results) > 0

    def test_val_accuracy_above_random(self):
        df, feat_cols, folds = _make_training_data()
        result = train_walk_forward(df, feat_cols, "label_180s", folds)
        assert result.mean_val_acc > 0.35

    def test_train_val_gap_reasonable(self):
        df, feat_cols, folds = _make_training_data()
        result = train_walk_forward(df, feat_cols, "label_180s", folds)
        assert result.train_val_gap < 0.30

    def test_feature_importance_sums_to_one(self):
        df, feat_cols, folds = _make_training_data()
        result = train_walk_forward(df, feat_cols, "label_180s", folds)
        imp = result.fold_results[0].feature_importance
        total = sum(imp.values())
        assert abs(total - 1.0) < 0.01

    def test_predictions_are_valid_classes(self):
        df, feat_cols, folds = _make_training_data()
        result = train_walk_forward(df, feat_cols, "label_180s", folds)
        X = df[feat_cols].values[:10]
        preds = result.best_model.predict(X)
        assert all(p in (0, 1, 2) for p in preds)

    def test_probabilities_sum_to_one(self):
        df, feat_cols, folds = _make_training_data()
        result = train_walk_forward(df, feat_cols, "label_180s", folds)
        X = df[feat_cols].values[:10]
        proba = result.best_model.predict_proba(X)
        for row in proba:
            assert abs(sum(row) - 1.0) < 0.01

    def test_two_stage_logistic_returns_valid_multiclass_probabilities(self):
        df, feat_cols, folds = _make_training_data()
        weights = np.ones(len(df), dtype=float)
        result = train_two_stage_walk_forward(
            df,
            feat_cols,
            feat_cols[:2],
            feat_cols[1:],
            "label_180s",
            folds,
            sample_weights=weights,
        )
        assert result.model_family == "two_stage_logistic"
        proba = result.best_model.predict_proba(df[feat_cols].values[:10])
        assert proba.shape == (10, 3)
        np.testing.assert_allclose(proba.sum(axis=1), np.ones(10), atol=1e-6)

    def test_two_stage_xgb_returns_valid_multiclass_probabilities(self):
        df, feat_cols, folds = _make_training_data()
        weights = np.ones(len(df), dtype=float)
        result = train_two_stage_xgb_walk_forward(
            df,
            feat_cols,
            feat_cols[:2],
            feat_cols[1:],
            "label_180s",
            folds,
            sample_weights=weights,
        )
        assert result.model_family == "two_stage_xgb"
        proba = result.best_model.predict_proba(df[feat_cols].values[:10])
        assert proba.shape == (10, 3)
        np.testing.assert_allclose(proba.sum(axis=1), np.ones(10), atol=1e-6)


class TestSaveLoad:
    def test_round_trip(self, tmp_path):
        df, feat_cols, folds = _make_training_data()
        result = train_walk_forward(df, feat_cols, "label_180s", folds)
        calibrator = MulticlassIsotonicCalibrator().fit(
            result.best_model.predict_proba(df[feat_cols].values[:50]),
            df["label_180s"].values[:50].astype(int),
        )
        result.calibrator = calibrator
        result.recommended_threshold = 0.45
        result.threshold_selection = [{"threshold": 0.45, "trigger_count": 10}]
        path = str(tmp_path / "model.pkl")
        save_model(result, path)
        loaded = load_model(path)
        assert "model" in loaded
        assert loaded["feature_columns"] == feat_cols
        assert loaded["calibrator"] is not None
        assert loaded["recommended_threshold"] == pytest.approx(0.45)
        assert loaded["threshold_selection"] == [
            {"threshold": 0.45, "trigger_count": 10}
        ]
        X = df[feat_cols].values[:5]
        orig_pred = result.best_model.predict(X)
        load_pred = loaded["model"].predict(X)
        np.testing.assert_array_equal(orig_pred, load_pred)


class TestFoldResolution:
    def test_falls_back_to_temporal_holdout_when_walk_forward_is_too_small(self):
        df, feat_cols, folds = _make_training_data(n_dates=4, n_per_date=60)
        walk_forward = [WalkForwardFold(0, ["2025-12-01"], ["2025-12-02"])]
        fallback = [WalkForwardFold(0, ["2025-12-01", "2025-12-02"], ["2025-12-03"])]
        resolved, strategy = resolve_training_folds(
            df, "label_180s", walk_forward, fallback
        )
        assert strategy == "temporal_holdout"
        assert resolved == fallback


class TestQualityGate:
    def test_quality_gate_flags_overfit_temporal_holdout_model(self):
        df, feat_cols, folds = _make_training_data()
        result = train_walk_forward(df, feat_cols, "label_180s", folds)
        gate = QualityGate(
            min_val_accuracy=0.99,
            max_train_val_gap=0.01,
            min_test_accuracy=0.99,
            require_walk_forward=True,
            min_folds=10,
        )
        failures = quality_gate_failures(
            result,
            fold_strategy="temporal_holdout",
            gate=gate,
            test_accuracy=0.20,
        )
        assert failures
        assert any("expected walk_forward" in failure for failure in failures)


class TestTrainingScriptHelpers:
    def test_align_training_rows_to_live_scoring_keeps_last_snapshot_per_bucket(self):
        df = pd.DataFrame(
            {
                "symbol": ["AAA", "AAA", "AAA"],
                "date": ["2026-03-10", "2026-03-10", "2026-03-10"],
                "ts_utc": pd.to_datetime(
                    [
                        "2026-03-10 14:30:05+00:00",
                        "2026-03-10 14:30:45+00:00",
                        "2026-03-10 14:31:10+00:00",
                    ],
                    utc=True,
                ),
                "session_bucket": [0.0, 0.0, 0.0],
                "label_180s": [1.0, 1.0, 2.0],
                "f1": [1.0, 2.0, 3.0],
            }
        )

        aligned = _align_training_rows_to_live_scoring(df, bucket_seconds=60)

        assert len(aligned) == 2
        assert aligned["f1"].tolist() == [2.0, 3.0]

    def test_select_training_universe_excludes_holdout_symbols(self):
        df, _, _ = _make_training_data()
        test_df = df.copy()
        symbols = np.array(["A", "B", "C", "A", "B"])
        repeats = int(np.ceil(len(test_df) / len(symbols)))
        test_df["symbol"] = np.tile(symbols, repeats)[: len(test_df)]
        info = type(
            "SplitInfoStub",
            (),
            {
                "train_symbols": ["A", "B"],
                "holdout_symbols": ["C"],
                "test_dates": ["2025-12-10"],
            },
        )()
        selected = _select_training_universe(test_df, info)
        assert set(selected["symbol"].unique()) == {"A", "B"}

    def test_derive_executable_edge_labels_uses_cost_floor(self):
        df = pd.DataFrame(
            {
                "ret_fwd_60s": [-0.0020, -0.0005, 0.0, 0.0008, 0.0020],
                "spread": [0.01] * 5,
                "mid": [50.0] * 5,
                "session_bucket": [1.0] * 5,
                "source_type": ["features"] * 5,
            }
        )
        labeled, label_col = _derive_executable_edge_labels(
            df,
            horizon=60,
            edge_bps=10.0,
            spread_weight=0.0,
            open_penalty_bps=0.0,
            raw_penalty_bps=0.0,
        )
        assert label_col == "label_exec_edge_60s"
        assert labeled[label_col].tolist() == [0.0, 1.0, 1.0, 1.0, 2.0]

    def test_derive_executable_edge_labels_applies_contextual_penalties(self):
        df = pd.DataFrame(
            {
                "ret_fwd_60s": [0.0016, 0.0016, 0.0016],
                "spread": [0.05, 0.05, 0.05],
                "mid": [50.0, 50.0, 50.0],
                "session_bucket": [1.0, 0.0, 1.0],
                "source_type": ["features", "features", "raw"],
            }
        )
        labeled, label_col = _derive_executable_edge_labels(
            df,
            horizon=60,
            edge_bps=12.0,
            spread_weight=1.0,
            open_penalty_bps=2.0,
            raw_penalty_bps=2.0,
        )
        assert labeled["edge_floor_bps_60s"].round(2).tolist() == [22.0, 24.0, 24.0]
        assert labeled[label_col].tolist() == [1.0, 1.0, 1.0]

    def test_apply_training_balance_weights_includes_label_balance(self):
        df = pd.DataFrame(
            {
                "source_type": ["features"] * 4,
                "date": ["2026-03-10"] * 4,
                "session_bucket": [1.0] * 4,
                "symbol": ["AAA", "AAA", "AAA", "AAA"],
                "label_exec_edge_60s": [1.0, 1.0, 1.0, 2.0],
            }
        )
        weights = _apply_training_balance_weights(df, label_col="label_exec_edge_60s")
        assert weights[-1] > weights[0]

    def test_build_training_dataframe_from_compact_cache_repairs_missing_source_type(
        self, tmp_path
    ):
        cache_dir = tmp_path / "cache"
        data_dir = cache_dir / "date=2026-03-10" / "symbol=TEST"
        data_dir.mkdir(parents=True)
        pd.DataFrame(
            {
                "ts_utc": pd.to_datetime(["2026-03-10 14:30:00+00:00"], utc=True),
                "date": ["2026-03-10"],
                "symbol": ["TEST"],
                "f1": [1.0],
                "source_type": [np.nan],
            }
        ).to_parquet(data_dir / "compact.parquet", index=False)
        (cache_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "entries": [
                        {
                            "date": "2026-03-10",
                            "symbol": "TEST",
                            "path": str(data_dir / "compact.parquet"),
                            "source_counts": {"features": 1},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        loaded = _build_training_dataframe_from_compact_cache(
            cache_dir=cache_dir,
            max_total_rows=None,
            max_rows_per_date=None,
            sampling_strategy="balanced_by_date",
        )

        assert loaded["source_type"].tolist() == ["features"]

    def test_build_training_dataframe_from_compact_cache_repairs_unknown_source_from_flags(
        self, tmp_path
    ):
        cache_dir = tmp_path / "cache"
        data_dir = cache_dir / "date=2026-03-10" / "symbol=TEST"
        data_dir.mkdir(parents=True)
        pd.DataFrame(
            {
                "ts_utc": pd.to_datetime(["2026-03-10 14:30:00+00:00"], utc=True),
                "date": ["2026-03-10"],
                "symbol": ["TEST"],
                "f1": [1.0],
                "source_type": ["unknown"],
                "source_is_features": [0.0],
                "source_is_raw": [1.0],
                "source_is_unknown": [0.0],
            }
        ).to_parquet(data_dir / "compact.parquet", index=False)
        (cache_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "entries": [
                        {
                            "date": "2026-03-10",
                            "symbol": "TEST",
                            "path": str(data_dir / "compact.parquet"),
                            "source_counts": {},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

        loaded = _build_training_dataframe_from_compact_cache(
            cache_dir=cache_dir,
            max_total_rows=None,
            max_rows_per_date=None,
            sampling_strategy="balanced_by_date",
        )

        assert loaded["source_type"].tolist() == ["raw"]

    def test_augment_training_context_features_adds_side_aware_columns(self):
        df = pd.DataFrame(
            {
                "session_bucket": [0.0, 2.0],
                "depth_imb_k_mean_10s": [0.20, -0.30],
                "depth_imb_k_mean_60s": [0.10, -0.20],
                "micro_off_mean_30s": [0.05, -0.07],
                "micro_off_mean_60s": [0.02, -0.04],
            }
        )

        augmented = _augment_training_context_features(
            df, enable_side_aware_context_features=True
        )

        assert augmented["session_is_open"].tolist() == [1.0, 0.0]
        assert augmented["session_is_midday"].tolist() == [0.0, 1.0]
        np.testing.assert_allclose(
            augmented["depth_imb_positive_10s"], [0.20, 0.0], atol=1e-6
        )
        np.testing.assert_allclose(
            augmented["depth_imb_negative_10s"], [0.0, 0.30], atol=1e-6
        )
        np.testing.assert_allclose(
            augmented["open_x_depth_imb_positive_10s"], [0.20, 0.0], atol=1e-6
        )
        np.testing.assert_allclose(
            augmented["midday_x_depth_imb_negative_10s"], [0.0, 0.30], atol=1e-6
        )

    def test_side_aware_context_columns_are_declared_for_stage_scoping(self):
        cols = set(get_side_aware_context_columns())
        assert "session_is_open" in cols
        assert "depth_imb_positive_10s" in cols
        assert "open_x_micro_off_negative_30s" in cols

    def test_evaluate_test_accuracy_filters_nan_labels_and_prefers_holdouts(self):
        model = type(
            "ModelStub", (), {"predict": lambda self, x: np.zeros(len(x), dtype=int)}
        )()
        df = pd.DataFrame(
            {
                "date": ["2025-12-08", "2025-12-08", "2025-12-09"],
                "symbol": ["AAA", "HOLD", "HOLD"],
                "f1": [1.0, 2.0, 3.0],
                "label_180s": [1.0, np.nan, 0.0],
            }
        )
        info = type(
            "SplitInfoStub",
            (),
            {
                "test_dates": ["2025-12-08", "2025-12-09"],
                "holdout_symbols": ["HOLD"],
            },
        )()
        acc = _evaluate_test_accuracy(df, info, ["f1"], "label_180s", model)
        assert acc == 1.0

    def test_evaluate_test_accuracy_uses_calibrator_when_provided(self):
        model = type(
            "ModelStub",
            (),
            {
                "predict_proba": lambda self, x: np.array(
                    [[0.2, 0.1, 0.7], [0.6, 0.2, 0.2]]
                )
            },
        )()
        calibrator = type(
            "CalibratorStub",
            (),
            {
                "predict_proba": lambda self, probs: np.array(
                    [[0.8, 0.1, 0.1], [0.1, 0.1, 0.8]]
                )
            },
        )()
        df = pd.DataFrame(
            {
                "date": ["2025-12-08", "2025-12-09"],
                "symbol": ["AAA", "BBB"],
                "f1": [1.0, 2.0],
                "label_180s": [0.0, 2.0],
            }
        )
        info = type(
            "SplitInfoStub",
            (),
            {
                "test_dates": ["2025-12-08", "2025-12-09"],
                "holdout_symbols": [],
            },
        )()

        acc = _evaluate_test_accuracy(
            df,
            info,
            ["f1"],
            "label_180s",
            model,
            calibrator=calibrator,
        )

        assert acc == 1.0

    def test_select_confidence_threshold_respects_precision_floor(self):
        probabilities = np.array(
            [
                [0.10, 0.10, 0.80],
                [0.80, 0.10, 0.10],
                [0.55, 0.10, 0.45],
                [0.55, 0.10, 0.45],
            ]
        )
        labels = np.array([2, 0, 2, 2])
        threshold, rows = select_confidence_threshold(
            probabilities,
            labels,
            thresholds=(0.45, 0.80),
            min_directional_precision=0.60,
            min_trigger_count=1,
        )
        assert threshold == pytest.approx(0.80)
        assert rows[0]["meets_precision_floor"] is False
        assert rows[1]["meets_precision_floor"] is True
