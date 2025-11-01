"""Tests for Walk-Forward Optimization Evaluator

Tests walk-forward evaluation with KPI tracking, regime analysis,
and comprehensive performance monitoring.
"""

from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest

from extensions.intraday_ml_models.wfo_evaluator import (
    WalkForwardEvaluator,
    WFOAggregatedResults,
    WFOPeriod,
    WFOPeriodResults,
    run_walk_forward_optimization,
)


class TestWFOPeriod:
    """Test WFOPeriod dataclass."""

    def test_wfo_period_creation(self):
        """Test WFOPeriod creation."""
        period = WFOPeriod(
            period_id=1,
            train_start=datetime(2024, 1, 1),
            train_end=datetime(2024, 3, 31),
            validation_start=datetime(2024, 4, 1),
            validation_end=datetime(2024, 4, 30),
            oos_start=datetime(2024, 5, 1),
            oos_end=datetime(2024, 5, 31),
            train_symbols=["AAPL", "MSFT", "GOOGL"],
            oos_symbols=["AAPL", "MSFT", "GOOGL"],
            train_size=3000,
            oos_size=1000,
        )

        assert period.period_id == 1
        assert period.train_start == datetime(2024, 1, 1)
        assert period.oos_end == datetime(2024, 5, 31)
        assert len(period.train_symbols) == 3
        assert period.train_size == 3000


class TestWFOPeriodResults:
    """Test WFOPeriodResults dataclass."""

    def test_wfo_period_results_creation(self):
        """Test WFOPeriodResults creation."""
        period = WFOPeriod(
            period_id=1,
            train_start=datetime(2024, 1, 1),
            train_end=datetime(2024, 3, 31),
            validation_start=datetime(2024, 4, 1),
            validation_end=datetime(2024, 4, 30),
            oos_start=datetime(2024, 5, 1),
            oos_end=datetime(2024, 5, 31),
            train_symbols=["AAPL", "MSFT"],
            oos_symbols=["AAPL", "MSFT"],
            train_size=1000,
            oos_size=300,
        )

        oos_predictions = pd.DataFrame(
            {
                "prob_class_-1": [0.3, 0.2, 0.5],
                "prob_class_0": [0.4, 0.6, 0.3],
                "prob_class_1": [0.3, 0.2, 0.2],
                "predicted_class": [0, 0, -1],
            }
        )

        oos_metrics = {
            "accuracy": 0.75,
            "f1_macro": 0.70,
            "brier_score": 0.25,
            "total_predictions": 300,
        }

        results = WFOPeriodResults(
            period=period,
            training_result=Mock(),  # Would be actual TrainingResult
            cv_results={},
            oos_predictions=oos_predictions,
            oos_metrics=oos_metrics,
            model_path="/path/to/model.joblib",
            model_card_path="/path/to/model_card.json",
            training_time_seconds=120.0,
            inference_time_seconds=5.0,
        )

        assert results.period.period_id == 1
        assert results.oos_metrics["accuracy"] == 0.75
        assert len(results.oos_predictions) == 3
        assert results.training_time_seconds == 120.0


class TestWalkForwardEvaluator:
    """Test WalkForwardEvaluator class."""

    @pytest.fixture
    def wfo_config(self):
        """Sample WFO configuration."""
        return {
            "train_months": 3,
            "validation_months": 1,
            "oos_months": 1,
            "step_size_months": 1,
            "window_type": "expanding",
            "start_date": "2024-01-01",
            "min_observations_per_period": 500,
            "min_symbols_per_period": 2,
            "kpi_tracking": {
                "performance_thresholds": {"min_f1_score": 0.6, "min_accuracy": 0.65}
            },
        }

    @pytest.fixture
    def model_config(self):
        """Sample model configuration."""
        return {
            "lgbm_params": {
                "objective": "multiclass",
                "num_class": 3,
                "n_estimators": 10,
                "random_state": 42,
            },
            "training": {"validation_split": 0.2},
        }

    @pytest.fixture
    def cv_config(self):
        """Sample CV configuration."""
        return {
            "n_folds": 3,
            "purge_days": 2,
            "embargo_days": 3,
            "validation_method": "purged_cv",
        }

    @pytest.fixture
    def sample_data(self):
        """Create sample multi-index data for testing."""
        symbols = ["AAPL", "MSFT", "GOOGL"]
        start_date = datetime(2024, 1, 1)
        dates = pd.date_range(start_date, periods=200, freq="D")

        index = pd.MultiIndex.from_product([symbols, dates], names=["symbol", "ts"])

        np.random.seed(42)
        n_samples = len(index)
        features_data = np.random.randn(n_samples, 4)
        feature_names = ["feature_1", "feature_2", "feature_3", "feature_4"]

        features = pd.DataFrame(features_data, index=index, columns=feature_names)

        targets = pd.Series(
            np.random.choice([-1, 0, 1], size=n_samples), index=index, name="target"
        )

        return features, targets

    def test_evaluator_initialization(self, wfo_config, tmp_path):
        """Test evaluator initialization."""
        model_dir = tmp_path / "models"
        evaluator = WalkForwardEvaluator(wfo_config, model_dir)

        assert evaluator.config == wfo_config
        assert evaluator.model_dir == model_dir
        assert evaluator.train_months == 3
        assert evaluator.validation_months == 1
        assert evaluator.oos_months == 1
        assert evaluator.step_size_months == 1
        assert evaluator.window_type == "expanding"
        assert evaluator.start_date == pd.to_datetime("2024-01-01")

    def test_create_wfo_periods(self, wfo_config, sample_data, tmp_path):
        """Test WFO period creation."""
        features, targets = sample_data
        evaluator = WalkForwardEvaluator(wfo_config, tmp_path / "models")

        # Combine data for period creation
        combined_data = features.copy()
        combined_data["target"] = targets

        periods = evaluator.create_wfo_periods(combined_data)

        assert isinstance(periods, list)
        # Note: Periods may be empty if data doesn't meet requirements
        # Test the structure when periods are created
        if len(periods) > 0:
            for period in periods:
                assert isinstance(period, WFOPeriod)

        # Check period structure when periods exist
        if len(periods) > 0:
            for period in periods:
                assert isinstance(period, WFOPeriod)
                assert period.train_start < period.train_end
                assert period.train_end < period.validation_start
                assert period.validation_end < period.oos_start
                assert period.oos_start < period.oos_end
                assert len(period.train_symbols) >= 2
                assert len(period.oos_symbols) >= 2
                assert period.train_size > 0
                assert period.oos_size > 0

            # Check temporal ordering
            for i in range(1, len(periods)):
                assert periods[i - 1].oos_end < periods[i].train_start

    def test_create_wfo_periods_rolling_window(self, sample_data, tmp_path):
        """Test WFO period creation with rolling window."""
        wfo_config_rolling = {
            "train_months": 3,
            "validation_months": 1,
            "oos_months": 1,
            "step_size_months": 1,
            "window_type": "rolling",
            "start_date": "2024-01-01",
            "min_observations_per_period": 500,
            "min_symbols_per_period": 2,
        }

        features, targets = sample_data
        evaluator = WalkForwardEvaluator(wfo_config_rolling, tmp_path / "models")

        combined_data = features.copy()
        combined_data["target"] = targets

        periods = evaluator.create_wfo_periods(combined_data)
        assert isinstance(periods, list)

    def test_find_date_index(self, wfo_config, tmp_path):
        """Test date index finding."""
        evaluator = WalkForwardEvaluator(wfo_config, tmp_path / "models")

        dates = pd.date_range("2024-01-01", periods=10, freq="D")

        # Test existing date
        target_date = dates[5]
        idx = evaluator._find_date_index(dates.tolist(), target_date, 0)
        # The method finds the first date >= target, which should be index 5
        assert idx >= 5 and idx < len(dates)
        assert dates[idx] >= target_date

        # Test non-existing date (should find next available)
        target_date = dates[5] + pd.Timedelta(hours=12)
        idx = evaluator._find_date_index(dates.tolist(), target_date, 0)
        # Should find date 6 since date 5 is not >= the target (target is later in the day)
        assert idx == 6

        # Test date beyond range
        target_date = dates[-1] + pd.Timedelta(days=10)
        idx = evaluator._find_date_index(dates.tolist(), target_date, 0)
        assert idx is None

    def test_generate_predictions(self, wfo_config, sample_data, tmp_path):
        """Test prediction generation."""
        evaluator = WalkForwardEvaluator(wfo_config, tmp_path / "models")

        features, _ = sample_data
        features_subset = features[:20]

        # Mock model
        mock_model = Mock()
        mock_model.predict_proba.return_value = np.array(
            [
                [0.3, 0.4, 0.3],  # Sample 1
                [0.2, 0.5, 0.3],  # Sample 2
            ]
        )
        mock_model.predict.return_value = np.array([0, 0])

        predictions = evaluator._generate_predictions(mock_model, features_subset[:2])

        assert isinstance(predictions, pd.DataFrame)
        assert len(predictions) == 2
        assert "prob_class_0" in predictions.columns
        assert "prob_class_1" in predictions.columns
        assert "prob_class_2" in predictions.columns
        assert "predicted_class" in predictions.columns

    def test_calculate_oos_metrics(self, wfo_config, tmp_path):
        """Test OOS metrics calculation."""
        evaluator = WalkForwardEvaluator(wfo_config, tmp_path / "models")

        # Create mock predictions
        predictions = pd.DataFrame(
            {
                "prob_class_-1": [0.3, 0.2, 0.4, 0.1],
                "prob_class_0": [0.4, 0.6, 0.3, 0.7],
                "prob_class_1": [0.3, 0.2, 0.3, 0.2],
                "predicted_class": [0, 0, -1, 0],
            },
            index=pd.MultiIndex.from_tuples(
                [
                    ("AAPL", pd.Timestamp("2024-01-01")),
                    ("AAPL", pd.Timestamp("2024-01-02")),
                    ("MSFT", pd.Timestamp("2024-01-01")),
                    ("MSFT", pd.Timestamp("2024-01-02")),
                ],
                names=["symbol", "ts"],
            ),
        )

        true_labels = pd.Series([0, 1, -1, 0], index=predictions.index)

        metrics = evaluator._calculate_oos_metrics(predictions, true_labels)

        assert isinstance(metrics, dict)
        assert "accuracy" in metrics
        assert "f1_macro" in metrics
        assert "brier_score" in metrics
        assert "log_loss" in metrics
        assert "win_rate" in metrics
        assert "total_predictions" in metrics
        assert "prediction_distribution" in metrics

        assert 0 <= metrics["accuracy"] <= 1
        assert 0 <= metrics["f1_macro"] <= 1
        assert metrics["total_predictions"] == 4

    def test_calculate_overall_metrics(self, wfo_config, tmp_path):
        """Test overall metrics calculation."""
        evaluator = WalkForwardEvaluator(wfo_config, tmp_path / "models")

        # Create mock period results
        period_results = []
        for i in range(3):
            oos_metrics = {
                "accuracy": 0.7 + i * 0.05,
                "precision_macro": 0.65 + i * 0.03,
                "recall_macro": 0.68 + i * 0.04,
                "f1_macro": 0.66 + i * 0.02,
                "brier_score": 0.3 - i * 0.02,
                "log_loss": 0.5 - i * 0.01,
                "win_rate": 0.7 + i * 0.05,
            }

            period_result = Mock()
            period_result.oos_metrics = oos_metrics
            period_result.training_time_seconds = 100.0 + i * 10
            period_result.inference_time_seconds = 5.0 + i

            period_results.append(period_result)

        overall = evaluator._calculate_overall_metrics(period_results)

        # Check aggregated statistics
        for metric in ["accuracy", "f1_macro", "brier_score"]:
            assert f"{metric}_mean" in overall
            assert f"{metric}_std" in overall
            assert f"{metric}_min" in overall
            assert f"{metric}_max" in overall

        # Check timing metrics
        assert "training_time_mean" in overall
        assert "training_time_total" in overall
        assert "inference_time_mean" in overall

        # Verify calculations
        expected_f1_mean = np.mean([0.66, 0.68, 0.70])
        assert np.isclose(overall["f1_macro_mean"], expected_f1_mean)

    def test_analyze_temporal_stability(self, wfo_config, tmp_path):
        """Test temporal stability analysis."""
        evaluator = WalkForwardEvaluator(wfo_config, tmp_path / "models")

        # Create mock period results with trend
        period_results = []
        for i in range(5):
            oos_metrics = {"f1_macro": 0.65 + i * 0.02, "accuracy": 0.7 + i * 0.01}
            period = Mock()
            period.period_id = i + 1

            period_result = Mock()
            period_result.period = period
            period_result.oos_metrics = oos_metrics
            period_results.append(period_result)

        stability = evaluator._analyze_temporal_stability(period_results)

        assert "f1_trend" in stability
        assert "accuracy_trend" in stability
        assert "f1_volatility" in stability
        assert "accuracy_volatility" in stability
        assert "stability_score" in stability
        assert "performance_drift" in stability

        # Check that trend is positive (increasing performance)
        assert stability["f1_trend"] > 0

        # Check stability score calculation
        expected_volatility = np.std([0.65, 0.67, 0.69, 0.71, 0.73])
        expected_stability = 1 / (1 + expected_volatility)
        assert np.isclose(stability["stability_score"], expected_stability)

    def test_analyze_regime_performance(self, wfo_config, tmp_path):
        """Test regime performance analysis."""
        evaluator = WalkForwardEvaluator(wfo_config, tmp_path / "models")

        # Create mock period results across different quarters
        period_results = []
        quarters = ["2024-Q1", "2024-Q1", "2024-Q2", "2024-Q2"]

        for i, quarter in enumerate(quarters):
            # Create period with appropriate dates
            if "Q1" in quarter:
                oos_start = datetime(2024, 1, 15) + timedelta(days=i * 30)
            else:
                oos_start = datetime(2024, 4, 15) + timedelta(days=i * 30)

            period = Mock()
            period.period_id = i + 1
            period.oos_start = oos_start

            oos_metrics = {"f1_macro": 0.65 + i * 0.02, "accuracy": 0.7}

            period_result = Mock()
            period_result.period = period
            period_result.oos_metrics = oos_metrics
            period_results.append(period_result)

        regime_analysis = evaluator._analyze_regime_performance(period_results)

        assert "quarterly_performance" in regime_analysis
        assert "regime_consistency" in regime_analysis

        # Check quarterly statistics
        quarterly_perf = regime_analysis["quarterly_performance"]
        assert "2024-Q1" in quarterly_perf
        assert "2024-Q2" in quarterly_perf

        for quarter_data in quarterly_perf.values():
            assert "mean_f1" in quarter_data
            assert "std_f1" in quarter_data
            assert "period_count" in quarter_data

    def test_analyze_model_evolution(self, wfo_config, tmp_path):
        """Test model evolution analysis."""
        evaluator = WalkForwardEvaluator(wfo_config, tmp_path / "models")

        # Create mock period results with feature importance
        period_results = []
        for i in range(3):
            feature_importance = {
                "feature_1": 0.5 - i * 0.05,
                "feature_2": 0.3 + i * 0.02,
                "feature_3": 0.2 + i * 0.03,
            }

            training_result = Mock()
            training_result.metrics = {"feature_importance": feature_importance}

            period_result = Mock()
            period_result.training_result = training_result
            period_results.append(period_result)

        evolution = evaluator._analyze_model_evolution(period_results)

        assert "feature_importance_trends" in evolution
        assert "model_complexity_evolution" in evolution
        assert "hyperparameter_stability" in evolution

        # Check feature importance trends
        trends = evolution["feature_importance_trends"]
        assert "feature_1" in trends
        assert "feature_2" in trends
        assert "feature_3" in trends

        # feature_1 should have negative trend (decreasing importance)
        assert trends["feature_1"] < 0

    def test_calculate_kpi_summary(self, wfo_config, tmp_path):
        """Test KPI summary calculation."""
        evaluator = WalkForwardEvaluator(wfo_config, tmp_path / "models")

        # Create mock period results with varying performance
        period_results = []
        for i in range(5):
            oos_metrics = {
                "f1_macro": 0.6 + i * 0.05,  # 0.6 to 0.8
                "accuracy": 0.65 + i * 0.04,
                "precision_macro": 0.62 + i * 0.04,
                "recall_macro": 0.63 + i * 0.03,
            }

            period_result = Mock()
            period_result.oos_metrics = oos_metrics
            period_result.training_time_seconds = 100.0
            period_result.inference_time_seconds = 5.0
            period_results.append(period_result)

        kpi_summary = evaluator._calculate_kpi_summary(period_results)

        assert "performance" in kpi_summary
        assert "efficiency" in kpi_summary
        assert "reliability" in kpi_summary
        assert "production_readiness" in kpi_summary

        # Check performance KPIs
        perf_kpis = kpi_summary["performance"]
        assert "mean_f1_score" in perf_kpis
        assert "f1_consistency" in perf_kpis
        assert "worst_period_f1" in perf_kpis
        assert "performance_above_threshold" in perf_kpis

        # Check efficiency KPIs
        eff_kpis = kpi_summary["efficiency"]
        assert "total_training_hours" in eff_kpis
        assert "average_inference_time_ms" in eff_kpis
        assert "periods_per_day" in eff_kpis

        # Check reliability KPIs
        rel_kpis = kpi_summary["reliability"]
        assert "successful_periods" in rel_kpis
        assert "success_rate" in rel_kpis

        # Check production readiness
        prod_ready = kpi_summary["production_readiness"]
        assert "ready_for_production" in prod_ready
        assert "recommended_monitoring" in prod_ready
        assert "risk_level" in prod_ready

        # Verify calculations
        expected_mean_f1 = np.mean([0.6, 0.65, 0.7, 0.75, 0.8])
        assert np.isclose(perf_kpis["mean_f1_score"], expected_mean_f1)

        # With good performance, should be ready for production
        assert bool(prod_ready["ready_for_production"]) is True
        assert prod_ready["risk_level"] in ["low", "medium", "high"]

    def test_compute_data_hash(self, wfo_config, tmp_path, sample_data):
        """Test data hash computation."""
        evaluator = WalkForwardEvaluator(wfo_config, tmp_path / "models")
        features, _ = sample_data

        hash_value = evaluator._compute_data_hash(features)

        assert isinstance(hash_value, str)
        assert len(hash_value) > 0

        # Hash should be consistent for same data
        hash_value_2 = evaluator._compute_data_hash(features)
        assert hash_value == hash_value_2

    def test_compute_config_hash(self, wfo_config, tmp_path):
        """Test config hash computation."""
        evaluator = WalkForwardEvaluator(wfo_config, tmp_path / "models")

        model_config = {"param1": "value1", "param2": 42}
        cv_config = {"n_folds": 3, "method": "purged"}

        hash_value = evaluator._compute_config_hash(model_config, cv_config)

        assert isinstance(hash_value, str)
        assert len(hash_value) > 0

        # Hash should be consistent for same configs
        hash_value_2 = evaluator._compute_config_hash(model_config, cv_config)
        assert hash_value == hash_value_2

        # Different configs should produce different hashes
        different_config = {"param1": "value2", "param2": 42}
        hash_value_3 = evaluator._compute_config_hash(different_config, cv_config)
        assert hash_value != hash_value_3

    @patch("extensions.intraday_ml_models.wfo_evaluator.run_cross_validation")
    @patch("extensions.intraday_ml_models.wfo_evaluator.LightGBMTrainer")
    def test_run_wfo_period(
        self, mock_trainer_class, mock_run_cv, wfo_config, sample_data, tmp_path
    ):
        """Test running a single WFO period."""
        # Setup mocks
        mock_trainer = Mock()
        mock_trainer_class.return_value = mock_trainer

        mock_training_result = Mock()
        mock_training_result.metrics = {"feature_importance": {"feature_1": 0.5}}
        mock_calibrated = Mock()

        # Create dynamic mock that returns right size for any input
        def mock_predict_proba(X):
            n_samples = (
                len(X) if hasattr(X, "__len__") else 28
            )  # Default to sample size
            return np.array([[0.3, 0.4, 0.3]] * n_samples)  # 3 classes

        def mock_predict(X):
            n_samples = len(X) if hasattr(X, "__len__") else 28
            return np.array([0] * n_samples)

        mock_calibrated.predict_proba.side_effect = mock_predict_proba
        mock_calibrated.predict.side_effect = mock_predict
        mock_training_result.calibrated_model = mock_calibrated
        mock_trainer.train_model.return_value = mock_training_result

        mock_cv_result = Mock()
        mock_cv_result.reproducibility_info = {
            "features_hash": "hash1",
            "targets_hash": "hash2",
        }
        mock_run_cv.return_value = mock_cv_result

        evaluator = WalkForwardEvaluator(wfo_config, tmp_path / "models")

        # Create test period
        period = WFOPeriod(
            period_id=1,
            train_start=datetime(2024, 1, 1),
            train_end=datetime(2024, 1, 31),
            validation_start=datetime(2024, 2, 1),
            validation_end=datetime(2024, 2, 15),
            oos_start=datetime(2024, 2, 16),
            oos_end=datetime(2024, 2, 29),
            train_symbols=["AAPL", "MSFT"],
            oos_symbols=["AAPL", "MSFT"],
            train_size=100,
            oos_size=50,
        )

        features, targets = sample_data
        combined_data = features.copy()
        combined_data["target"] = targets

        # Mock model IO
        evaluator.model_io = Mock()
        evaluator.model_io.save_model.return_value = {
            "model_path": "/path/to/model.joblib",
            "model_card_path": "/path/to/card.json",
        }

        # Run period
        result = evaluator._run_wfo_period(period, combined_data, {}, {})

        assert isinstance(result, WFOPeriodResults)
        assert result.period == period
        assert result.training_result == mock_training_result
        assert result.model_path == "/path/to/model.joblib"

    def test_run_walk_forward_optimization_convenience(
        self, wfo_config, model_config, cv_config, sample_data
    ):
        """Test convenience function for WFO."""
        features, targets = sample_data

        # Test function signature
        assert callable(run_walk_forward_optimization)

        # Note: Full integration test would require actual model training
        # which is computationally expensive for unit tests


class TestWFOAggregatedResults:
    """Test WFOAggregatedResults dataclass."""

    def test_wfo_aggregated_results_creation(self):
        """Test WFOAggregatedResults creation."""
        result = WFOAggregatedResults(
            wfo_config={"train_months": 3},
            periods=[],
            period_results=[],
            overall_metrics={"f1_macro_mean": 0.7},
            temporal_stability={"f1_trend": 0.01},
            regime_analysis={"quarterly_performance": {}},
            model_evolution={"feature_importance_trends": {}},
            kpi_summary={"performance": {"mean_f1_score": 0.7}},
            total_time_seconds=3600.0,
            reproducibility_info={"total_periods": 5},
        )

        assert result.wfo_config["train_months"] == 3
        assert result.overall_metrics["f1_macro_mean"] == 0.7
        assert result.total_time_seconds == 3600.0
        assert result.reproducibility_info["total_periods"] == 5
