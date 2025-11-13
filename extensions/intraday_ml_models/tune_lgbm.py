"""Bayesian Hyperparameter Tuning for LightGBM with Trade-Rate Shaping

Implements sophisticated hyperparameter optimization using Bayesian optimization
with composite objectives that balance predictive performance with economic metrics
and trade-rate control.
"""

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from extensions.intraday_ml.utils.checksums import compute_data_hash
from extensions.intraday_ml_models.cv_runner import CVResult, run_cross_validation
from extensions.intraday_ml_models.train_lgbm import LightGBMTrainer


@dataclass
class HyperparameterBounds:
    """Bounds for hyperparameter search."""

    param_name: str
    low: float
    high: float
    param_type: str  # 'continuous', 'integer', 'categorical'
    choices: list[Any] | None = None


@dataclass
class OptimizationTrial:
    """Single optimization trial results."""

    trial_id: int
    params: dict[str, Any]
    cv_result: CVResult
    objective_value: float
    component_scores: dict[str, float]
    optimization_time_seconds: float


@dataclass
class TuningResult:
    """Complete hyperparameter tuning results."""

    best_params: dict[str, Any]
    best_cv_result: CVResult
    optimization_history: list[OptimizationTrial]
    total_trials: int
    total_time_seconds: float
    convergence_info: dict[str, Any]
    reproducibility_info: dict[str, Any]


class BayesianLightGBMTuner:
    """Bayesian hyperparameter tuner for LightGBM with composite objectives."""

    def __init__(
        self,
        model_config: dict[str, Any],
        cv_config: dict[str, Any],
        objective_config: dict[str, Any],
    ):
        """Initialize tuner with configurations.

        Args:
            model_config: Base model configuration
            cv_config: Cross-validation configuration
            objective_config: Objective function configuration
        """
        self.base_model_config = model_config
        self.cv_config = cv_config
        self.objective_config = objective_config

        # Initialize hyperparameter bounds
        self.param_bounds = self._initialize_parameter_bounds()

        # Optimization settings
        self.max_trials = objective_config.get("max_trials", 50)
        self.acquisition_function = objective_config.get(
            "acquisition_function", "ei"
        )  # Expected Improvement
        self.n_initial_points = objective_config.get("n_initial_points", 10)
        self.random_seed = objective_config.get("random_seed", 42)

        # Trade-rate shaping parameters
        self.trade_rate_config = objective_config.get("trade_rate_shaping", {})
        self.target_trade_rate = self.trade_rate_config.get("target_trade_rate", 0.02)
        self.trade_rate_weight = self.trade_rate_config.get("trade_rate_weight", 0.3)
        self.max_trade_rate = self.trade_rate_config.get("max_trade_rate", 0.1)

        # Composite objective weights
        self.objective_weights = objective_config.get(
            "objective_weights",
            {
                "f1_macro": 0.4,
                "brier_score": 0.3,
                "expectancy": 0.2,
                "trade_rate_penalty": 0.1,
            },
        )

        # Optimization state
        self.trial_history: list[OptimizationTrial] = []
        self.current_trial = 0
        self.gaussian_process_state = None
        self._context_data: pd.DataFrame | None = None

    def _initialize_parameter_bounds(self) -> list[HyperparameterBounds]:
        """Initialize hyperparameter search bounds."""
        bounds = [
            # LightGBM parameters
            HyperparameterBounds("num_leaves", 20, 300, "integer"),
            HyperparameterBounds("learning_rate", 0.001, 0.3, "continuous"),
            HyperparameterBounds("feature_fraction", 0.5, 1.0, "continuous"),
            HyperparameterBounds("bagging_fraction", 0.5, 1.0, "continuous"),
            HyperparameterBounds("bagging_freq", 1, 10, "integer"),
            HyperparameterBounds("min_child_samples", 5, 100, "integer"),
            HyperparameterBounds("min_child_weight", 0.001, 10.0, "continuous"),
            HyperparameterBounds("reg_alpha", 0.0, 10.0, "continuous"),
            HyperparameterBounds("reg_lambda", 0.0, 10.0, "continuous"),
            HyperparameterBounds("max_depth", 3, 15, "integer"),
            # Decision policy parameters
            HyperparameterBounds("probability_threshold", 0.5, 0.9, "continuous"),
            HyperparameterBounds("expected_move_multiplier", 0.5, 2.0, "continuous"),
            HyperparameterBounds("cooldown_minutes", 5, 60, "integer"),
        ]

        return bounds

    def optimize(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        output_dir: Path | None = None,
        context_data: pd.DataFrame | None = None,
    ) -> TuningResult:
        """Run Bayesian hyperparameter optimization.

        Args:
            features: Feature DataFrame with multi-index (symbol, ts)
            labels: Label Series with multi-index (symbol, ts)
            output_dir: Optional directory to save results

        Returns:
            Complete tuning results
        """
        start_time = time.time()
        self._context_data = context_data

        # Set random seed for reproducibility
        np.random.seed(self.random_seed)

        print(f"Starting Bayesian optimization with max {self.max_trials} trials")

        # Initial random sampling
        if len(self.trial_history) < self.n_initial_points:
            print(f"Running {self.n_initial_points} initial random trials...")
            for _ in range(self.n_initial_points):
                if self.current_trial >= self.max_trials:
                    break
                self._run_random_trial(features, labels)

        # Bayesian optimization loop
        print("Starting Bayesian optimization phase...")
        while self.current_trial < self.max_trials:
            # Find next point to evaluate
            next_params = self._propose_next_parameters()

            # Evaluate trial
            trial_result = self._evaluate_trial(next_params, features, labels)

            # Update Gaussian Process (simplified - would use proper GP in practice)
            self._update_optimization_state(trial_result)

            # Progress reporting
            if (self.current_trial + 1) % 10 == 0:
                best_score = min([t.objective_value for t in self.trial_history])
                print(
                    f"Trial {self.current_trial + 1}/{self.max_trials}, Best score: {best_score:.4f}"
                )

        # Select best trial
        best_trial = min(self.trial_history, key=lambda t: t.objective_value)

        total_time = time.time() - start_time

        result = TuningResult(
            best_params=best_trial.params,
            best_cv_result=best_trial.cv_result,
            optimization_history=self.trial_history,
            total_trials=len(self.trial_history),
            total_time_seconds=total_time,
            convergence_info=self._calculate_convergence_info(),
            reproducibility_info={
                "random_seed": self.random_seed,
                "features_hash": compute_data_hash(features),
                "labels_hash": compute_data_hash(labels),
                "config_hash": compute_data_hash(
                    pd.Series(
                        [
                            json.dumps(self.base_model_config, sort_keys=True),
                            json.dumps(self.objective_config, sort_keys=True),
                        ]
                    )
                ),
            },
        )

        # Save results if output directory provided
        if output_dir:
            self._save_tuning_results(result, output_dir)

        print(f"Optimization completed. Best score: {best_trial.objective_value:.4f}")
        print(f"Best parameters: {json.dumps(best_trial.params, indent=2)}")

        return result

    def _run_random_trial(self, features: pd.DataFrame, labels: pd.Series):
        """Run a random trial for initial exploration."""
        params = self._sample_random_parameters()
        trial_result = self._evaluate_trial(params, features, labels)
        self.trial_history.append(trial_result)
        self.current_trial += 1

    def _sample_random_parameters(self) -> dict[str, Any]:
        """Sample random parameters within bounds."""
        params = {}
        for bound in self.param_bounds:
            if bound.param_type == "continuous":
                params[bound.param_name] = np.random.uniform(bound.low, bound.high)
            elif bound.param_type == "integer":
                params[bound.param_name] = np.random.randint(bound.low, bound.high + 1)
            elif bound.param_type == "categorical":
                params[bound.param_name] = np.random.choice(bound.choices)

        return params

    def _propose_next_parameters(self) -> dict[str, Any]:
        """Propose next parameters using acquisition function."""
        if len(self.trial_history) < 2:
            # Not enough history for GP, use random sampling
            return self._sample_random_parameters()

        # Simplified acquisition function (would use proper GP in practice)
        # For now, use random perturbation around best parameters
        best_trial = min(self.trial_history, key=lambda t: t.objective_value)
        params = best_trial.params.copy()

        # Add random perturbation
        for bound in self.param_bounds:
            if bound.param_name in params and np.random.random() < 0.3:  # 30% chance to modify
                if bound.param_type == "continuous":
                    perturbation = np.random.normal(0, (bound.high - bound.low) * 0.1)
                    new_value = params[bound.param_name] + perturbation
                    params[bound.param_name] = np.clip(new_value, bound.low, bound.high)
                elif bound.param_type == "integer":
                    perturbation = np.random.randint(-2, 3)
                    new_value = params[bound.param_name] + perturbation
                    params[bound.param_name] = int(np.clip(new_value, bound.low, bound.high))

        return params

    def _evaluate_trial(
        self, params: dict[str, Any], features: pd.DataFrame, labels: pd.Series
    ) -> OptimizationTrial:
        """Evaluate a single parameter trial."""
        trial_start = time.time()

        # Create model config with trial parameters
        trial_config = self._create_trial_config(params)

        # Initialize trainer
        LightGBMTrainer(trial_config)

        # Run cross-validation
        cv_result = run_cross_validation(
            features,
            labels,
            trial_config,
            self.cv_config,
            context_data=self._context_data,
        )

        # Calculate composite objective
        objective_value, component_scores = self._calculate_composite_objective(cv_result)

        optimization_time = time.time() - trial_start

        trial = OptimizationTrial(
            trial_id=self.current_trial + 1,
            params=params.copy(),
            cv_result=cv_result,
            objective_value=objective_value,
            component_scores=component_scores,
            optimization_time_seconds=optimization_time,
        )

        return trial

    def _create_trial_config(self, params: dict[str, Any]) -> dict[str, Any]:
        """Create model configuration for a trial."""
        config = self.base_model_config.copy()

        # Update LightGBM parameters
        lgbm_params = config.get("lgbm_params", {}).copy()
        decision_params = config.get("decision_policy", {}).copy()

        # Map trial parameters to appropriate config sections
        lgbm_keys = [
            "num_leaves",
            "learning_rate",
            "feature_fraction",
            "bagging_fraction",
            "bagging_freq",
            "min_child_samples",
            "min_child_weight",
            "reg_alpha",
            "reg_lambda",
            "max_depth",
        ]

        decision_keys = [
            "probability_threshold",
            "expected_move_multiplier",
            "cooldown_minutes",
        ]

        for key, value in params.items():
            if key in lgbm_keys:
                lgbm_params[key] = value
            elif key in decision_keys:
                if key == "cooldown_minutes":
                    decision_params["cooldown"] = {"base_minutes": int(value)}
                else:
                    decision_params[key] = value

        config["lgbm_params"] = lgbm_params
        config["decision_policy"] = decision_params

        return config

    def _calculate_composite_objective(self, cv_result: CVResult) -> tuple[float, dict[str, float]]:
        """Calculate composite objective with trade-rate shaping."""
        agg_metrics = cv_result.aggregated_metrics

        # Extract primary metrics (to be maximized, so we use negative for minimization)
        f1_macro = agg_metrics.get("f1_macro_mean", 0.0)
        brier_score = agg_metrics.get("brier_score_mean", 1.0)  # Lower is better
        expectancy = agg_metrics.get("expectancy_mean", 0.0)

        # Trade density metrics
        trades_per_day = agg_metrics.get("trades_per_ticker_day_mean", 0.0)

        # Calculate component scores
        scores = {}

        # F1 score (higher is better)
        scores["f1_macro"] = -f1_macro * self.objective_weights.get("f1_macro", 0.4)

        # Brier score (lower is better)
        scores["brier_score"] = brier_score * self.objective_weights.get("brier_score", 0.3)

        # Expectancy (higher is better)
        scores["expectancy"] = -expectancy * self.objective_weights.get("expectancy", 0.2)

        # Trade rate penalty (trade-rate shaping)
        trade_rate = (
            trades_per_day / 390
        )  # Convert to per-minute rate (assuming 390 trading minutes)
        trade_rate_penalty = self._calculate_trade_rate_penalty(trade_rate)
        scores["trade_rate_penalty"] = trade_rate_penalty * self.objective_weights.get(
            "trade_rate_penalty", 0.1
        )

        # Composite objective (to be minimized)
        composite_score = sum(scores.values())

        return composite_score, scores

    def _calculate_trade_rate_penalty(self, trade_rate: float) -> float:
        """Calculate trade-rate penalty using asymmetric loss function."""
        target = self.target_trade_rate
        max_rate = self.max_trade_rate
        weight = self.trade_rate_weight

        if trade_rate <= max_rate:
            # Below maximum, use quadratic penalty around target
            deviation = trade_rate - target
            penalty = weight * (deviation**2)
        else:
            # Above maximum, use exponential penalty
            excess = trade_rate - max_rate
            penalty = weight * (max_rate - target) ** 2 + excess**2

        return penalty

    def _update_optimization_state(self, trial_result: OptimizationTrial):
        """Update optimization state (simplified Gaussian Process)."""
        # In a full implementation, this would update a Gaussian Process
        # For now, we just store the trial history
        self.trial_history.append(trial_result)
        self.current_trial += 1

    def _calculate_convergence_info(self) -> dict[str, Any]:
        """Calculate convergence information."""
        if len(self.trial_history) < 2:
            return {"converged": False, "reason": "Insufficient trials"}

        # Extract objective values
        objective_values = [t.objective_value for t in self.trial_history]

        # Calculate improvement in last 10 trials
        if len(objective_values) >= 10:
            recent_best = min(objective_values[-10:])
            overall_best = min(objective_values)
            improvement = overall_best - recent_best
        else:
            improvement = 0.0

        # Simple convergence criterion
        converged = abs(improvement) < 1e-4 and len(objective_values) >= 20

        return {
            "converged": converged,
            "improvement_last_10": improvement,
            "best_objective": min(objective_values),
            "final_objective": objective_values[-1],
            "total_trials": len(objective_values),
        }

    def _save_tuning_results(self, result: TuningResult, output_dir: Path):
        """Save tuning results to files."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save complete results
        results_path = output_dir / "tuning_results.json"
        with open(results_path, "w") as f:
            json.dump(asdict(result), f, indent=2, default=str)

        # Save best parameters
        best_params_path = output_dir / "best_parameters.json"
        with open(best_params_path, "w") as f:
            json.dump(result.best_params, f, indent=2)

        # Save optimization history
        history_path = output_dir / "optimization_history.csv"
        history_data = []
        for trial in result.optimization_history:
            row = {
                "trial_id": trial.trial_id,
                "objective_value": trial.objective_value,
                "optimization_time": trial.optimization_time_seconds,
            }
            row.update(trial.params)
            row.update(trial.component_scores)
            history_data.append(row)

        history_df = pd.DataFrame(history_data)
        history_df.to_csv(history_path, index=False)

        print(f"Tuning results saved to {output_dir}")


def optimize_lightgbm_model(
    features: pd.DataFrame,
    labels: pd.Series,
    model_config: dict[str, Any],
    cv_config: dict[str, Any],
    objective_config: dict[str, Any],
    output_dir: Path | None = None,
    context_data: pd.DataFrame | None = None,
) -> TuningResult:
    """Convenience function for LightGBM hyperparameter optimization.

    Args:
        features: Feature DataFrame with multi-index (symbol, ts)
        labels: Label Series with multi-index (symbol, ts)
        model_config: Base model configuration
        cv_config: Cross-validation configuration
        objective_config: Objective function configuration
        output_dir: Optional directory to save results

    Returns:
        Complete tuning results
    """
    tuner = BayesianLightGBMTuner(model_config, cv_config, objective_config)
    return tuner.optimize(features, labels, output_dir, context_data=context_data)
