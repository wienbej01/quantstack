"""LightGBM Training Module for Intraday ML

Tri-class classifier training with probability calibration and comprehensive
evaluation metrics for prominent moves prediction.
"""

import time
from dataclasses import dataclass
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    log_loss,
    precision_recall_fscore_support,
)
from sklearn.model_selection import StratifiedKFold, train_test_split


@dataclass
class TrainingResult:
    """Result of model training with comprehensive metrics."""

    model: lgb.LGBMClassifier
    calibrated_model: CalibratedClassifierCV
    metrics: dict[str, Any]
    training_metadata: dict[str, Any]
    training_time_seconds: float


class LightGBMTrainer:
    """Trains LightGBM tri-class classifier for intraday ML."""

    def __init__(self, model_config: dict[str, Any]):
        """Initialize trainer with model configuration.

        Args:
            model_config: Configuration dictionary from model_lgbm.yaml
        """
        self.config = model_config
        self.lgbm_params = model_config.get("lgbm_params", {})
        self.training_params = model_config.get("training", {})
        self.calibration_config = model_config.get("calibration", {})
        class_weights_cfg = model_config.get("class_weights", {})
        if isinstance(class_weights_cfg, dict) and "base" in class_weights_cfg:
            self.class_weight_base = class_weights_cfg.get("base", {})
            self.class_weight_strategy = class_weights_cfg.get("auto_balance", {})
        else:
            self.class_weight_base = class_weights_cfg or {}
            self.class_weight_strategy = {}
        self._last_weight_summary: dict[str, Any] | None = None

    def train_model(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        features_hash: str,
        targets_hash: str,
        validation_data: tuple[pd.DataFrame, pd.Series] | None = None,
    ) -> TrainingResult:
        """Train LightGBM model with calibration.

        Args:
            features: Feature DataFrame
            labels: Label Series
            features_hash: Hash of feature data
            targets_hash: Hash of target data
            validation_data: Optional validation tuple (X_val, y_val)

        Returns:
            TrainingResult with trained model and metrics
        """
        start_time = time.time()
        self._last_weight_summary = None

        # Prepare data
        X, y = self._prepare_data(features, labels)

        # Validate label diversity - critical for multiclass training
        unique_labels = y.unique()
        if len(unique_labels) <= 1:
            raise ValueError(
                f"Cannot train multiclass model with only {len(unique_labels)} unique class: {unique_labels.tolist()}. "
                f"This typically means the ATR threshold is too high (all moves are 'neutral'). "
                f"Consider reducing 'atr_multiplier' in targets configuration (current: {getattr(self, 'atr_multiplier', 'unknown')})."
            )

        # Split data if no validation provided
        if validation_data is None:
            X_train, X_val, y_train, y_val = self._split_data(X, y)
        else:
            X_train, y_train = X, y
            X_val, y_val = validation_data

        # Train model
        model = self._train_lgbm(X_train, y_train, X_val, y_val)

        # Calibrate probabilities
        calibrated_model = self._calibrate_model(model, X_train, y_train)

        # Evaluate model
        metrics = self._evaluate_model(model, calibrated_model, X_val, y_val)

        # Create training metadata
        training_metadata = {
            "training_samples": len(X_train),
            "validation_samples": len(X_val),
            "feature_count": X_train.shape[1],
            "features_hash": features_hash,
            "targets_hash": targets_hash,
            "class_distribution": y_train.value_counts().to_dict(),
            "class_weight_summary": self._last_weight_summary,
            "model_params": self.lgbm_params,
            "training_config": self.config,
        }

        training_time = time.time() - start_time

        return TrainingResult(
            model=model,
            calibrated_model=calibrated_model,
            metrics=metrics,
            training_metadata=training_metadata,
            training_time_seconds=training_time,
        )

    def _prepare_data(
        self, features: pd.DataFrame, labels: pd.Series
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Prepare data for training."""
        # Align features and labels
        aligned_data = pd.concat([features, labels], axis=1, join="inner")
        X = aligned_data.drop(columns=[labels.name])
        y = aligned_data[labels.name]

        # Handle missing values
        X = X.fillna(0)  # Simple imputation for now

        # Ensure proper data types
        for col in X.columns:
            if X[col].dtype == "object":
                X[col] = pd.to_numeric(X[col], errors="coerce")
                X[col] = X[col].fillna(0)

        return X, y

    def _split_data(
        self, X: pd.DataFrame, y: pd.Series
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        """Split data into training and validation sets."""
        val_split = self.training_params.get("validation_split", 0.2)
        stratify = self.training_params.get("stratify_by_class", True)

        if stratify and len(y.unique()) > 1:
            X_train, X_val, y_train, y_val = train_test_split(
                X,
                y,
                test_size=val_split,
                random_state=self.config.get("reproducibility", {}).get("seed", 42),
                stratify=y,
            )
        else:
            X_train, X_val, y_train, y_val = train_test_split(
                X,
                y,
                test_size=val_split,
                random_state=self.config.get("reproducibility", {}).get("seed", 42),
            )

        return X_train, X_val, y_train, y_val

    def _train_lgbm(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame,
        y_val: pd.Series,
    ) -> lgb.LGBMClassifier:
        """Train LightGBM model."""
        # Prepare parameters
        params = self.lgbm_params.copy()
        params["objective"] = "multiclass"
        params["num_class"] = len(np.unique(y_train))

        sample_weight = self._resolve_sample_weights(y_train)

        # Create callbacks
        callbacks = []
        early_stopping_rounds = self.training_params.get("early_stopping_rounds", 20)
        if early_stopping_rounds > 0:
            callbacks.append(lgb.early_stopping(early_stopping_rounds))

        # Train model
        model = lgb.LGBMClassifier(**params)

        model.fit(
            X_train,
            y_train,
            sample_weight=sample_weight,
            eval_set=[(X_val, y_val)],
            eval_metric=self.training_params.get("eval_metric", "multi_logloss"),
            callbacks=callbacks,
        )

        return model

    def _resolve_sample_weights(self, y_train: pd.Series) -> np.ndarray | None:
        """Determine sample weights based on configured strategies."""
        if y_train.empty:
            return None

        weights_map: dict[int, float] = {}

        if self.class_weight_strategy.get("enabled"):
            weights_map = self._compute_auto_weights(y_train)
        elif self.class_weight_base:
            weights_map = {
                int(class_label): float(weight)
                for class_label, weight in self.class_weight_base.items()
            }
            counts = {
                int(cls): int(count)
                for cls, count in y_train.value_counts().items()
            }
            self._last_weight_summary = {
                "auto": False,
                "weights": dict(sorted(weights_map.items())),
                "counts": counts,
            }

        if not weights_map:
            return None

        sample_weight = np.ones(len(y_train), dtype=float)
        for class_label, weight in weights_map.items():
            mask = y_train == class_label
            if mask.any():
                sample_weight[mask] = float(max(weight, 1e-6))

        return sample_weight

    def _compute_auto_weights(self, y_train: pd.Series) -> dict[int, float]:
        """Blend base class weights with inverse-frequency balancing."""
        strategy = self.class_weight_strategy or {}
        base = {
            int(cls): float(self.class_weight_base.get(cls, 1.0))
            for cls in (-1, 0, 1)
        }
        counts = {int(cls): int(count) for cls, count in y_train.value_counts().items()}
        total = float(len(y_train))
        mix = float(strategy.get("mix", 0.65))
        mix = min(max(mix, 0.0), 1.0)
        missing_multiplier = float(strategy.get("missing_class_weight", 1.3))

        balanced = {}
        for cls in (-1, 0, 1):
            count = counts.get(cls, 0)
            if count <= 0:
                balanced[cls] = base.get(cls, 1.0) * missing_multiplier
            else:
                balanced[cls] = total / (3.0 * count)

        weights = {}
        for cls in (-1, 0, 1):
            base_weight = base.get(cls, 1.0)
            balanced_weight = balanced.get(cls, 1.0)
            weights[cls] = (base_weight ** (1.0 - mix)) * (balanced_weight ** mix)

        if strategy.get("equalize_directional", True):
            directional_weight = float(
                np.mean([weights.get(-1, 1.0), weights.get(1, 1.0)])
            )
            weights[-1] = directional_weight
            weights[1] = directional_weight

        target_ratio = float(strategy.get("target_ratio", 1.0))
        tolerance = float(strategy.get("tolerance", 0.15))
        ratio_adjust = float(strategy.get("ratio_adjust", 0.35))

        long_count = counts.get(1, 0)
        short_count = counts.get(-1, 0)
        if long_count > 0 and short_count > 0:
            ratio = long_count / max(short_count, 1)
            if ratio > target_ratio + tolerance:
                weights[1] *= max(1.0 - ratio_adjust, 0.05)
                weights[-1] *= 1.0 + ratio_adjust
            elif ratio < target_ratio - tolerance:
                weights[1] *= 1.0 + ratio_adjust
                weights[-1] *= max(1.0 - ratio_adjust, 0.05)

        neutral_floor = float(strategy.get("neutral_weight_floor", 0.3))
        neutral_cap = float(strategy.get("neutral_weight_cap", 0.7))
        weights[0] = float(np.clip(weights.get(0, 1.0), neutral_floor, neutral_cap))

        min_weight = float(strategy.get("min_weight", 0.05))
        max_weight = float(strategy.get("max_weight", 5.0))
        for cls in list(weights):
            weights[cls] = float(
                np.clip(weights[cls], min_weight, max_weight)
            )

        if strategy.get("normalize", True):
            mean_weight = float(np.mean(list(weights.values())))
            if mean_weight > 0.0 and np.isfinite(mean_weight):
                for cls in list(weights):
                    weights[cls] = float(weights[cls] / mean_weight)

        self._last_weight_summary = {
            "auto": True,
            "weights": dict(sorted((int(k), float(v)) for k, v in weights.items())),
            "counts": {int(k): counts.get(k, 0) for k in (-1, 0, 1)},
            "mix": mix,
            "target_ratio": target_ratio,
        }
        return weights

    def _calibrate_model(
        self, model: lgb.LGBMClassifier, X_train: pd.DataFrame, y_train: pd.Series
    ) -> CalibratedClassifierCV:
        """Calibrate model probabilities."""
        if not self.calibration_config.get("enabled", True):
            # Return wrapped model without calibration
            return model

        calibration_method = self.calibration_config.get("method", "isotonic")
        cv_folds = self.calibration_config.get("cv_folds", 5)

        calibrated = CalibratedClassifierCV(
            model, method=calibration_method, cv=cv_folds
        )

        calibrated.fit(X_train, y_train)

        return calibrated

    def _evaluate_model(
        self,
        model: lgb.LGBMClassifier,
        calibrated_model: CalibratedClassifierCV,
        X_val: pd.DataFrame,
        y_val: pd.Series,
    ) -> dict[str, Any]:
        """Evaluate model performance."""
        # Get predictions
        y_pred = model.predict(X_val)
        y_proba = model.predict_proba(X_val)
        y_proba_calibrated = calibrated_model.predict_proba(X_val)

        # Calculate trade density proxy
        trade_density = np.mean(y_pred != 0)

        # Calculate metrics
        accuracy = accuracy_score(y_val, y_pred)
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_val, y_pred, average="macro"
        )
        brier_score = brier_score_loss(y_val, y_proba, labels=model.classes_)
        brier_score_calibrated = brier_score_loss(
            y_val, y_proba_calibrated, labels=model.classes_
        )
        logloss_val = log_loss(y_val, y_proba, labels=model.classes_)
        logloss_calibrated = log_loss(y_val, y_proba_calibrated, labels=model.classes_)

        # Class-specific metrics
        precision_per_class, recall_per_class, f1_per_class, _ = (
            precision_recall_fscore_support(
                y_val, y_pred, average=None, labels=model.classes_
            )
        )

        # Feature importance
        feature_importance = dict(
            zip(X_val.columns, model.feature_importances_, strict=False)
        )
        top_features = sorted(
            feature_importance.items(), key=lambda x: x[1], reverse=True
        )[:10]

        metrics = {
            "accuracy": accuracy,
            "precision_macro": precision,
            "recall_macro": recall,
            "f1_macro": f1,
            "brier_score": brier_score,
            "brier_score_calibrated": brier_score_calibrated,
            "brier_improvement": brier_score - brier_score_calibrated,
            "log_loss": logloss_val,
            "log_loss_calibrated": logloss_calibrated,
            "trade_density": trade_density,
            "class_metrics": {
                str(cls): {
                    "precision": float(precision_per_class[i]),
                    "recall": float(recall_per_class[i]),
                    "f1": float(f1_per_class[i]),
                }
                for i, cls in enumerate(model.classes_)
            },
            "feature_importance": feature_importance,
            "top_features": top_features,
            "num_features": len(X_val.columns),
        }

        return metrics

    def cross_validate(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
        features_hash: str,
        targets_hash: str,
    ) -> dict[str, Any]:
        """Perform cross-validation for model evaluation."""
        cv_config = self.config.get("evaluation", {}).get("cross_validation", {})
        if not cv_config.get("enabled", False):
            return {"cv_enabled": False}

        X, y = self._prepare_data(features, labels)
        cv_folds = cv_config.get("folds", 5)
        cv_config.get("stratify", True)

        cv = StratifiedKFold(
            n_splits=cv_folds,
            shuffle=True,
            random_state=self.config.get("reproducibility", {}).get("seed", 42),
        )

        cv_scores = {
            "accuracy": [],
            "precision_macro": [],
            "recall_macro": [],
            "f1_macro": [],
            "brier_score": [],
            "brier_score_calibrated": [],
        }

        fold_results = []

        for fold, (train_idx, val_idx) in enumerate(cv.split(X, y)):
            X_train_fold, X_val_fold = X.iloc[train_idx], X.iloc[val_idx]
            y_train_fold, y_val_fold = y.iloc[train_idx], y.iloc[val_idx]

            # Train model
            model = self._train_lgbm(X_train_fold, y_train_fold, X_val_fold, y_val_fold)
            calibrated_model = self._calibrate_model(model, X_train_fold, y_train_fold)

            # Evaluate
            metrics = self._evaluate_model(
                model, calibrated_model, X_val_fold, y_val_fold
            )

            # Collect scores
            for metric in cv_scores:
                if metric in metrics:
                    cv_scores[metric].append(metrics[metric])

            fold_results.append(
                {
                    "fold": fold + 1,
                    "metrics": metrics,
                    "training_samples": len(X_train_fold),
                    "validation_samples": len(X_val_fold),
                }
            )

        # Calculate mean and std
        cv_summary = {}
        for metric, scores in cv_scores.items():
            cv_summary[f"{metric}_mean"] = np.mean(scores)
            cv_summary[f"{metric}_std"] = np.std(scores)

        return {
            "cv_enabled": True,
            "cv_summary": cv_summary,
            "fold_results": fold_results,
            "cv_folds": cv_folds,
        }


def train_lgbm_model(
    features: pd.DataFrame,
    labels: pd.Series,
    model_config: dict[str, Any],
    features_hash: str,
    targets_hash: str,
) -> TrainingResult:
    """Convenience function to train LightGBM model.

    Args:
        features: Feature DataFrame
        labels: Label Series
        model_config: Model configuration
        features_hash: Hash of feature data
        targets_hash: Hash of target data

    Returns:
        TrainingResult with trained model and metrics
    """
    trainer = LightGBMTrainer(model_config)
    return trainer.train_model(features, labels, features_hash, targets_hash)
