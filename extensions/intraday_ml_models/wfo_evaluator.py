"""Walk-Forward Optimization (WFO) Evaluator for Intraday ML Models

Implements rolling walk-forward evaluation with KPI tracking, regime analysis,
and comprehensive performance monitoring for production readiness assessment.
"""

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from extensions.intraday_ml_models.cv_runner import run_cross_validation
from extensions.intraday_ml_models.model_io import ModelIO
from extensions.intraday_ml_models.train_lgbm import LightGBMTrainer, TrainingResult


@dataclass
class WFOPeriod:
    """Single WFO period configuration."""

    period_id: int
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime
    oos_start: datetime
    oos_end: datetime
    train_symbols: list[str]
    oos_symbols: list[str]
    train_size: int
    oos_size: int


@dataclass
class WFOPeriodResults:
    """Results for a single WFO period."""

    period: WFOPeriod
    training_result: TrainingResult
    cv_results: dict[str, Any]  # Cross-validation results
    oos_predictions: pd.DataFrame
    oos_metrics: dict[str, Any]
    model_path: str
    model_card_path: str
    training_time_seconds: float
    inference_time_seconds: float


@dataclass
class WFOAggregatedResults:
    """Aggregated results across all WFO periods."""

    wfo_config: dict[str, Any]
    periods: list[WFOPeriod]
    period_results: list[WFOPeriodResults]
    overall_metrics: dict[str, Any]
    temporal_stability: dict[str, Any]
    regime_analysis: dict[str, Any]
    model_evolution: dict[str, Any]
    kpi_summary: dict[str, Any]
    total_time_seconds: float
    reproducibility_info: dict[str, Any]


class WalkForwardEvaluator:
    """Evaluates models using walk-forward optimization with comprehensive KPI tracking."""

    def __init__(self, wfo_config: dict[str, Any], model_dir: Path):
        """Initialize WFO evaluator.

        Args:
            wfo_config: WFO configuration
            model_dir: Directory to save models
        """
        self.config = wfo_config
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)

        # WFO schedule parameters
        self.train_months = wfo_config.get("train_months", 12)
        self.validation_months = wfo_config.get("validation_months", 1)
        self.oos_months = wfo_config.get("oos_months", 1)
        self.step_size_months = wfo_config.get("step_size_months", 1)
        self.window_type = wfo_config.get("window_type", "expanding")
        self.start_date = pd.to_datetime(wfo_config.get("start_date", "2024-01-01"))

        # Data quality controls
        self.min_observations_per_period = wfo_config.get("min_observations_per_period", 5000)
        self.min_symbols_per_period = wfo_config.get("min_symbols_per_period", 5)

        # Model persistence
        self.model_io = ModelIO(self.model_dir, wfo_config)

        # KPI tracking
        self.kpi_config = wfo_config.get("kpi_tracking", {})

    def create_wfo_periods(self, data: pd.DataFrame) -> list[WFOPeriod]:
        """Create walk-forward optimization periods.

        Args:
            data: Input data with multi-index (symbol, ts)

        Returns:
            List of WFO periods
        """
        # Extract unique dates and sort
        dates = data.index.get_level_values("ts").normalize().unique()
        dates = sorted(dates)

        # Find start index
        start_idx = 0
        for i, date in enumerate(dates):
            if date >= self.start_date:
                start_idx = i
                break

        periods = []
        period_id = 1

        # Calculate period lengths in months
        train_length = timedelta(days=self.train_months * 30)
        validation_length = timedelta(days=self.validation_months * 30)
        oos_length = timedelta(days=self.oos_months * 30)
        step_length = timedelta(days=self.step_size_months * 30)

        current_start_idx = start_idx

        while True:
            # Calculate period boundaries
            train_start_date = dates[current_start_idx]

            # Find train end date
            train_target_date = train_start_date + train_length
            train_end_idx = self._find_date_index(dates, train_target_date, current_start_idx)
            if train_end_idx is None:
                break
            train_end_date = dates[train_end_idx]

            # Validation period
            val_start_date = train_end_date + timedelta(days=1)
            val_target_date = val_start_date + validation_length
            val_end_idx = self._find_date_index(dates, val_target_date, train_end_idx + 1)
            if val_end_idx is None:
                break
            val_end_date = dates[val_end_idx]

            # Out-of-sample period
            oos_start_date = val_end_date + timedelta(days=1)
            oos_target_date = oos_start_date + oos_length
            oos_end_idx = self._find_date_index(dates, oos_target_date, val_end_idx + 1)
            if oos_end_idx is None:
                break
            oos_end_date = dates[oos_end_idx]

            # Get data for each period
            train_data = data[
                (data.index.get_level_values("ts").normalize() >= train_start_date)
                & (data.index.get_level_values("ts").normalize() <= train_end_date)
            ]
            oos_data = data[
                (data.index.get_level_values("ts").normalize() >= oos_start_date)
                & (data.index.get_level_values("ts").normalize() <= oos_end_date)
            ]

            # Get symbols
            train_symbols = sorted(train_data.index.get_level_values("symbol").unique().tolist())
            oos_symbols = sorted(oos_data.index.get_level_values("symbol").unique().tolist())

            # Filter to common symbols
            common_symbols = list(set(train_symbols) & set(oos_symbols))
            if len(common_symbols) >= self.min_symbols_per_period:
                train_data = train_data[
                    train_data.index.get_level_values("symbol").isin(common_symbols)
                ]
                oos_data = oos_data[oos_data.index.get_level_values("symbol").isin(common_symbols)]

                # Check minimum observation requirements
                if (
                    len(train_data) >= self.min_observations_per_period
                    and len(oos_data) >= self.min_observations_per_period
                ):
                    period = WFOPeriod(
                        period_id=period_id,
                        train_start=train_start_date,
                        train_end=train_end_date,
                        validation_start=val_start_date,
                        validation_end=val_end_date,
                        oos_start=oos_start_date,
                        oos_end=oos_end_date,
                        train_symbols=common_symbols,
                        oos_symbols=common_symbols,
                        train_size=len(train_data),
                        oos_size=len(oos_data),
                    )

                    periods.append(period)
                    period_id += 1

            # Move to next period
            if self.window_type == "rolling":
                # Rolling window: shift start date
                step_target_date = train_start_date + step_length
                next_start_idx = self._find_date_index(dates, step_target_date, current_start_idx)
            else:
                # Expanding window: move OOS start
                step_target_date = oos_start_date + step_length
                next_start_idx = self._find_date_index(dates, step_target_date, current_start_idx)

            if next_start_idx is None:
                break

            current_start_idx = max(next_start_idx, current_start_idx + 1)

        return periods

    def _find_date_index(
        self, dates: list[pd.Timestamp], target_date: pd.Timestamp, start_idx: int
    ) -> int | None:
        """Find the index of the closest date to target."""
        for i in range(start_idx, len(dates)):
            if dates[i] >= target_date:
                return i
        return None

    def run_walk_forward(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        model_config: dict[str, Any],
        cv_config: dict[str, Any],
    ) -> WFOAggregatedResults:
        """Run complete walk-forward evaluation.

        Args:
            features: Feature DataFrame with multi-index (symbol, ts)
            labels: Label Series with multi-index (symbol, ts)
            model_config: Model configuration
            cv_config: Cross-validation configuration

        Returns:
            Complete WFO results
        """
        start_time = datetime.now()

        # Prepare combined data
        combined_data = features.copy()
        combined_data["target"] = labels

        # Create WFO periods
        periods = self.create_wfo_periods(combined_data)

        if not periods:
            raise ValueError("No valid WFO periods could be created")

        print(f"Created {len(periods)} WFO periods")

        # Run each period
        period_results = []
        for _i, period in enumerate(periods):
            print(f"\nRunning WFO period {period.period_id}/{len(periods)}")
            print(f"Training: {period.train_start.date()} to {period.train_end.date()}")
            print(f"OOS: {period.oos_start.date()} to {period.oos_end.date()}")

            period_result = self._run_wfo_period(period, combined_data, model_config, cv_config)
            period_results.append(period_result)

            print(f"Period {period.period_id} completed")
            print(f"Training time: {period_result.training_time_seconds:.1f}s")
            print(f"OOS F1: {period_result.oos_metrics.get('f1_macro', 0):.3f}")

        # Aggregate results
        overall_metrics = self._calculate_overall_metrics(period_results)
        temporal_stability = self._analyze_temporal_stability(period_results)
        regime_analysis = self._analyze_regime_performance(period_results)
        model_evolution = self._analyze_model_evolution(period_results)
        kpi_summary = self._calculate_kpi_summary(period_results)

        total_time = (datetime.now() - start_time).total_seconds()

        # Create reproducibility info
        reproducibility_info = {
            "features_hash": self._compute_data_hash(features),
            "labels_hash": self._compute_data_hash(labels),
            "config_hash": self._compute_config_hash(model_config, cv_config),
            "total_periods": len(periods),
            "successful_periods": len(period_results),
        }

        result = WFOAggregatedResults(
            wfo_config=self.config,
            periods=periods,
            period_results=period_results,
            overall_metrics=overall_metrics,
            temporal_stability=temporal_stability,
            regime_analysis=regime_analysis,
            model_evolution=model_evolution,
            kpi_summary=kpi_summary,
            total_time_seconds=total_time,
            reproducibility_info=reproducibility_info,
        )

        # Save results
        self._save_wfo_results(result)

        print(f"\nWalk-forward evaluation completed in {total_time:.1f}s")
        print(
            f"Average OOS F1: {overall_metrics.get('f1_macro_mean', 0):.3f} ± {overall_metrics.get('f1_macro_std', 0):.3f}"
        )

        return result

    def _run_wfo_period(
        self,
        period: WFOPeriod,
        combined_data: pd.DataFrame,
        model_config: dict[str, Any],
        cv_config: dict[str, Any],
    ) -> WFOPeriodResults:
        """Run a single WFO period."""
        period_start_time = datetime.now()

        # Extract training data
        train_mask = (
            (combined_data.index.get_level_values("ts").normalize() >= period.train_start)
            & (combined_data.index.get_level_values("ts").normalize() <= period.train_end)
            & (combined_data.index.get_level_values("symbol").isin(period.train_symbols))
        )
        train_data = combined_data[train_mask]

        # Extract OOS data
        oos_mask = (
            (combined_data.index.get_level_values("ts").normalize() >= period.oos_start)
            & (combined_data.index.get_level_values("ts").normalize() <= period.oos_end)
            & (combined_data.index.get_level_values("symbol").isin(period.oos_symbols))
        )
        oos_data = combined_data[oos_mask]

        # Split features and labels
        train_features = train_data.drop(columns=["target"])
        train_labels = train_data["target"]
        oos_features = oos_data.drop(columns=["target"])
        oos_labels = oos_data["target"]

        # Cross-validation on training data
        cv_results = run_cross_validation(train_features, train_labels, model_config, cv_config)

        # Train final model on full training data
        trainer = LightGBMTrainer(model_config)
        training_result = trainer.train_model(
            train_features,
            train_labels,
            cv_results.reproducibility_info["features_hash"],
            cv_results.reproducibility_info["targets_hash"],
        )

        # Save model
        model_name = f"wfo_period_{period.period_id}"
        model_save_info = self.model_io.save_model(training_result, model_name, config=model_config)

        # Generate OOS predictions
        inference_start = datetime.now()
        oos_predictions = self._generate_predictions(training_result.calibrated_model, oos_features)
        inference_time = (datetime.now() - inference_start).total_seconds()

        # Calculate OOS metrics
        oos_metrics = self._calculate_oos_metrics(oos_predictions, oos_labels)

        training_time = (datetime.now() - period_start_time).total_seconds()

        return WFOPeriodResults(
            period=period,
            training_result=training_result,
            cv_results=cv_results if hasattr(cv_results, "__dict__") else cv_results,
            oos_predictions=oos_predictions,
            oos_metrics=oos_metrics,
            model_path=model_save_info["model_path"],
            model_card_path=model_save_info["model_card_path"],
            training_time_seconds=training_time,
            inference_time_seconds=inference_time,
        )

    def _generate_predictions(self, model, features: pd.DataFrame) -> pd.DataFrame:
        """Generate predictions with probabilities."""
        predictions = model.predict_proba(features)
        predicted_classes = model.predict(features)

        # Create prediction DataFrame
        pred_df = pd.DataFrame(
            predictions,
            index=features.index,
            columns=[f"prob_class_{i}" for i in range(predictions.shape[1])],
        )
        pred_df["predicted_class"] = predicted_classes

        return pred_df

    def _calculate_oos_metrics(
        self, predictions: pd.DataFrame, true_labels: pd.Series
    ) -> dict[str, Any]:
        """Calculate out-of-sample metrics."""
        from sklearn.metrics import (
            accuracy_score,
            brier_score_loss,
            log_loss,
            precision_recall_fscore_support,
        )

        pred_classes = predictions["predicted_class"]
        prob_cols = [c for c in predictions.columns if c.startswith("prob_class_")]
        probas = predictions[prob_cols].values

        # Basic metrics
        accuracy = accuracy_score(true_labels, pred_classes)
        precision, recall, f1, _ = precision_recall_fscore_support(
            true_labels, pred_classes, average="macro"
        )

        # Probability metrics
        brier_score = brier_score_loss(true_labels, probas, labels=np.unique(true_labels))
        logloss = log_loss(true_labels, probas)

        # Economic metrics (simplified)
        win_rate = accuracy  # Simplified

        return {
            "accuracy": accuracy,
            "precision_macro": precision,
            "recall_macro": recall,
            "f1_macro": f1,
            "brier_score": brier_score,
            "log_loss": logloss,
            "win_rate": win_rate,
            "total_predictions": len(predictions),
            "prediction_distribution": pred_classes.value_counts().to_dict(),
        }

    def _calculate_overall_metrics(self, period_results: list[WFOPeriodResults]) -> dict[str, Any]:
        """Calculate overall metrics across all periods."""
        metric_names = [
            "accuracy",
            "precision_macro",
            "recall_macro",
            "f1_macro",
            "brier_score",
            "log_loss",
            "win_rate",
        ]

        overall = {}
        for metric in metric_names:
            values = [r.oos_metrics.get(metric, 0) for r in period_results]
            overall[f"{metric}_mean"] = np.mean(values)
            overall[f"{metric}_std"] = np.std(values)
            overall[f"{metric}_min"] = np.min(values)
            overall[f"{metric}_max"] = np.max(values)

        # Timing metrics
        training_times = [r.training_time_seconds for r in period_results]
        inference_times = [r.inference_time_seconds for r in period_results]

        overall["training_time_mean"] = np.mean(training_times)
        overall["training_time_total"] = np.sum(training_times)
        overall["inference_time_mean"] = np.mean(inference_times)

        return overall

    def _analyze_temporal_stability(self, period_results: list[WFOPeriodResults]) -> dict[str, Any]:
        """Analyze temporal stability of performance."""
        # Extract metrics over time
        periods = [r.period.period_id for r in period_results]
        f1_scores = [r.oos_metrics.get("f1_macro", 0) for r in period_results]
        accuracies = [r.oos_metrics.get("accuracy", 0) for r in period_results]

        # Calculate trends
        if len(f1_scores) > 1:
            f1_trend = np.polyfit(periods, f1_scores, 1)[0]
            acc_trend = np.polyfit(periods, accuracies, 1)[0]
        else:
            f1_trend = 0.0
            acc_trend = 0.0

        # Calculate volatility
        f1_volatility = np.std(f1_scores) if len(f1_scores) > 1 else 0.0
        acc_volatility = np.std(accuracies) if len(accuracies) > 1 else 0.0

        return {
            "f1_trend": f1_trend,
            "accuracy_trend": acc_trend,
            "f1_volatility": f1_volatility,
            "accuracy_volatility": acc_volatility,
            "stability_score": 1 / (1 + f1_volatility),  # Higher = more stable
            "performance_drift": f1_trend,
        }

    def _analyze_regime_performance(self, period_results: list[WFOPeriodResults]) -> dict[str, Any]:
        """Analyze performance across different market regimes."""
        # Simplified regime analysis - in practice would use market regime indicators
        performance_by_quarter = {}
        for result in period_results:
            period = result.period
            quarter = f"{period.oos_start.year}-Q{(period.oos_start.month - 1) // 3 + 1}"

            if quarter not in performance_by_quarter:
                performance_by_quarter[quarter] = []

            performance_by_quarter[quarter].append(
                {
                    "f1_macro": result.oos_metrics.get("f1_macro", 0),
                    "accuracy": result.oos_metrics.get("accuracy", 0),
                    "period_id": period.period_id,
                }
            )

        # Calculate quarterly statistics
        quarterly_stats = {}
        for quarter, perfs in performance_by_quarter.items():
            f1_scores = [p["f1_macro"] for p in perfs]
            quarterly_stats[quarter] = {
                "mean_f1": np.mean(f1_scores),
                "std_f1": np.std(f1_scores),
                "period_count": len(perfs),
            }

        return {
            "quarterly_performance": quarterly_stats,
            "regime_consistency": 1.0,  # Placeholder - would calculate actual regime consistency
        }

    def _analyze_model_evolution(self, period_results: list[WFOPeriodResults]) -> dict[str, Any]:
        """Analyze evolution of model parameters over time."""
        # Extract feature importance trends
        all_features = set()
        for result in period_results:
            all_features.update(result.training_result.metrics.get("feature_importance", {}).keys())

        feature_trends = {}
        for feature in list(all_features)[:10]:  # Top 10 features
            importance_values = []
            for result in period_results:
                importance = result.training_result.metrics.get("feature_importance", {}).get(
                    feature, 0
                )
                importance_values.append(importance)

            if len(importance_values) > 1:
                trend = np.polyfit(range(len(importance_values)), importance_values, 1)[0]
                feature_trends[feature] = trend

        return {
            "feature_importance_trends": feature_trends,
            "model_complexity_evolution": [],  # Placeholder
            "hyperparameter_stability": {},  # Placeholder
        }

    def _calculate_kpi_summary(self, period_results: list[WFOPeriodResults]) -> dict[str, Any]:
        """Calculate comprehensive KPI summary."""
        # Performance KPIs
        avg_f1 = np.mean([r.oos_metrics.get("f1_macro", 0) for r in period_results])
        f1_std = np.std([r.oos_metrics.get("f1_macro", 0) for r in period_results])
        min_f1 = np.min([r.oos_metrics.get("f1_macro", 0) for r in period_results])

        # Stability KPIs
        stability_score = 1 / (1 + f1_std) if f1_std > 0 else 1.0

        # Efficiency KPIs
        total_training_time = np.sum([r.training_time_seconds for r in period_results])
        avg_inference_time = np.mean([r.inference_time_seconds for r in period_results])

        # Business KPIs
        successful_periods = len(
            [r for r in period_results if r.oos_metrics.get("f1_macro", 0) > 0.5]
        )
        success_rate = successful_periods / len(period_results)

        return {
            "performance": {
                "mean_f1_score": avg_f1,
                "f1_consistency": stability_score,
                "worst_period_f1": min_f1,
                "performance_above_threshold": success_rate,
            },
            "efficiency": {
                "total_training_hours": total_training_time / 3600,
                "average_inference_time_ms": avg_inference_time * 1000,
                "periods_per_day": len(period_results) / (total_training_time / 86400),
            },
            "reliability": {
                "successful_periods": successful_periods,
                "total_periods": len(period_results),
                "success_rate": success_rate,
                "model_degradation": 0.0,  # Placeholder - would calculate degradation
            },
            "production_readiness": {
                "ready_for_production": success_rate > 0.7 and avg_f1 > 0.6,
                "recommended_monitoring": [
                    "f1_score_drift",
                    "prediction_distribution",
                    "inference_latency",
                ],
                "risk_level": (
                    "low" if success_rate > 0.8 else "medium" if success_rate > 0.6 else "high"
                ),
            },
        }

    def _compute_data_hash(self, data: pd.DataFrame) -> str:
        """Compute hash of data for reproducibility."""
        return str(hash(pd.util.hash_pandas_object(data.head(1000)).sum()))

    def _compute_config_hash(self, model_config: dict, cv_config: dict) -> str:
        """Compute hash of configurations."""
        config_str = json.dumps({**model_config, **cv_config}, sort_keys=True)
        return str(hash(config_str))

    def _save_wfo_results(self, result: WFOAggregatedResults):
        """Save WFO results to files."""
        # Save complete results
        results_path = self.model_dir / "wfo_results.json"
        with open(results_path, "w") as f:
            json.dump(asdict(result), f, indent=2, default=str)

        # Save KPI summary
        kpi_path = self.model_dir / "wfo_kpi_summary.json"
        with open(kpi_path, "w") as f:
            json.dump(result.kpi_summary, f, indent=2, default=str)

        # Save period-by-period results
        periods_data = []
        for period_result in result.period_results:
            period_data = {
                "period_id": period_result.period.period_id,
                "train_start": period_result.period.train_start.isoformat(),
                "train_end": period_result.period.train_end.isoformat(),
                "oos_start": period_result.period.oos_start.isoformat(),
                "oos_end": period_result.period.oos_end.isoformat(),
                "f1_macro": period_result.oos_metrics.get("f1_macro", 0),
                "accuracy": period_result.oos_metrics.get("accuracy", 0),
                "training_time": period_result.training_time_seconds,
            }
            periods_data.append(period_data)

        periods_df = pd.DataFrame(periods_data)
        periods_path = self.model_dir / "wfo_period_results.csv"
        periods_df.to_csv(periods_path, index=False)

        print(f"WFO results saved to {self.model_dir}")


def run_walk_forward_optimization(
    features: pd.DataFrame,
    labels: pd.Series,
    model_config: dict[str, Any],
    cv_config: dict[str, Any],
    wfo_config: dict[str, Any],
    model_dir: Path,
) -> WFOAggregatedResults:
    """Convenience function for walk-forward optimization.

    Args:
        features: Feature DataFrame with multi-index (symbol, ts)
        labels: Label Series with multi-index (symbol, ts)
        model_config: Model configuration
        cv_config: Cross-validation configuration
        wfo_config: WFO configuration
        model_dir: Directory to save models

    Returns:
        Complete WFO results
    """
    evaluator = WalkForwardEvaluator(wfo_config, model_dir)
    return evaluator.run_walk_forward(features, labels, model_config, cv_config)
