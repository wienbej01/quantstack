"""Tests for LightGBM Hyperparameter Tuning

Tests Bayesian hyperparameter optimization with composite objectives
and trade-rate shaping functionality.
"""

import numpy as np
import pandas as pd
import pytest

from extensions.intraday_ml_models.tune_lgbm import (
    BayesianLightGBMTuner,
    HyperparameterBounds,
    OptimizationTrial,
    TuningResult,
    optimize_lightgbm_model,
)


class TestHyperparameterBounds:
    """Test HyperparameterBounds dataclass."""

    def test_continuous_bounds(self):
        """Test continuous parameter bounds."""
        bounds = HyperparameterBounds(
            param_name="learning_rate", low=0.001, high=0.3, param_type="continuous"
        )

        assert bounds.param_name == "learning_rate"
        assert bounds.low == 0.001
        assert bounds.high == 0.3
        assert bounds.param_type == "continuous"

    def test_integer_bounds(self):
        """Test integer parameter bounds."""
        bounds = HyperparameterBounds(
            param_name="num_leaves", low=20, high=300, param_type="integer"
        )

        assert bounds.param_type == "integer"
        assert bounds.low == 20
        assert bounds.high == 300

    def test_categorical_bounds(self):
        """Test categorical parameter bounds."""
        bounds = HyperparameterBounds(
            param_name="boosting_type",
            low=0,
            high=2,
            param_type="categorical",
            choices=["gbdt", "dart", "goss"],
        )

        assert bounds.param_type == "categorical"
        assert bounds.choices == ["gbdt", "dart", "goss"]


class TestOptimizationTrial:
    """Test OptimizationTrial dataclass."""

    def test_optimization_trial_creation(self):
        """Test OptimizationTrial creation."""
        trial = OptimizationTrial(
            trial_id=1,
            params={"learning_rate": 0.1, "num_leaves": 50},
            cv_result=None,  # Would be actual CV result in practice
            objective_value=0.25,
            component_scores={"f1_macro": -0.15, "brier_score": 0.08},
            optimization_time_seconds=45.0,
        )

        assert trial.trial_id == 1
        assert trial.params["learning_rate"] == 0.1
        assert trial.objective_value == 0.25
        assert trial.component_scores["f1_macro"] == -0.15


class TestBayesianLightGBMTuner:
    """Test BayesianLightGBMTuner class."""

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
            "calibration": {"enabled": True, "method": "sigmoid"},
        }

    @pytest.fixture
    def cv_config(self):
        """Sample CV configuration."""
        return {
            "n_folds": 3,
            "purge_days": 2,
            "embargo_days": 3,
            "validation_method": "purged_cv",
            "min_observations_per_fold": 50,
        }

    @pytest.fixture
    def objective_config(self):
        """Sample objective configuration."""
        return {
            "max_trials": 10,
            "n_initial_points": 3,
            "acquisition_function": "ei",
            "random_seed": 42,
            "objective_weights": {
                "f1_macro": 0.4,
                "brier_score": 0.3,
                "expectancy": 0.2,
                "trade_rate_penalty": 0.1,
            },
            "trade_rate_shaping": {
                "target_trade_rate": 0.02,
                "trade_rate_weight": 0.3,
                "max_trade_rate": 0.1,
            },
        }

    @pytest.fixture
    def sample_data(self):
        """Create sample data for testing."""
        symbols = ["AAPL", "MSFT"]
        dates = pd.date_range("2024-01-01", periods=50, freq="D")

        index = pd.MultiIndex.from_product([symbols, dates], names=["symbol", "ts"])

        np.random.seed(42)
        features_data = np.random.randn(len(index), 3)
        features = pd.DataFrame(
            features_data, index=index, columns=["feature_1", "feature_2", "feature_3"]
        )

        targets = pd.Series(
            np.random.choice([-1, 0, 1], size=len(index)), index=index, name="target"
        )

        return features, targets

    def test_tuner_initialization(self, model_config, cv_config, objective_config):
        """Test tuner initialization."""
        tuner = BayesianLightGBMTuner(model_config, cv_config, objective_config)

        assert tuner.base_model_config == model_config
        assert tuner.cv_config == cv_config
        assert tuner.objective_config == objective_config
        assert tuner.max_trials == 10
        assert tuner.n_initial_points == 3
        assert tuner.random_seed == 42

        # Check parameter bounds
        assert len(tuner.param_bounds) > 0
        assert any(b.param_name == "learning_rate" for b in tuner.param_bounds)
        assert any(b.param_name == "num_leaves" for b in tuner.param_bounds)

        # Check trade-rate shaping parameters
        assert tuner.target_trade_rate == 0.02
        assert tuner.trade_rate_weight == 0.3
        assert tuner.max_trade_rate == 0.1

    def test_initialize_parameter_bounds(
        self, model_config, cv_config, objective_config
    ):
        """Test parameter bounds initialization."""
        tuner = BayesianLightGBMTuner(model_config, cv_config, objective_config)

        bounds = tuner.param_bounds

        # Check that we have the expected parameter types
        param_names = [b.param_name for b in bounds]
        expected_params = [
            "num_leaves",
            "learning_rate",
            "feature_fraction",
            "bagging_fraction",
            "probability_threshold",
        ]

        for param in expected_params:
            assert param in param_names

        # Check bounds structure
        for bound in bounds:
            assert hasattr(bound, "param_name")
            assert hasattr(bound, "low")
            assert hasattr(bound, "high")
            assert hasattr(bound, "param_type")
            assert bound.param_type in ["continuous", "integer", "categorical"]

    def test_sample_random_parameters(self, model_config, cv_config, objective_config):
        """Test random parameter sampling."""
        tuner = BayesianLightGBMTuner(model_config, cv_config, objective_config)

        # Set seed for reproducibility
        np.random.seed(42)

        params = tuner._sample_random_parameters()

        assert isinstance(params, dict)
        assert len(params) > 0

        # Check that parameters are within bounds
        for bound in tuner.param_bounds:
            if bound.param_name in params:
                value = params[bound.param_name]
                if bound.param_type == "continuous":
                    assert bound.low <= value <= bound.high
                elif bound.param_type == "integer":
                    assert bound.low <= value <= bound.high
                    assert isinstance(value, (int, np.integer))

    def test_create_trial_config(self, model_config, cv_config, objective_config):
        """Test trial configuration creation."""
        tuner = BayesianLightGBMTuner(model_config, cv_config, objective_config)

        trial_params = {
            "learning_rate": 0.05,
            "num_leaves": 50,
            "probability_threshold": 0.7,
            "cooldown_minutes": 15,
        }

        trial_config = tuner._create_trial_config(trial_params)

        # Check that base config is preserved
        assert "lgbm_params" in trial_config
        assert "decision_policy" in trial_config

        # Check that trial parameters are applied
        assert trial_config["lgbm_params"]["learning_rate"] == 0.05
        assert trial_config["lgbm_params"]["num_leaves"] == 50
        assert trial_config["decision_policy"]["probability_threshold"] == 0.7
        assert trial_config["decision_policy"]["cooldown"]["base_minutes"] == 15

    def test_calculate_composite_objective(
        self, model_config, cv_config, objective_config
    ):
        """Test composite objective calculation."""
        tuner = BayesianLightGBMTuner(model_config, cv_config, objective_config)

        # Create mock CV result
        from extensions.intraday_ml_models.cv_runner import CVResult

        mock_cv_result = CVResult(
            cv_config={},
            splits=[],
            fold_metrics=[],
            aggregated_metrics={
                "f1_macro_mean": 0.75,
                "brier_score_mean": 0.25,
                "expectancy_mean": 0.1,
                "trades_per_ticker_day_mean": 8.0,  # ~0.02 per minute
            },
            stability_metrics={},
            calibration_metrics={},
            reproducibility_info={},
            total_time_seconds=60.0,
        )

        objective_value, component_scores = tuner._calculate_composite_objective(
            mock_cv_result
        )

        assert isinstance(objective_value, float)
        assert isinstance(component_scores, dict)

        # Check component scores
        expected_components = [
            "f1_macro",
            "brier_score",
            "expectancy",
            "trade_rate_penalty",
        ]
        for component in expected_components:
            assert component in component_scores

        # Check that objective is weighted sum of components
        calculated_objective = sum(component_scores.values())
        assert np.isclose(objective_value, calculated_objective)

    def test_calculate_trade_rate_penalty(
        self, model_config, cv_config, objective_config
    ):
        """Test trade rate penalty calculation."""
        tuner = BayesianLightGBMTuner(model_config, cv_config, objective_config)

        # Test with trade rate at target
        penalty_at_target = tuner._calculate_trade_rate_penalty(tuner.target_trade_rate)
        assert penalty_at_target >= 0

        # Test with trade rate below maximum
        penalty_below_max = tuner._calculate_trade_rate_penalty(0.05)
        assert penalty_below_max >= 0

        # Test with trade rate above maximum
        penalty_above_max = tuner._calculate_trade_rate_penalty(0.15)
        assert penalty_above_max >= penalty_below_max  # Should be higher penalty

        # Test with very high trade rate
        penalty_very_high = tuner._calculate_trade_rate_penalty(0.5)
        assert penalty_very_high > penalty_above_max

    def test_propose_next_parameters_random_phase(
        self, model_config, cv_config, objective_config
    ):
        """Test parameter proposal in random phase."""
        tuner = BayesianLightGBMTuner(model_config, cv_config, objective_config)

        # With no history, should return random parameters
        params = tuner._propose_next_parameters()
        assert isinstance(params, dict)
        assert len(params) > 0

    def test_propose_next_parameters_with_history(
        self, model_config, cv_config, objective_config
    ):
        """Test parameter proposal with optimization history."""
        tuner = BayesianLightGBMTuner(model_config, cv_config, objective_config)

        # Add mock trial history
        from extensions.intraday_ml_models.cv_runner import CVResult

        mock_cv_result = CVResult(
            cv_config={},
            splits=[],
            fold_metrics=[],
            aggregated_metrics={"f1_macro_mean": 0.7},
            stability_metrics={},
            calibration_metrics={},
            reproducibility_info={},
            total_time_seconds=60.0,
        )

        mock_trial = OptimizationTrial(
            trial_id=1,
            params={"learning_rate": 0.1, "num_leaves": 50},
            cv_result=mock_cv_result,
            objective_value=0.3,
            component_scores={"f1_macro": -0.2, "brier_score": 0.1},
            optimization_time_seconds=30.0,
        )

        tuner.trial_history = [mock_trial]

        # Set seed for reproducibility
        np.random.seed(42)

        params = tuner._propose_next_parameters()
        assert isinstance(params, dict)
        assert len(params) > 0

    def test_calculate_convergence_info(
        self, model_config, cv_config, objective_config
    ):
        """Test convergence information calculation."""
        tuner = BayesianLightGBMTuner(model_config, cv_config, objective_config)

        # Test with insufficient trials
        convergence = tuner._calculate_convergence_info()
        assert convergence["converged"] is False
        assert "reason" in convergence

        # Test with sufficient trials
        from extensions.intraday_ml_models.cv_runner import CVResult

        mock_cv_result = CVResult(
            cv_config={},
            splits=[],
            fold_metrics=[],
            aggregated_metrics={"f1_macro_mean": 0.7},
            stability_metrics={},
            calibration_metrics={},
            reproducibility_info={},
            total_time_seconds=60.0,
        )

        # Add mock trials
        for i in range(25):
            trial = OptimizationTrial(
                trial_id=i + 1,
                params={"learning_rate": 0.1},
                cv_result=mock_cv_result,
                objective_value=0.3 + i * 0.001,  # Small improvement
                component_scores={},
                optimization_time_seconds=30.0,
            )
            tuner.trial_history.append(trial)

        convergence = tuner._calculate_convergence_info()
        assert "converged" in convergence
        assert "best_objective" in convergence
        assert "final_objective" in convergence
        assert convergence["total_trials"] == 25

    @pytest.mark.skip(reason="Integration test with actual optimization")
    def test_optimize_integration(
        self, model_config, cv_config, objective_config, sample_data
    ):
        """Integration test for complete optimization."""
        features, targets = sample_data
        BayesianLightGBMTuner(model_config, cv_config, objective_config)

        # This would run the full optimization process
        # Skipping for unit test efficiency
        pass

    @pytest.mark.skip(reason="Integration test with actual optimization")
    def test_optimize_lightgbm_model_convenience(
        self, model_config, cv_config, objective_config, sample_data
    ):
        """Test convenience function for optimization."""
        features, targets = sample_data

        # Test function signature
        assert callable(optimize_lightgbm_model)

        # Note: Full integration test would be computationally expensive


class TestTuningResult:
    """Test TuningResult dataclass."""

    def test_tuning_result_creation(self):
        """Test TuningResult creation."""
        result = TuningResult(
            best_params={"learning_rate": 0.1},
            best_cv_result=None,
            optimization_history=[],
            total_trials=10,
            total_time_seconds=300.0,
            convergence_info={"converged": True},
            reproducibility_info={"random_seed": 42},
        )

        assert result.best_params["learning_rate"] == 0.1
        assert result.total_trials == 10
        assert result.total_time_seconds == 300.0
        assert result.convergence_info["converged"] is True
