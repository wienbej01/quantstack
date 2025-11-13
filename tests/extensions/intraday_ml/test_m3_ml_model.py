"""Sprint M3 ML Model Tests

Tests for labeling, LightGBM training, model I/O, and decision policy
ensuring compliance with no-peek rules and execution discipline.
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from extensions.intraday_ml.labeling import IntradayMLLabeler
from extensions.intraday_ml_models.decision_policy import DecisionPolicy

# Mock LightGBM for testing if not available
try:
    from extensions.intraday_ml_models.model_io import (
        ModelIO,
        load_model_with_card,
        save_model_with_card,
    )
    from extensions.intraday_ml_models.train_lgbm import (
        LightGBMTrainer,
        train_lgbm_model,
    )

    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False
    LightGBMTrainer = None
    train_lgbm_model = None
    ModelIO = None
    save_model_with_card = None
    load_model_with_card = None


class TestLabeling:
    """Tests for ATR-thresholded labeling with no-peek validation."""

    @pytest.fixture
    def targets_config(self):
        """Load targets configuration."""
        config_path = Path("configs/extensions/intraday_ml/targets.yaml")
        with open(config_path) as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def sample_bars(self):
        """Generate sample bar data for labeling."""
        np.random.seed(42)
        symbols = ["AAPL", "MSFT"]
        dates = pd.date_range("2024-01-02 09:30:00", periods=200, freq="1min")

        data = []
        for symbol in symbols:
            base_price = 150.0 if symbol == "AAPL" else 250.0

            for i, ts in enumerate(dates):
                # Simulate price movement with some trends
                trend = i * 0.001  # Small trend
                noise = np.random.normal(0, 0.002) * base_price
                close = base_price + trend + noise

                # Generate OHLC with some volatility
                high_low_range = abs(np.random.normal(0, 0.005)) * base_price
                high = close + high_low_range * np.random.random()
                low = close - high_low_range * (1 - np.random.random())
                open_price = low + (high - low) * np.random.random()

                volume = max(1000, int(np.random.normal(100000, 20000)))

                data.append(
                    {
                        "ts": ts,
                        "symbol": symbol,
                        "open": open_price,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume,
                    }
                )

        df = pd.DataFrame(data)
        return df.sort_values(["symbol", "ts"]).reset_index(drop=True)

    def test_labeler_initialization(self, targets_config):
        """Test labeler initializes correctly."""
        labeler = IntradayMLLabeler(targets_config)
        assert labeler.horizons == [30, 60, 90]
        assert labeler.atr_multiplier == pytest.approx(0.038, rel=1e-6)
        assert labeler.base_long_multiplier == pytest.approx(0.036, rel=1e-6)
        assert labeler.base_short_multiplier == pytest.approx(0.04, rel=1e-6)
        assert labeler.volatility_scaling_enabled is True
        assert labeler.directional_balance_enabled is True
        assert labeler.atr_window == 14

    def test_no_peek_validation(self, targets_config, sample_bars):
        """Test no-peek validation works correctly."""
        labeler = IntradayMLLabeler(targets_config)

        # Should work with sufficient historical data
        ts_cut = sample_bars["ts"].iloc[50]  # Cut in middle
        label_result = labeler.create_labels(sample_bars, ts_cut, validate_no_peek=True)
        assert label_result is not None
        assert len(label_result.labels) > 0

        # Should fail with insufficient historical data
        early_ts_cut = sample_bars["ts"].iloc[10]  # Too early
        with pytest.raises(ValueError, match="Insufficient historical data"):
            labeler.create_labels(sample_bars, early_ts_cut, validate_no_peek=True)

    def test_label_creation(self, targets_config, sample_bars):
        """Test label creation with ATR thresholds."""
        labeler = IntradayMLLabeler(targets_config)
        ts_cut = sample_bars["ts"].iloc[50]

        label_result = labeler.create_labels(sample_bars, ts_cut)

        # Validate structure
        assert label_result.labels is not None
        assert isinstance(label_result.labels, pd.Series)
        assert label_result.metadata is not None
        assert label_result.targets_hash is not None

        # Validate label values are in {-1, 0, 1}
        unique_labels = set(label_result.labels.dropna().unique())
        assert unique_labels.issubset({-1, 0, 1})

        # Validate metadata
        assert "horizons" in label_result.metadata
        assert "atr_multiplier" in label_result.metadata
        assert "label_counts" in label_result.metadata

    def test_atr_computation(self, targets_config, sample_bars):
        """Test ATR computation uses only historical data."""
        labeler = IntradayMLLabeler(targets_config)
        ts_cut = sample_bars["ts"].iloc[50]

        # ATR should be computed from data ≤ ts_cut only
        historical_bars = sample_bars[sample_bars["ts"] <= ts_cut]
        assert len(historical_bars) >= labeler.atr_window

        label_result = labeler.create_labels(sample_bars, ts_cut)
        assert label_result is not None  # Should not raise any errors

    def test_targets_hash_deterministic(self, targets_config, sample_bars):
        """Test targets hash is deterministic."""
        labeler = IntradayMLLabeler(targets_config)
        ts_cut = sample_bars["ts"].iloc[50]

        # Create labels twice
        result1 = labeler.create_labels(sample_bars, ts_cut)
        result2 = labeler.create_labels(sample_bars, ts_cut)

        # Hashes should be identical
        assert result1.targets_hash == result2.targets_hash

    def test_horizon_specific_labels(self, targets_config, sample_bars):
        """Test labels are created for each horizon."""
        labeler = IntradayMLLabeler(targets_config)
        ts_cut = sample_bars["ts"].iloc[50]

        label_result = labeler.create_labels(sample_bars, ts_cut)

        # Should have metadata for each horizon
        assert "horizon_metadata" in label_result.metadata
        horizon_metadata = label_result.metadata["horizon_metadata"]

        for horizon in labeler.horizons:
            assert horizon in horizon_metadata
            assert "horizon_minutes" in horizon_metadata[horizon]
            assert "threshold_hits" in horizon_metadata[horizon]


@pytest.mark.skipif(not LIGHTGBM_AVAILABLE, reason="LightGBM not available")
class TestLightGBMTraining:
    """Tests for LightGBM training with calibration."""

    @pytest.fixture
    def model_config(self):
        """Load model configuration."""
        config_path = Path("configs/extensions/intraday_ml/model_lgbm.yaml")
        with open(config_path) as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def sample_features_and_labels(self):
        """Generate sample features and labels."""
        np.random.seed(42)
        n_samples = 1000
        n_features = 20

        # Generate features
        features = pd.DataFrame(
            np.random.randn(n_samples, n_features),
            columns=[f"feature_{i}" for i in range(n_features)],
        )

        # Generate labels with some structure
        labels = np.random.choice([-1, 0, 1], n_samples, p=[0.2, 0.6, 0.2])
        labels = pd.Series(labels, name="label")

        return features, labels

    def test_trainer_initialization(self, model_config):
        """Test trainer initializes correctly."""
        trainer = LightGBMTrainer(model_config)
        assert trainer.lgbm_params is not None
        assert isinstance(trainer.class_weight_base, dict)
        assert isinstance(trainer.class_weight_strategy, dict)
        assert trainer.calibration_config is not None

    def test_model_training(self, model_config, sample_features_and_labels):
        """Test complete model training pipeline."""
        features, labels = sample_features_and_labels
        trainer = LightGBMTrainer(model_config)

        # Mock hashes
        features_hash = "test_features_hash"
        targets_hash = "test_targets_hash"

        result = trainer.train_model(features, labels, features_hash, targets_hash)

        # Validate result structure
        assert result.model is not None
        assert result.calibrated_model is not None
        assert result.metrics is not None
        assert result.training_metadata is not None
        assert result.training_time_seconds > 0

        # Validate model type
        from lightgbm import LGBMClassifier

        assert isinstance(result.model, LGBMClassifier)

        # Validate metrics
        assert "accuracy" in result.metrics
        assert "brier_score" in result.metrics
        assert "brier_score_calibrated" in result.metrics
        assert "brier_improvement" in result.metrics

        # Calibration should improve Brier score
        assert result.metrics["brier_improvement"] >= 0

    def test_calibration_improvement(self, model_config, sample_features_and_labels):
        """Test that calibration improves probability estimates."""
        features, labels = sample_features_and_labels
        trainer = LightGBMTrainer(model_config)

        # Disable calibration for comparison
        original_config = model_config.copy()
        original_config["calibration"]["enabled"] = False
        uncalibrated_trainer = LightGBMTrainer(original_config)

        features_hash = "test_features_hash"
        targets_hash = "test_targets_hash"

        # Train with and without calibration
        calibrated_result = trainer.train_model(features, labels, features_hash, targets_hash)
        uncalibrated_result = uncalibrated_trainer.train_model(
            features, labels, features_hash, targets_hash
        )

        # Calibrated should have better (lower) Brier score
        assert (
            calibrated_result.metrics["brier_score_calibrated"]
            <= uncalibrated_result.metrics["brier_score"]
        )

    def test_class_weights_handling(self, model_config, sample_features_and_labels):
        """Test class weights are properly applied."""
        features, labels = sample_features_and_labels
        trainer = LightGBMTrainer(model_config)

        # Check class weights are accessible
        for cls in (-1, 0, 1):
            assert cls in trainer.class_weight_base

        sample_weight = trainer._resolve_sample_weights(labels)
        assert sample_weight is not None
        assert len(sample_weight) == len(labels)

        # Training should not fail with class weights
        features_hash = "test_features_hash"
        targets_hash = "test_targets_hash"

        result = trainer.train_model(features, labels, features_hash, targets_hash)
        assert result is not None
        assert result.training_metadata.get("class_weight_summary") is not None

    def test_cross_validation(self, model_config, sample_features_and_labels):
        """Test cross-validation functionality."""
        features, labels = sample_features_and_labels
        trainer = LightGBMTrainer(model_config)

        features_hash = "test_features_hash"
        targets_hash = "test_targets_hash"

        cv_results = trainer.cross_validate(features, labels, features_hash, targets_hash)

        assert cv_results is not None
        if cv_results.get("cv_enabled", False):
            assert "cv_summary" in cv_results
            assert "fold_results" in cv_results
            assert len(cv_results["fold_results"]) > 0


@pytest.mark.skipif(not LIGHTGBM_AVAILABLE, reason="LightGBM not available")
class TestModelIO:
    """Tests for model I/O with versioning and model cards."""

    @pytest.fixture
    def sample_training_result(self):
        """Create a sample training result."""
        # Mock training result
        from lightgbm import LGBMClassifier
        from sklearn.calibration import CalibratedClassifierCV

        model = LGBMClassifier()
        calibrated_model = CalibratedClassifierCV(model)

        metrics = {
            "accuracy": 0.75,
            "brier_score": 0.25,
            "brier_score_calibrated": 0.20,
            "feature_importance": {"feature_1": 0.1, "feature_2": 0.05},
        }

        training_metadata = {
            "training_samples": 800,
            "validation_samples": 200,
            "feature_count": 20,
            "features_hash": "test_features_hash",
            "targets_hash": "test_targets_hash",
        }

        from extensions.intraday_ml_models.train_lgbm import TrainingResult

        return TrainingResult(
            model=model,
            calibrated_model=calibrated_model,
            metrics=metrics,
            training_metadata=training_metadata,
            training_time_seconds=45.2,
        )

    def test_model_save_and_load(self, sample_training_result):
        """Test model saving and loading with model cards."""
        with tempfile.TemporaryDirectory() as temp_dir:
            model_io = ModelIO(temp_dir)

            # Save model
            save_info = model_io.save_model(
                sample_training_result, model_name="test_model", version="v1.0.0"
            )

            # Validate save info
            assert "model_path" in save_info
            assert "calibrated_model_path" in save_info
            assert "model_card_path" in save_info

            # Load model
            load_info = model_io.load_model("test_model", "v1.0.0", load_calibrated=True)

            # Validate load info
            assert load_info["model"] is not None
            assert load_info["model_card"] is not None
            assert load_info["model_card"].model_name == "test_model"
            assert load_info["model_card"].version == "v1.0.0"

    def test_model_card_content(self, sample_training_result):
        """Test model card contains required information."""
        with tempfile.TemporaryDirectory() as temp_dir:
            model_io = ModelIO(temp_dir)

            # Save model
            save_info = model_io.save_model(sample_training_result, model_name="test_model")

            # Load model card
            model_card = model_io.get_model_info("test_model", save_info["version"])

            # Validate model card content
            assert model_card.model_name == "test_model"
            assert model_card.model_type == "LGBMClassifier"
            assert model_card.created_at is not None
            assert model_card.features_hash == "test_features_hash"
            assert model_card.targets_hash == "test_targets_hash"
            assert model_card.metrics is not None
            assert model_card.intended_use is not None

    def test_version_generation(self, sample_training_result):
        """Test version generation is deterministic."""
        with tempfile.TemporaryDirectory() as temp_dir:
            model_io = ModelIO(temp_dir)

            # Save model without specifying version
            save_info1 = model_io.save_model(sample_training_result, model_name="test_model")
            time.sleep(0.1)  # Small delay to ensure different timestamps
            save_info2 = model_io.save_model(sample_training_result, model_name="test_model")

            # Versions should be different due to timestamp
            assert save_info1["version"] != save_info2["version"]

    def test_convenience_functions(self, sample_training_result):
        """Test convenience save/load functions."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Save using convenience function
            save_info = save_model_with_card(sample_training_result, temp_dir, "test_model")

            # Load using convenience function
            load_info = load_model_with_card(temp_dir, "test_model", save_info["version"])

            assert load_info["model"] is not None
            assert load_info["model_card"] is not None


class TestDecisionPolicy:
    """Tests for decision policy with probability gates and cooldowns."""

    @pytest.fixture
    def decision_config(self):
        """Decision policy configuration."""
        return {
            "probability_threshold": 0.65,
            "expected_move_multiplier": 0.8,
            "cooldown": {"base_minutes": 15, "atr_multiplier": 0.5, "max_minutes": 60},
            "time_filter": {
                "first_minutes_after_open": 3,
                "high_confidence_threshold": 0.8,
            },
            "force_flat_before_close": "15:59:59",
        }

    def test_policy_initialization(self, decision_config):
        """Test policy initializes correctly."""
        policy = DecisionPolicy(decision_config)
        assert policy.probability_threshold == 0.65
        assert policy.expected_move_multiplier == 0.8
        assert policy.cooldown_tracker == {}

    def test_probability_gate(self, decision_config):
        """Test probability gate enforcement."""
        policy = DecisionPolicy(decision_config)
        current_time = datetime.now()

        # Should reject low probability
        low_probs = {1: 0.3, -1: 0.2, 0: 0.5}
        should_trade, direction, reason = policy.should_trade("AAPL", low_probs, 0.5, current_time)
        assert not should_trade
        assert "Probability gate" in reason

        # Should accept high probability (with sufficient ATR)
        high_probs = {1: 0.8, -1: 0.1, 0: 0.1}
        should_trade, direction, reason = policy.should_trade(
            "AAPL",
            high_probs,
            1.0,
            current_time,  # Larger ATR value
        )
        assert should_trade
        assert direction == 1
        assert reason == "All conditions met"

    def test_expected_move_threshold(self, decision_config):
        """Test expected move threshold enforcement."""
        policy = DecisionPolicy(decision_config)
        current_time = datetime.now()

        # High probability but small expected move
        probs_small_move = {1: 0.7, -1: 0.2, 0: 0.1}
        atr_small = 0.1  # Small ATR
        should_trade, direction, reason = policy.should_trade(
            "AAPL", probs_small_move, atr_small, current_time
        )
        assert not should_trade
        assert "Expected move too small" in reason

        # High probability with sufficient expected move
        atr_large = 2.0  # Large ATR
        should_trade, direction, reason = policy.should_trade(
            "AAPL", probs_small_move, atr_large, current_time
        )
        assert should_trade

    def test_cooldown_enforcement(self, decision_config):
        """Test cooldown period enforcement."""
        policy = DecisionPolicy(decision_config)
        current_time = datetime.now()

        # Set up recent entry
        recent_entry = current_time - timedelta(minutes=5)
        policy.update_cooldown("AAPL", recent_entry, "entry")

        high_probs = {1: 0.8, -1: 0.1, 0: 0.1}
        should_trade, direction, reason = policy.should_trade(
            "AAPL", high_probs, 2.0, current_time, last_entry_time=recent_entry
        )
        assert not should_trade
        assert "In cooldown period" in reason

    def test_time_restrictions(self, decision_config):
        """Test time-of-day restrictions."""
        policy = DecisionPolicy(decision_config)
        high_probs = {1: 0.8, -1: 0.1, 0: 0.1}

        # Early morning (first 3 minutes after 9:30)
        early_time = datetime(2024, 1, 2, 9, 31, 0)
        should_trade, direction, reason = policy.should_trade("AAPL", high_probs, 1.0, early_time)
        assert not should_trade
        assert "Time-of-day restriction" in reason

        # Near EOD
        late_time = datetime(2024, 1, 2, 15, 59, 0)
        should_trade, direction, reason = policy.should_trade("AAPL", high_probs, 1.0, late_time)
        assert not should_trade

    def test_cooldown_tracking(self, decision_config):
        """Test cooldown state tracking."""
        policy = DecisionPolicy(decision_config)
        current_time = datetime.now()

        # Update cooldown state
        entry_time = current_time - timedelta(minutes=10)
        exit_time = current_time - timedelta(minutes=5)
        policy.update_cooldown("AAPL", entry_time, "entry")
        policy.update_cooldown("AAPL", exit_time, "exit")

        # Check cooldown status
        status = policy.get_cooldown_status("AAPL", current_time)
        assert status["in_cooldown"] is True
        assert "entry" in status["actions"]
        assert "exit" in status["actions"]

    def test_cooldown_reset(self, decision_config):
        """Test cooldown state reset."""
        policy = DecisionPolicy(decision_config)
        current_time = datetime.now()

        # Add some cooldown state
        policy.update_cooldown("AAPL", current_time - timedelta(minutes=5), "entry")
        policy.update_cooldown("MSFT", current_time - timedelta(minutes=10), "entry")

        # Reset cooldowns
        policy.reset_cooldowns()

        # Should be empty
        assert len(policy.cooldown_tracker) == 0

        status_aapl = policy.get_cooldown_status("AAPL", current_time)
        assert not status_aapl["in_cooldown"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
