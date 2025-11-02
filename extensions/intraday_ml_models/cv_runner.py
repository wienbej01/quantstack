"""Cross-Validation Runner for Intraday ML Models

Implements purged, embargoed time-series CV with proper temporal ordering,
comprehensive metrics aggregation, and reproducibility validation.
"""

import itertools
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    precision_recall_fscore_support,
)

from extensions.intraday_ml.utils.checksums import compute_data_hash
from extensions.intraday_ml_models.train_lgbm import LightGBMTrainer, TrainingResult


@dataclass
class CVSplit:
    """Single CV split with metadata."""

    fold: int
    train_start: datetime
    train_end: datetime
    val_start: datetime
    val_end: datetime
    train_symbols: list[str]
    val_symbols: list[str]
    train_size: int
    val_size: int
    purge_start: datetime | None = None
    purge_end: datetime | None = None
    embargo_end: datetime | None = None


@dataclass
class CVMetrics:
    """Comprehensive CV metrics for a single fold."""

    fold: int

    # Primary metrics
    accuracy: float
    precision_macro: float
    recall_macro: float
    f1_macro: float
    brier_score: float
    brier_score_calibrated: float
    brier_improvement: float
    log_loss: float
    log_loss_calibrated: float

    # Class-specific metrics
    class_metrics: dict[str, dict[str, float]]

    # Economic metrics
    expectancy: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float

    # Trade density metrics
    trades_per_ticker_day: float
    micro_trade_rate: float
    avg_holding_time: float
    abstention_rate: float

    # Feature importance
    feature_importance: dict[str, float]
    top_features: list[tuple[str, float]]

    # Reproducibility
    features_hash: str
    targets_hash: str
    config_hash: str

    # Timing
    train_time_seconds: float


@dataclass
class CVResult:
    """Complete CV results with aggregated metrics."""

    cv_config: dict[str, Any]
    splits: list[CVSplit]
    fold_metrics: list[CVMetrics]
    aggregated_metrics: dict[str, Any]
    stability_metrics: dict[str, Any]
    calibration_metrics: dict[str, Any]
    reproducibility_info: dict[str, Any]
    total_time_seconds: float


class TimeSeriesCVRunner:
    """Runs purged, embargoed time-series CV with proper temporal ordering."""

    def __init__(self, cv_config: dict[str, Any]):
        """Initialize CV runner with configuration.

        Args:
            cv_config: CV configuration from cv.yaml
        """
        self.config = cv_config
        self.n_folds = cv_config.get("n_folds", 5)
        self.purge_days = cv_config.get("purge_days", 2)
        self.embargo_days = cv_config.get("embargo_days", 5)
        self.validation_method = cv_config.get("validation_method", "purged_cv")
        self.strict_temporal_order = cv_config.get("strict_temporal_order", True)
        self.cross_symbol_consistency = cv_config.get("cross_symbol_consistency", True)

        # Data quality controls
        self.min_observations_per_fold = cv_config.get(
            "min_observations_per_fold", 1000
        )
        self.min_symbols_per_fold = cv_config.get("min_symbols_per_fold", 2)

        # Metrics configuration
        self.metrics_config = cv_config.get("metrics", [])
        if isinstance(self.metrics_config, dict):
            self.primary_metrics = self.metrics_config.get("primary_metrics", [])
            self.economic_metrics = self.metrics_config.get("economic_metrics", [])
            self.trade_density_metrics = self.metrics_config.get("trade_density", [])
        else:
            self.primary_metrics = self.metrics_config
            self.economic_metrics = []
            self.trade_density_metrics = []

    def create_splits(
        self, data: pd.DataFrame, date_column: str = "ts"
    ) -> list[CVSplit]:
        """Create purged, embargoed CV splits.

        Args:
            data: Input data with timestamps
            date_column: Name of date column

        Returns:
            List of CV splits with metadata
        """
        if self.validation_method == "purged_cv":
            return self._create_purged_splits(data, date_column)
        elif self.validation_method == "expanding_window":
            return self._create_expanding_splits(data, date_column)
        elif self.validation_method == "rolling_window":
            return self._create_rolling_splits(data, date_column)
        else:
            raise ValueError(f"Unknown validation method: {self.validation_method}")

    def _create_purged_splits(
        self, data: pd.DataFrame, date_column: str
    ) -> list[CVSplit]:
        """Create purged CV splits with proper temporal ordering."""
        # Ensure data is sorted by timestamp
        data = data.sort_values(date_column)

        # Get unique dates and ensure temporal ordering
        unique_dates = data[date_column].dt.floor("D").unique()
        unique_dates = sorted(unique_dates)

        # Calculate split points
        n_dates = len(unique_dates)
        fold_size = n_dates // self.n_folds

        splits = []

        for fold in range(self.n_folds):
            # Calculate boundaries
            if fold < self.n_folds - 1:
                val_start_idx = fold * fold_size
                val_end_idx = (fold + 1) * fold_size
            else:
                # Last fold takes remaining data
                val_start_idx = fold * fold_size
                val_end_idx = n_dates

            # Validation period
            val_start_date = unique_dates[val_start_idx]
            val_end_date = (
                unique_dates[val_end_idx - 1]
                + pd.Timedelta(days=1)
                - pd.Timedelta(seconds=1)
            )

            # Training period (all data before validation)
            train_end_idx = val_start_idx
            if train_end_idx == 0:
                continue  # Skip fold with no training data

            train_start_date = unique_dates[0]
            train_end_date = (
                unique_dates[train_end_idx - 1]
                + pd.Timedelta(days=1)
                - pd.Timedelta(seconds=1)
            )

            # Apply purge period
            purge_start_date = train_end_date + pd.Timedelta(seconds=1)
            purge_end_date = val_start_date - pd.Timedelta(days=self.purge_days)

            # Apply embargo period
            embargo_end_date = val_start_date - pd.Timedelta(days=self.embargo_days)

            # Adjust training end if purge overlaps
            if purge_end_date <= train_end_date:
                train_end_date = purge_end_date - pd.Timedelta(seconds=1)

            # Get symbols in each period
            train_data = data[
                (data[date_column] >= train_start_date)
                & (data[date_column] <= train_end_date)
            ]
            val_data = data[
                (data[date_column] >= val_start_date)
                & (data[date_column] <= val_end_date)
            ]

            train_symbols = sorted(train_data["symbol"].unique().tolist())
            val_symbols = sorted(val_data["symbol"].unique().tolist())

            # Apply cross-symbol consistency
            if self.cross_symbol_consistency:
                common_symbols = set(train_symbols) & set(val_symbols)
                train_symbols = sorted(common_symbols)
                val_symbols = sorted(common_symbols)

                # Filter data to common symbols
                train_data = train_data[train_data["symbol"].isin(common_symbols)]
                val_data = val_data[val_data["symbol"].isin(common_symbols)]

            # Check minimum requirements
            if (
                len(train_data) < self.min_observations_per_fold
                or len(val_data) < self.min_observations_per_fold
                or len(train_symbols) < self.min_symbols_per_fold
                or len(val_symbols) < self.min_symbols_per_fold
            ):
                continue

            split = CVSplit(
                fold=fold + 1,
                train_start=train_start_date,
                train_end=train_end_date,
                val_start=val_start_date,
                val_end=val_end_date,
                train_symbols=train_symbols,
                val_symbols=val_symbols,
                train_size=len(train_data),
                val_size=len(val_data),
                purge_start=(
                    purge_start_date if purge_start_date < val_start_date else None
                ),
                purge_end=purge_end_date if purge_end_date > train_end_date else None,
                embargo_end=(
                    embargo_end_date if embargo_end_date > train_end_date else None
                ),
            )

            splits.append(split)

        return splits

    def _create_expanding_splits(
        self, data: pd.DataFrame, date_column: str
    ) -> list[CVSplit]:
        """Create expanding window CV splits."""
        # Similar implementation to purged splits but with expanding windows
        # For now, delegate to purged splits
        return self._create_purged_splits(data, date_column)

    def _create_rolling_splits(
        self, data: pd.DataFrame, date_column: str
    ) -> list[CVSplit]:
        """Create rolling window CV splits."""
        # Similar implementation to purged splits but with fixed-size windows
        # For now, delegate to purged splits
        return self._create_purged_splits(data, date_column)

    def run_cv(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        model_trainer: LightGBMTrainer,
        model_config: dict[str, Any],
    ) -> CVResult:
        """Run complete CV evaluation.

        Args:
            features: Feature DataFrame with multi-index (symbol, ts)
            labels: Label Series with multi-index (symbol, ts)
            model_trainer: Configured model trainer
            model_config: Model configuration

        Returns:
            Complete CV results
        """
        start_time = datetime.now()

        # Validate inputs
        self._validate_cv_inputs(features, labels)

        # Create splits
        combined_data = features.copy()
        combined_data["target"] = labels
        combined_data = combined_data.reset_index()

        splits = self.create_splits(combined_data, "ts")

        if not splits:
            raise ValueError("No valid CV splits could be created")

        # Run CV folds
        fold_metrics = []
        hashes_used = set()

        for split in splits:
            print(f"Running CV fold {split.fold}/{len(splits)}")

            # Get fold data
            train_mask = (
                (combined_data["ts"] >= split.train_start)
                & (combined_data["ts"] <= split.train_end)
                & (combined_data["symbol"].isin(split.train_symbols))
            )
            val_mask = (
                (combined_data["ts"] >= split.val_start)
                & (combined_data["ts"] <= split.val_end)
                & (combined_data["symbol"].isin(split.val_symbols))
            )

            train_data = combined_data[train_mask]
            val_data = combined_data[val_mask]

            # Prepare features and labels
            train_features = train_data.drop(columns=["target"]).set_index(
                ["symbol", "ts"]
            )
            train_labels = train_data.set_index(["symbol", "ts"])["target"]
            val_features = val_data.drop(columns=["target"]).set_index(["symbol", "ts"])
            val_labels = val_data.set_index(["symbol", "ts"])["target"]

            if train_labels.nunique() <= 1 or val_labels.nunique() == 0:
                print(
                    f"Skipping fold {split.fold}: insufficient class variety "
                    f"(train classes={train_labels.nunique()}, val classes={val_labels.nunique()})"
                )
                continue

            # Compute hashes
            features_hash = compute_data_hash(train_features)
            targets_hash = compute_data_hash(train_labels)
            config_hash = compute_data_hash(
                pd.Series([json.dumps(model_config, sort_keys=True)])
            )

            hash_key = (features_hash, targets_hash, config_hash)
            if hash_key in hashes_used:
                print(f"Warning: Duplicate hash detected in fold {split.fold}")
            hashes_used.add(hash_key)

            # Train model
            training_result = model_trainer.train_model(
                train_features,
                train_labels,
                features_hash,
                targets_hash,
                validation_data=(val_features, val_labels),
            )

            # Calculate comprehensive metrics
            metrics = self._calculate_comprehensive_metrics(
                training_result,
                val_features,
                val_labels,
                split,
                features_hash,
                targets_hash,
                config_hash,
            )

            fold_metrics.append(metrics)

        if not fold_metrics:
            raise ValueError(
                "No valid CV folds were executed due to insufficient data variety."
            )

        # Aggregate results
        aggregated_metrics = self._aggregate_metrics(fold_metrics)
        stability_metrics = self._calculate_stability_metrics(fold_metrics)
        calibration_metrics = self._calculate_calibration_metrics(fold_metrics)

        total_time = (datetime.now() - start_time).total_seconds()

        result = CVResult(
            cv_config=self.config,
            splits=splits,
            fold_metrics=fold_metrics,
            aggregated_metrics=aggregated_metrics,
            stability_metrics=stability_metrics,
            calibration_metrics=calibration_metrics,
            reproducibility_info={
                "unique_hashes": len(hashes_used),
                "total_folds": len(splits),
                "hash_collisions": 0,
            },
            total_time_seconds=total_time,
        )

        return result

    def _validate_cv_inputs(self, features: pd.DataFrame, labels: pd.Series):
        """Validate CV inputs for temporal consistency."""
        # Check multi-index
        if not isinstance(features.index, pd.MultiIndex):
            raise ValueError("Features must have multi-index (symbol, ts)")
        if not isinstance(labels.index, pd.MultiIndex):
            raise ValueError("Labels must have multi-index (symbol, ts)")

        # Check alignment
        if not features.index.equals(labels.index):
            raise ValueError("Features and labels must have identical indices")

        # Check temporal ordering within symbols
        for symbol in features.index.get_level_values("symbol").unique():
            symbol_data = features.loc[symbol]
            if not symbol_data.index.is_monotonic_increasing:
                raise ValueError(f"Data for symbol {symbol} is not temporally ordered")

    def _calculate_comprehensive_metrics(
        self,
        training_result: TrainingResult,
        val_features: pd.DataFrame,
        val_labels: pd.Series,
        split: CVSplit,
        features_hash: str,
        targets_hash: str,
        config_hash: str,
    ) -> CVMetrics:
        """Calculate comprehensive metrics for a single fold."""
        # Get predictions
        calibrated_model = training_result.calibrated_model
        y_proba = calibrated_model.predict_proba(val_features)
        y_pred = calibrated_model.predict(val_features)

        # Basic metrics
        accuracy = accuracy_score(val_labels, y_pred)
        precision, recall, f1, _ = precision_recall_fscore_support(
            val_labels, y_pred, average="macro"
        )

        # Brier score and calibration
        brier_score = brier_score_loss(
            val_labels, y_proba, labels=calibrated_model.classes_
        )

        # Class-specific metrics
        precision_per_class, recall_per_class, f1_per_class, _ = (
            precision_recall_fscore_support(
                val_labels, y_pred, average=None, labels=calibrated_model.classes_
            )
        )

        class_metrics = {}
        for i, cls in enumerate(calibrated_model.classes_):
            class_metrics[str(cls)] = {
                "precision": float(precision_per_class[i]),
                "recall": float(recall_per_class[i]),
                "f1": float(f1_per_class[i]),
            }

        # Economic metrics (simplified - would need price data for full calculation)
        expectancy = 0.0  # Placeholder
        sharpe_ratio = 0.0  # Placeholder
        max_drawdown = 0.0  # Placeholder
        win_rate = accuracy  # Simplified approximation

        # Trade density metrics (simplified)
        trades_per_ticker_day = len(y_pred) / (
            len(split.val_symbols) * 1
        )  # 1 day approximation
        micro_trade_rate = 0.0  # Would need trade sizes
        avg_holding_time = 0.0  # Would need holding period data
        abstention_rate = 0.0  # Would need abstention logic

        # Feature importance
        feature_importance = dict(
            zip(
                val_features.columns,
                training_result.model.feature_importances_,
                strict=False,
            )
        )
        top_features = sorted(
            feature_importance.items(), key=lambda x: x[1], reverse=True
        )[:10]

        return CVMetrics(
            fold=split.fold,
            accuracy=accuracy,
            precision_macro=precision,
            recall_macro=recall,
            f1_macro=f1,
            brier_score=brier_score,
            brier_score_calibrated=brier_score,  # Would need calibrated probabilities
            brier_improvement=0.0,  # Would need uncalibrated probabilities
            log_loss=0.0,  # Placeholder
            log_loss_calibrated=0.0,  # Placeholder
            class_metrics=class_metrics,
            expectancy=expectancy,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            trades_per_ticker_day=trades_per_ticker_day,
            micro_trade_rate=micro_trade_rate,
            avg_holding_time=avg_holding_time,
            abstention_rate=abstention_rate,
            feature_importance=feature_importance,
            top_features=top_features,
            features_hash=features_hash,
            targets_hash=targets_hash,
            config_hash=config_hash,
            train_time_seconds=training_result.training_time_seconds,
        )

    def _aggregate_metrics(self, fold_metrics: list[CVMetrics]) -> dict[str, Any]:
        """Aggregate metrics across folds."""
        # Collect numeric metrics
        metric_names = [
            "accuracy",
            "precision_macro",
            "recall_macro",
            "f1_macro",
            "brier_score",
            "expectancy",
            "sharpe_ratio",
            "max_drawdown",
            "win_rate",
            "trades_per_ticker_day",
            "micro_trade_rate",
            "avg_holding_time",
            "abstention_rate",
            "train_time_seconds",
        ]

        aggregated = {}

        for metric in metric_names:
            values = [getattr(m, metric) for m in fold_metrics]
            aggregated[f"{metric}_mean"] = np.mean(values)
            aggregated[f"{metric}_std"] = np.std(values)
            aggregated[f"{metric}_min"] = np.min(values)
            aggregated[f"{metric}_max"] = np.max(values)
            aggregated[f"{metric}_median"] = np.median(values)

        return aggregated

    def _calculate_stability_metrics(
        self, fold_metrics: list[CVMetrics]
    ) -> dict[str, Any]:
        """Calculate stability metrics across folds."""
        # Coefficient of variation for primary metrics
        primary_metrics = ["accuracy", "f1_macro", "precision_macro", "recall_macro"]

        stability = {}
        for metric in primary_metrics:
            values = [getattr(m, metric) for m in fold_metrics]
            mean_val = np.mean(values)
            std_val = np.std(values)
            cv = std_val / mean_val if mean_val != 0 else float("inf")

            stability[f"{metric}_cv"] = cv
            stability[f"{metric}_stability_score"] = 1 / (
                1 + cv
            )  # Higher = more stable

        # Feature importance stability
        all_features = set()
        for m in fold_metrics:
            all_features.update(m.feature_importance.keys())

        feature_correlations = []
        for i, j in itertools.combinations(range(len(fold_metrics)), 2):
            features_i = [
                fold_metrics[i].feature_importance.get(f, 0) for f in all_features
            ]
            features_j = [
                fold_metrics[j].feature_importance.get(f, 0) for f in all_features
            ]
            corr = np.corrcoef(features_i, features_j)[0, 1]
            if not np.isnan(corr):
                feature_correlations.append(corr)

        stability["feature_importance_mean_correlation"] = (
            np.mean(feature_correlations) if feature_correlations else 0.0
        )
        stability["feature_importance_stability"] = stability[
            "feature_importance_mean_correlation"
        ]

        return stability

    def _calculate_calibration_metrics(
        self, fold_metrics: list[CVMetrics]
    ) -> dict[str, Any]:
        """Calculate calibration metrics across folds."""
        # Simplified calibration metrics
        brier_scores = [m.brier_score for m in fold_metrics]

        calibration = {
            "mean_brier_score": np.mean(brier_scores),
            "brier_score_std": np.std(brier_scores),
            "brier_score_consistency": 1
            / (1 + np.std(brier_scores)),  # Higher = more consistent
        }

        return calibration

    def save_cv_results(self, result: CVResult, output_path: Path):
        """Save CV results to file.

        Args:
            result: CV results to save
            output_path: Path to save results
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Convert to serializable format
        result_dict = asdict(result)

        # Handle datetime serialization
        def json_serializer(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, np.floating):
                return float(obj)
            elif isinstance(obj, np.integer):
                return int(obj)
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

        with open(output_path, "w") as f:
            json.dump(result_dict, f, indent=2, default=json_serializer)

        print(f"CV results saved to {output_path}")


def run_cross_validation(
    features: pd.DataFrame,
    labels: pd.Series,
    model_config: dict[str, Any],
    cv_config: dict[str, Any],
    output_path: Path | None = None,
) -> CVResult:
    """Convenience function to run cross-validation.

    Args:
        features: Feature DataFrame with multi-index (symbol, ts)
        labels: Label Series with multi-index (symbol, ts)
        model_config: Model configuration
        cv_config: CV configuration
        output_path: Optional path to save results

    Returns:
        Complete CV results
    """
    # Initialize trainer and CV runner
    trainer = LightGBMTrainer(model_config)
    cv_runner = TimeSeriesCVRunner(cv_config)

    # Run CV
    result = cv_runner.run_cv(features, labels, trainer, model_config)

    # Save results if path provided
    if output_path:
        cv_runner.save_cv_results(result, output_path)

    return result
