"""
Two-stage LightGBM trainers for Sprint 3 big-move targets.

Stage 1 learns the probability of observing a large ATR-scaled move.
Stage 2 consumes the conditioned samples (``big_move == 1``) to learn
directional odds and an optional expected-R regression.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    log_loss,
    mean_absolute_error,
    mean_squared_error,
    precision_recall_fscore_support,
    r2_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split


@dataclass
class StageTrainingResult:
    """Container for stage-specific training artefacts."""

    model: lgb.LGBMModel
    metrics: dict[str, float]
    feature_importances: pd.Series
    training_samples: int
    validation_samples: int
    label_name: str


class BigMoveModelTrainer:
    """Trains big-move probability, direction, and expected-R models."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        label_cfg = self.config.get("labels", {})
        self.big_move_label = label_cfg.get("big_move", "y_bigmove")
        self.direction_label = label_cfg.get("direction", "y_bigmove_direction")
        self.realized_r_label = label_cfg.get("realized_r", "realized_r_bigmove")
        self.forward_return_column = label_cfg.get("forward_return", "fwd_return_bigmove")
        winsor_cfg = self.config.get("regression", {}).get("winsorize", {})
        self.realized_r_floor = float(winsor_cfg.get("floor", -5.0))
        self.realized_r_cap = float(winsor_cfg.get("cap", 5.0))
        self.random_state = int(self.config.get("random_state", 17))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def train_stage1_probability(
        self,
        features: pd.DataFrame,
        labels: pd.DataFrame,
    ) -> StageTrainingResult:
        """Train the binary big-move probability model."""
        label_series = _require_column(labels, self.big_move_label)
        if label_series.nunique() < 2:
            raise ValueError("Stage 1 requires both positive and negative big-move samples.")

        X, y = self._align_features(features, label_series)
        return self._train_classifier(
            X,
            y,
            stage_cfg=self.config.get("stage1", {}),
            label_name=self.big_move_label,
        )

    def train_stage2_direction(
        self,
        features: pd.DataFrame,
        labels: pd.DataFrame,
    ) -> StageTrainingResult:
        """Train the direction classifier conditioned on big-move samples."""
        base_mask = _require_column(labels, self.big_move_label) == 1
        direction_raw = _require_column(labels, self.direction_label).loc[base_mask]
        if direction_raw.empty:
            raise ValueError("No conditioned samples available for direction training.")

        direction_binary = direction_raw.map({-1: 0, 1: 1})
        if direction_binary.nunique() < 2:
            raise ValueError("Direction training needs both long and short outcomes.")

        X = features.loc[direction_binary.index]
        return self._train_classifier(
            X,
            direction_binary,
            stage_cfg=self.config.get("stage2_direction", {}),
            label_name=self.direction_label,
        )

    def train_stage2_expected_r(
        self,
        features: pd.DataFrame,
        labels: pd.DataFrame,
    ) -> StageTrainingResult:
        """Train an expected-R regression on conditioned samples."""
        base_mask = _require_column(labels, self.big_move_label) == 1
        realized_r = _require_column(labels, self.realized_r_label).loc[base_mask]
        if realized_r.empty:
            raise ValueError("No realized-R samples available for regression training.")

        realized_r = realized_r.clip(lower=self.realized_r_floor, upper=self.realized_r_cap)
        X = features.loc[realized_r.index]
        return self._train_regressor(
            X,
            realized_r,
            stage_cfg=self.config.get("stage2_expected_r", {}),
            label_name=self.realized_r_label,
        )

    def train_all_stages(
        self,
        features: pd.DataFrame,
        labels: pd.DataFrame,
    ) -> Dict[str, StageTrainingResult]:
        """Train all configured stages and return a mapping of results."""
        results = {
            "stage1": self.train_stage1_probability(features, labels),
        }
        if self.config.get("stage2_direction", {}).get("enabled", True):
            results["stage2_direction"] = self.train_stage2_direction(features, labels)
        if self.config.get("stage2_expected_r", {}).get("enabled", True):
            results["stage2_expected_r"] = self.train_stage2_expected_r(features, labels)
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _train_classifier(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        *,
        stage_cfg: dict[str, Any],
        label_name: str,
    ) -> StageTrainingResult:
        X_clean = _clean_features(X)
        y_clean = y.astype(int)
        params = {
            "n_estimators": 200,
            "learning_rate": 0.05,
            "max_depth": 5,
            "min_child_samples": 20,
            "subsample": 0.9,
            "colsample_bytree": 0.8,
            "random_state": self.random_state,
            "n_jobs": -1,
        }
        params.update(stage_cfg.get("lgbm_params", {}))
        val_split = float(stage_cfg.get("validation_split", 0.25))
        X_train, X_val, y_train, y_val = self._split(X_clean, y_clean, val_split, stratify=True)

        model = lgb.LGBMClassifier(**params)
        model.fit(X_train, y_train)

        val_proba = model.predict_proba(X_val)[:, 1]
        val_pred = (val_proba >= stage_cfg.get("decision_threshold", 0.5)).astype(int)
        metrics = self._classifier_metrics(y_val, val_pred, val_proba)

        return StageTrainingResult(
            model=model,
            metrics=metrics,
            feature_importances=pd.Series(model.feature_importances_, index=X_train.columns),
            training_samples=len(X_train),
            validation_samples=len(X_val),
            label_name=label_name,
        )

    def _train_regressor(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        *,
        stage_cfg: dict[str, Any],
        label_name: str,
    ) -> StageTrainingResult:
        X_clean = _clean_features(X)
        y_clean = y.astype(float)
        params = {
            "n_estimators": 300,
            "learning_rate": 0.05,
            "max_depth": 5,
            "subsample": 0.9,
            "random_state": self.random_state,
            "n_jobs": -1,
        }
        params.update(stage_cfg.get("lgbm_params", {}))
        val_split = float(stage_cfg.get("validation_split", 0.25))
        X_train, X_val, y_train, y_val = self._split(X_clean, y_clean, val_split, stratify=False)

        model = lgb.LGBMRegressor(**params)
        model.fit(X_train, y_train)
        val_pred = model.predict(X_val)
        metrics = self._regression_metrics(y_val, val_pred)

        return StageTrainingResult(
            model=model,
            metrics=metrics,
            feature_importances=pd.Series(model.feature_importances_, index=X_train.columns),
            training_samples=len(X_train),
            validation_samples=len(X_val),
            label_name=label_name,
        )

    def _align_features(
        self,
        features: pd.DataFrame,
        labels: pd.Series,
    ) -> tuple[pd.DataFrame, pd.Series]:
        labels = labels.copy()
        labels.name = labels.name or "label"
        aligned = features.join(labels, how="inner")
        X = aligned.drop(columns=[labels.name])
        y = aligned[labels.name]
        if X.empty or y.empty:
            raise ValueError("No overlapping samples between features and labels.")
        return X, y

    def _split(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        val_split: float,
        stratify: bool,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
        if val_split <= 0 or len(y) < 4:
            return X, X.copy(), y, y.copy()
        stratify_arg = y if stratify and y.nunique() > 1 else None
        X_train, X_val, y_train, y_val = train_test_split(
            X,
            y,
            test_size=val_split,
            random_state=self.random_state,
            stratify=stratify_arg,
        )
        return X_train, X_val, y_train, y_val

    @staticmethod
    def _classifier_metrics(
        y_true: pd.Series,
        y_pred: np.ndarray,
        y_proba: np.ndarray,
    ) -> dict[str, float]:
        precision, recall, f1, _ = precision_recall_fscore_support(
            y_true, y_pred, average="binary", zero_division=0
        )
        metrics = {
            "accuracy": float(accuracy_score(y_true, y_pred)),
            "precision": float(precision),
            "recall": float(recall),
            "f1": float(f1),
            "log_loss": float(log_loss(y_true, np.clip(y_proba, 1e-6, 1 - 1e-6))),
        }
        if len(np.unique(y_true)) > 1:
            metrics["roc_auc"] = float(roc_auc_score(y_true, y_proba))
        return metrics

    @staticmethod
    def _regression_metrics(y_true: pd.Series, y_pred: np.ndarray) -> dict[str, float]:
        mse = float(mean_squared_error(y_true, y_pred))
        return {
            "mae": float(mean_absolute_error(y_true, y_pred)),
            "rmse": float(math.sqrt(max(mse, 0.0))),
            "r2": float(r2_score(y_true, y_pred)),
        }


def _clean_features(features: pd.DataFrame) -> pd.DataFrame:
    cleaned = features.copy()
    for column in cleaned.columns:
        cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce")
    return cleaned.fillna(0.0)


def _require_column(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        raise KeyError(f"Column '{column}' missing from provided labels/frame.")
    series = df[column]
    series.name = column
    return series


__all__ = [
    "BigMoveModelTrainer",
    "StageTrainingResult",
]
