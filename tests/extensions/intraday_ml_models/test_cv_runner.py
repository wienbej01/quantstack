"""Tests for Cross-Validation Runner

Tests purged, embargoed time-series CV with proper temporal ordering
and comprehensive metrics aggregation.
"""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from extensions.intraday_ml_models.cv_runner import (
    CVMetrics,
    CVResult,
    CVSplit,
    TimeSeriesCVRunner,
    run_cross_validation,
)


class TestTimeSeriesCVRunner:
    """Test suite for TimeSeriesCVRunner."""

    @pytest.fixture
    def sample_data(self):
        """Create sample multi-index data for testing."""
        # Create sample symbols and timestamps
        symbols = ["AAPL", "MSFT", "GOOGL"]
        start_date = datetime(2024, 1, 1)
        dates = pd.date_range(start_date, periods=100, freq="D")

        # Create multi-index
        index = pd.MultiIndex.from_product([symbols, dates], names=["symbol", "ts"])

        # Create sample features and targets
        np.random.seed(42)
        n_samples = len(index)
        features_data = np.random.randn(n_samples, 5)
        feature_names = [
            "feature_1",
            "feature_2",
            "feature_3",
            "feature_4",
            "feature_5",
        ]

        features = pd.DataFrame(features_data, index=index, columns=feature_names)

        # Create tri-class targets
        targets = pd.Series(
            np.random.choice([-1, 0, 1], size=n_samples, p=[0.3, 0.4, 0.3]),
            index=index,
            name="target",
        )

        return features, targets

    @pytest.fixture
    def cv_config(self):
        """Sample CV configuration."""
        return {
            "n_folds": 3,
            "purge_days": 2,
            "embargo_days": 3,
            "validation_method": "purged_cv",
            "strict_temporal_order": True,
            "cross_symbol_consistency": True,
            "min_observations_per_fold": 50,
            "min_symbols_per_fold": 2,
            "metrics": {
                "primary_metrics": ["accuracy", "f1_macro", "brier_score"],
                "economic_metrics": ["expectancy", "win_rate"],
                "trade_density": ["trades_per_ticker_day"],
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
                "verbose": -1,
            },
            "training": {"validation_split": 0.2, "early_stopping_rounds": 5},
            "calibration": {"enabled": True, "method": "sigmoid", "cv_folds": 3},
            "reproducibility": {"seed": 42},
        }

    def test_cv_runner_initialization(self, cv_config):
        """Test CV runner initialization."""
        runner = TimeSeriesCVRunner(cv_config)

        assert runner.n_folds == 3
        assert runner.purge_days == 2
        assert runner.embargo_days == 3
        assert runner.validation_method == "purged_cv"
        assert runner.strict_temporal_order is True
        assert runner.cross_symbol_consistency is True

    def test_create_purged_splits(self, sample_data, cv_config):
        """Test creation of purged CV splits."""
        features, targets = sample_data
        runner = TimeSeriesCVRunner(cv_config)

        # Combine data for split creation
        combined_data = features.copy()
        combined_data["target"] = targets
        combined_data = combined_data.reset_index()

        splits = runner.create_splits(combined_data, "ts")

        assert len(splits) <= 3  # May have fewer due to minimum requirements
        assert all(isinstance(split, CVSplit) for split in splits)

        # Check temporal ordering
        for split in splits:
            assert split.train_end < split.val_start
            assert split.train_start <= split.train_end
            assert split.val_start <= split.val_end

        # Check symbol consistency
        for split in splits:
            assert len(split.train_symbols) >= 2
            assert len(split.val_symbols) >= 2
            if runner.cross_symbol_consistency:
                assert set(split.train_symbols) == set(split.val_symbols)

    def test_create_expanding_splits(self, sample_data, cv_config):
        """Test creation of expanding window splits."""
        cv_config_expanding = cv_config.copy()
        cv_config_expanding["validation_method"] = "expanding_window"

        features, targets = sample_data
        runner = TimeSeriesCVRunner(cv_config_expanding)

        combined_data = features.copy()
        combined_data["target"] = targets
        combined_data = combined_data.reset_index()

        splits = runner.create_splits(combined_data, "ts")
        assert isinstance(splits, list)

    def test_create_rolling_splits(self, sample_data, cv_config):
        """Test creation of rolling window splits."""
        cv_config_rolling = cv_config.copy()
        cv_config_rolling["validation_method"] = "rolling_window"

        features, targets = sample_data
        runner = TimeSeriesCVRunner(cv_config_rolling)

        combined_data = features.copy()
        combined_data["target"] = targets
        combined_data = combined_data.reset_index()

        splits = runner.create_splits(combined_data, "ts")
        assert isinstance(splits, list)

    def test_validate_cv_inputs_valid(self, sample_data):
        """Test input validation with valid data."""
        features, targets = sample_data
        runner = TimeSeriesCVRunner({})

        # Should not raise any exceptions
        runner._validate_cv_inputs(features, targets)

    def test_validate_cv_inputs_invalid_index(self, sample_data):
        """Test input validation with invalid index."""
        features, targets = sample_data
        runner = TimeSeriesCVRunner({})

        # Break multi-index
        features_bad = features.reset_index()
        targets_bad = targets.reset_index(drop=True)

        with pytest.raises(ValueError, match="multi-index"):
            runner._validate_cv_inputs(features_bad, targets_bad)

    def test_validate_cv_inputs_misaligned_indices(self, sample_data):
        """Test input validation with misaligned indices."""
        features, targets = sample_data
        runner = TimeSeriesCVRunner({})

        # Create misaligned indices
        targets_misaligned = targets.iloc[10:]

        with pytest.raises(ValueError, match="identical indices"):
            runner._validate_cv_inputs(features, targets_misaligned)

    def test_validate_cv_inputs_non_temporal_data(self, sample_data):
        """Test input validation with non-temporal data."""
        features, targets = sample_data
        runner = TimeSeriesCVRunner({})

        # Sort data to break temporal ordering for one symbol
        features_sorted = features.sort_values("feature_1")
        targets_sorted = targets.reindex(features_sorted.index)

        with pytest.raises(ValueError, match="temporally ordered"):
            runner._validate_cv_inputs(features_sorted, targets_sorted)

    def test_calculate_comprehensive_metrics(self, sample_data, cv_config):
        """Test comprehensive metrics calculation."""
        features, targets = sample_data
        runner = TimeSeriesCVRunner(cv_config)

        # Create mock split and training result
        split = CVSplit(
            fold=1,
            train_start=datetime(2024, 1, 1),
            train_end=datetime(2024, 1, 31),
            val_start=datetime(2024, 2, 1),
            val_end=datetime(2024, 2, 15),
            train_symbols=["AAPL", "MSFT"],
            val_symbols=["AAPL", "MSFT"],
            train_size=100,
            val_size=50,
        )

        # Create mock training result
        from unittest.mock import Mock

        from sklearn.calibration import CalibratedClassifierCV

        from extensions.intraday_ml_models.train_lgbm import TrainingResult

        # Create mock model with required attributes
        mock_model = Mock()
        mock_model.predict.return_value = np.array([0] * 20)  # Dummy predictions
        mock_model.predict_proba.return_value = np.array(
            [[0.7, 0.2, 0.1] for _ in range(20)]
        )  # Dummy probabilities
        mock_model.classes_ = np.array([-1, 0, 1])
        mock_model.feature_importances_ = np.array([0.5, 0.3, 0.1, 0.05, 0.05])

        mock_calibrated = Mock()
        mock_calibrated.predict.return_value = np.array([0] * 20)
        mock_calibrated.predict_proba.return_value = np.array(
            [[0.7, 0.2, 0.1] for _ in range(20)]
        )
        mock_calibrated.classes_ = np.array([-1, 0, 1])

        training_result = TrainingResult(
            model=mock_model,
            calibrated_model=mock_calibrated,
            metrics={"feature_importance": {"feature_1": 0.5, "feature_2": 0.3}},
            training_metadata={},
            training_time_seconds=10.0,
        )

        # Get validation data
        val_features = features[:20]
        val_labels = targets[:20]

        # Calculate metrics
        metrics = runner._calculate_comprehensive_metrics(
            training_result,
            val_features,
            val_labels,
            split,
            "features_hash",
            "targets_hash",
            "config_hash",
        )

        assert isinstance(metrics, CVMetrics)
        assert metrics.fold == 1
        assert hasattr(metrics, "accuracy")
        assert hasattr(metrics, "f1_macro")
        assert hasattr(metrics, "feature_importance")
        assert isinstance(metrics.feature_importance, dict)
        assert isinstance(metrics.top_features, list)

    def test_aggregate_metrics(self):
        """Test metrics aggregation across folds."""
        runner = TimeSeriesCVRunner({})

        # Create mock metrics
        fold_metrics = [
            CVMetrics(
                fold=1,
                accuracy=0.8,
                precision_macro=0.75,
                recall_macro=0.7,
                f1_macro=0.72,
                brier_score=0.3,
                brier_score_calibrated=0.28,
                brier_improvement=0.02,
                log_loss=0.5,
                log_loss_calibrated=0.48,
                class_metrics={},
                expectancy=0.1,
                sharpe_ratio=0.5,
                max_drawdown=0.1,
                win_rate=0.6,
                trades_per_ticker_day=2.0,
                micro_trade_rate=0.1,
                avg_holding_time=30.0,
                abstention_rate=0.2,
                feature_importance={},
                top_features=[],
                features_hash="",
                targets_hash="",
                config_hash="",
                train_time_seconds=10.0,
            ),
            CVMetrics(
                fold=2,
                accuracy=0.75,
                precision_macro=0.7,
                recall_macro=0.68,
                f1_macro=0.69,
                brier_score=0.32,
                brier_score_calibrated=0.3,
                brier_improvement=0.02,
                log_loss=0.52,
                log_loss_calibrated=0.5,
                class_metrics={},
                expectancy=0.08,
                sharpe_ratio=0.4,
                max_drawdown=0.12,
                win_rate=0.58,
                trades_per_ticker_day=1.8,
                micro_trade_rate=0.12,
                avg_holding_time=32.0,
                abstention_rate=0.25,
                feature_importance={},
                top_features=[],
                features_hash="",
                targets_hash="",
                config_hash="",
                train_time_seconds=12.0,
            ),
        ]

        aggregated = runner._aggregate_metrics(fold_metrics)

        # Check aggregation for key metrics
        assert "accuracy_mean" in aggregated
        assert "accuracy_std" in aggregated
        assert "f1_macro_mean" in aggregated
        assert np.isclose(aggregated["accuracy_mean"], 0.775)
        assert np.isclose(aggregated["f1_macro_mean"], 0.705)

    def test_stability_metrics(self):
        """Test stability metrics calculation."""
        runner = TimeSeriesCVRunner({})

        # Create mock metrics with some variation
        fold_metrics = [
            CVMetrics(
                fold=1,
                accuracy=0.8,
                precision_macro=0.75,
                recall_macro=0.7,
                f1_macro=0.72,
                brier_score=0.3,
                brier_score_calibrated=0.28,
                brier_improvement=0.02,
                log_loss=0.5,
                log_loss_calibrated=0.48,
                class_metrics={},
                expectancy=0.1,
                sharpe_ratio=0.5,
                max_drawdown=0.1,
                win_rate=0.6,
                trades_per_ticker_day=2.0,
                micro_trade_rate=0.1,
                avg_holding_time=30.0,
                abstention_rate=0.2,
                feature_importance={"feature_1": 0.5},
                top_features=[],
                features_hash="",
                targets_hash="",
                config_hash="",
                train_time_seconds=10.0,
            ),
            CVMetrics(
                fold=2,
                accuracy=0.78,
                precision_macro=0.73,
                recall_macro=0.69,
                f1_macro=0.71,
                brier_score=0.31,
                brier_score_calibrated=0.29,
                brier_improvement=0.02,
                log_loss=0.51,
                log_loss_calibrated=0.49,
                class_metrics={},
                expectancy=0.09,
                sharpe_ratio=0.45,
                max_drawdown=0.11,
                win_rate=0.59,
                trades_per_ticker_day=1.9,
                micro_trade_rate=0.11,
                avg_holding_time=31.0,
                abstention_rate=0.22,
                feature_importance={"feature_1": 0.48},
                top_features=[],
                features_hash="",
                targets_hash="",
                config_hash="",
                train_time_seconds=11.0,
            ),
        ]

        stability = runner._calculate_stability_metrics(fold_metrics)

        assert "accuracy_cv" in stability
        assert "f1_macro_cv" in stability
        assert "feature_importance_stability" in stability
        assert stability["accuracy_cv"] >= 0

    def test_calibration_metrics(self):
        """Test calibration metrics calculation."""
        runner = TimeSeriesCVRunner({})

        fold_metrics = [
            CVMetrics(
                fold=1,
                accuracy=0.8,
                precision_macro=0.75,
                recall_macro=0.7,
                f1_macro=0.72,
                brier_score=0.3,
                brier_score_calibrated=0.28,
                brier_improvement=0.02,
                log_loss=0.5,
                log_loss_calibrated=0.48,
                class_metrics={},
                expectancy=0.1,
                sharpe_ratio=0.5,
                max_drawdown=0.1,
                win_rate=0.6,
                trades_per_ticker_day=2.0,
                micro_trade_rate=0.1,
                avg_holding_time=30.0,
                abstention_rate=0.2,
                feature_importance={},
                top_features=[],
                features_hash="",
                targets_hash="",
                config_hash="",
                train_time_seconds=10.0,
            ),
            CVMetrics(
                fold=2,
                accuracy=0.75,
                precision_macro=0.7,
                recall_macro=0.68,
                f1_macro=0.69,
                brier_score=0.32,
                brier_score_calibrated=0.3,
                brier_improvement=0.02,
                log_loss=0.52,
                log_loss_calibrated=0.5,
                class_metrics={},
                expectancy=0.08,
                sharpe_ratio=0.4,
                max_drawdown=0.12,
                win_rate=0.58,
                trades_per_ticker_day=1.8,
                micro_trade_rate=0.12,
                avg_holding_time=32.0,
                abstention_rate=0.25,
                feature_importance={},
                top_features=[],
                features_hash="",
                targets_hash="",
                config_hash="",
                train_time_seconds=12.0,
            ),
        ]

        calibration = runner._calculate_calibration_metrics(fold_metrics)

        assert "mean_brier_score" in calibration
        assert "brier_score_std" in calibration
        assert "brier_score_consistency" in calibration
        assert np.isclose(calibration["mean_brier_score"], 0.31)

    @pytest.mark.skip(reason="Integration test with actual model training")
    def test_run_cv_integration(self, sample_data, cv_config, model_config):
        """Integration test for complete CV run."""
        features, targets = sample_data
        runner = TimeSeriesCVRunner(cv_config)

        # This would require actual LightGBM training
        # Skipping for unit test efficiency
        pass

    def test_run_cross_validation_convenience_function(
        self, sample_data, cv_config, model_config
    ):
        """Test convenience function for CV."""
        features, targets = sample_data

        # Test function signature
        assert callable(run_cross_validation)

        # Note: Full integration test would require actual model training
        # which is computationally expensive for unit tests


class TestCVSplit:
    """Test CVSplit dataclass."""

    def test_cv_split_creation(self):
        """Test CVSplit dataclass creation."""
        split = CVSplit(
            fold=1,
            train_start=datetime(2024, 1, 1),
            train_end=datetime(2024, 1, 31),
            val_start=datetime(2024, 2, 1),
            val_end=datetime(2024, 2, 15),
            train_symbols=["AAPL", "MSFT"],
            val_symbols=["AAPL", "MSFT"],
            train_size=100,
            val_size=50,
        )

        assert split.fold == 1
        assert split.train_symbols == ["AAPL", "MSFT"]
        assert split.val_size == 50


class TestCVMetrics:
    """Test CVMetrics dataclass."""

    def test_cv_metrics_creation(self):
        """Test CVMetrics dataclass creation."""
        metrics = CVMetrics(
            fold=1,
            accuracy=0.8,
            precision_macro=0.75,
            recall_macro=0.7,
            f1_macro=0.72,
            brier_score=0.3,
            brier_score_calibrated=0.28,
            brier_improvement=0.02,
            log_loss=0.5,
            log_loss_calibrated=0.48,
            class_metrics={},
            expectancy=0.1,
            sharpe_ratio=0.5,
            max_drawdown=0.1,
            win_rate=0.6,
            trades_per_ticker_day=2.0,
            micro_trade_rate=0.1,
            avg_holding_time=30.0,
            abstention_rate=0.2,
            feature_importance={"feature_1": 0.5},
            top_features=[("feature_1", 0.5)],
            features_hash="hash1",
            targets_hash="hash2",
            config_hash="hash3",
            train_time_seconds=10.0,
        )

        assert metrics.fold == 1
        assert metrics.accuracy == 0.8
        assert metrics.feature_importance == {"feature_1": 0.5}
        assert len(metrics.top_features) == 1


class TestCVResult:
    """Test CVResult dataclass."""

    def test_cv_result_creation(self):
        """Test CVResult dataclass creation."""
        cv_config = {"n_folds": 3}
        splits = []
        fold_metrics = []
        aggregated_metrics = {"accuracy_mean": 0.75}
        stability_metrics = {"accuracy_cv": 0.1}
        calibration_metrics = {"mean_brier_score": 0.3}
        reproducibility_info = {"unique_hashes": 3}

        result = CVResult(
            cv_config=cv_config,
            splits=splits,
            fold_metrics=fold_metrics,
            aggregated_metrics=aggregated_metrics,
            stability_metrics=stability_metrics,
            calibration_metrics=calibration_metrics,
            reproducibility_info=reproducibility_info,
            total_time_seconds=120.0,
        )

        assert result.cv_config == cv_config
        assert result.total_time_seconds == 120.0
        assert result.aggregated_metrics["accuracy_mean"] == 0.75
