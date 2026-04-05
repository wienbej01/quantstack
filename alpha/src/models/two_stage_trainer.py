"""Two-stage ML baselines for live-aligned trading research."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from ..data.ml_labels import WalkForwardFold
from .xgb_trainer import FoldResult, TrainingResult

logger = logging.getLogger(__name__)


@dataclass
class TwoStageCalibrator:
    """Validation-only calibration for trade and direction probabilities."""

    trade_calibrator: Optional[IsotonicRegression] = None
    direction_calibrator: Optional[IsotonicRegression] = None


def _build_feature_indices(
    feature_cols: List[str],
    stage1_feature_cols: Optional[List[str]],
    stage2_feature_cols: Optional[List[str]],
) -> tuple[np.ndarray, np.ndarray]:
    feature_index = {name: idx for idx, name in enumerate(feature_cols)}
    stage1_names = stage1_feature_cols or feature_cols
    stage2_names = stage2_feature_cols or feature_cols
    stage1_idx = np.array([feature_index[name] for name in stage1_names], dtype=int)
    stage2_idx = np.array([feature_index[name] for name in stage2_names], dtype=int)
    return stage1_idx, stage2_idx


class _TwoStageModelBase:
    """Shared probability composition for two-stage models."""

    def __init__(
        self,
        feature_cols: List[str],
        stage1_feature_cols: Optional[List[str]] = None,
        stage2_feature_cols: Optional[List[str]] = None,
    ) -> None:
        self.feature_cols = feature_cols
        self.stage1_feature_cols = stage1_feature_cols or feature_cols
        self.stage2_feature_cols = stage2_feature_cols or feature_cols
        self._stage1_idx, self._stage2_idx = _build_feature_indices(
            feature_cols,
            self.stage1_feature_cols,
            self.stage2_feature_cols,
        )
        self.calibrator = TwoStageCalibrator()

    def _trade_X(self, X: np.ndarray) -> np.ndarray:
        return X[:, self._stage1_idx]

    def _direction_X(self, X: np.ndarray) -> np.ndarray:
        return X[:, self._stage2_idx]

    def fit_calibrator(self, X_val: np.ndarray, y_val: np.ndarray) -> None:
        labels = np.asarray(y_val, dtype=int)
        trade_probs = self._predict_trade_probability(X_val)
        trade_y = (labels != 1).astype(np.float64)
        self.calibrator.trade_calibrator = IsotonicRegression(
            out_of_bounds="clip",
            y_min=0.0,
            y_max=1.0,
        ).fit(trade_probs, trade_y)

        direction_mask = labels != 1
        if direction_mask.any():
            direction_probs = self._predict_up_given_trade(X_val[direction_mask])
            direction_y = (labels[direction_mask] == 2).astype(np.float64)
            if np.unique(direction_y).size >= 2:
                self.calibrator.direction_calibrator = IsotonicRegression(
                    out_of_bounds="clip",
                    y_min=0.0,
                    y_max=1.0,
                ).fit(direction_probs, direction_y)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        trade_prob = self._predict_trade_probability(X)
        if self.calibrator.trade_calibrator is not None:
            trade_prob = self.calibrator.trade_calibrator.predict(trade_prob)

        up_given_trade = self._predict_up_given_trade(X)
        if self.calibrator.direction_calibrator is not None:
            up_given_trade = self.calibrator.direction_calibrator.predict(
                up_given_trade
            )

        trade_prob = np.clip(trade_prob, 1e-6, 1.0 - 1e-6)
        up_given_trade = np.clip(up_given_trade, 1e-6, 1.0 - 1e-6)
        p_up = trade_prob * up_given_trade
        p_down = trade_prob * (1.0 - up_given_trade)
        p_flat = 1.0 - trade_prob
        stacked = np.column_stack([p_down, p_flat, p_up])
        row_sums = stacked.sum(axis=1, keepdims=True)
        return stacked / np.where(row_sums <= 0, 1.0, row_sums)

    def predict(self, X: np.ndarray) -> np.ndarray:
        return np.asarray(np.argmax(self.predict_proba(X), axis=1), dtype=int)


class TwoStageLogisticModel(_TwoStageModelBase):
    """Trade-vs-flat first, then long-vs-short on eligible rows."""

    def __init__(
        self,
        *,
        c: float = 1.0,
        max_iter: int = 1000,
        class_weight: str | dict | None = "balanced",
        random_state: int = 42,
        feature_cols: Optional[List[str]] = None,
        stage1_feature_cols: Optional[List[str]] = None,
        stage2_feature_cols: Optional[List[str]] = None,
    ) -> None:
        if feature_cols is None:
            raise ValueError("feature_cols must be provided for two-stage models")
        super().__init__(feature_cols, stage1_feature_cols, stage2_feature_cols)
        self.trade_scaler = StandardScaler()
        self.direction_scaler = StandardScaler()
        self.trade_model = LogisticRegression(
            C=c,
            max_iter=max_iter,
            class_weight=class_weight,
            random_state=random_state,
            solver="lbfgs",
        )
        self.direction_model = LogisticRegression(
            C=c,
            max_iter=max_iter,
            class_weight=class_weight,
            random_state=random_state,
            solver="lbfgs",
        )

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        sample_weight: Optional[np.ndarray] = None,
    ) -> "TwoStageLogisticModel":
        labels = np.asarray(y, dtype=int)
        trade_y = (labels != 1).astype(int)
        direction_mask = trade_y == 1
        if not direction_mask.any():
            raise RuntimeError("two-stage model requires at least one non-flat row")
        direction_y = (labels[direction_mask] == 2).astype(int)
        if np.unique(direction_y).size < 2:
            raise RuntimeError(
                "two-stage direction model requires both long and short examples"
            )

        weights = (
            None
            if sample_weight is None
            else np.asarray(sample_weight, dtype=np.float64)
        )
        X_trade = self._trade_X(X)
        X_direction = self._direction_X(X)
        self.trade_scaler.fit(X_trade)
        trade_scaled = self.trade_scaler.transform(X_trade)
        self.trade_model.fit(trade_scaled, trade_y, sample_weight=weights)
        dir_weights = None if weights is None else weights[direction_mask]
        self.direction_scaler.fit(X_direction[direction_mask])
        direction_scaled = self.direction_scaler.transform(X_direction[direction_mask])
        self.direction_model.fit(
            direction_scaled,
            direction_y,
            sample_weight=dir_weights,
        )
        return self

    def _predict_trade_probability(self, X: np.ndarray) -> np.ndarray:
        trade_scaled = self.trade_scaler.transform(self._trade_X(X))
        return self.trade_model.predict_proba(trade_scaled)[:, 1]

    def _predict_up_given_trade(self, X: np.ndarray) -> np.ndarray:
        direction_scaled = self.direction_scaler.transform(self._direction_X(X))
        return self.direction_model.predict_proba(direction_scaled)[:, 1]

    def feature_importance(self, feature_cols: List[str]) -> Dict[str, float]:
        combined = np.zeros(len(feature_cols), dtype=np.float64)
        combined[self._stage1_idx] += np.abs(self.trade_model.coef_[0])
        combined[self._stage2_idx] += np.abs(self.direction_model.coef_[0])
        total = float(combined.sum())
        if total <= 0:
            return {name: 0.0 for name in feature_cols}
        return {
            name: float(value / total) for name, value in zip(feature_cols, combined)
        }


class TwoStageXGBModel(_TwoStageModelBase):
    """Two-stage binary XGBoost model."""

    def __init__(
        self,
        *,
        feature_cols: List[str],
        stage1_feature_cols: Optional[List[str]] = None,
        stage2_feature_cols: Optional[List[str]] = None,
        trade_params: Optional[dict] = None,
        direction_params: Optional[dict] = None,
    ) -> None:
        super().__init__(feature_cols, stage1_feature_cols, stage2_feature_cols)
        base_params = {
            "max_depth": 3,
            "n_estimators": 200,
            "learning_rate": 0.05,
            "subsample": 0.7,
            "colsample_bytree": 0.5,
            "min_child_weight": 100,
            "gamma": 1.0,
            "reg_alpha": 0.5,
            "reg_lambda": 2.0,
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "tree_method": "hist",
            "random_state": 42,
            "n_jobs": 1,
            "verbosity": 0,
        }
        self.trade_model = XGBClassifier(**{**base_params, **(trade_params or {})})
        self.direction_model = XGBClassifier(
            **{**base_params, "min_child_weight": 50, **(direction_params or {})}
        )

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        sample_weight: Optional[np.ndarray] = None,
    ) -> "TwoStageXGBModel":
        labels = np.asarray(y, dtype=int)
        trade_y = (labels != 1).astype(int)
        direction_mask = trade_y == 1
        if not direction_mask.any():
            raise RuntimeError("two-stage model requires at least one non-flat row")
        direction_y = (labels[direction_mask] == 2).astype(int)
        if np.unique(direction_y).size < 2:
            raise RuntimeError(
                "two-stage direction model requires both long and short examples"
            )

        weights = (
            None
            if sample_weight is None
            else np.asarray(sample_weight, dtype=np.float64)
        )
        self.trade_model.fit(
            self._trade_X(X), trade_y, sample_weight=weights, verbose=False
        )
        dir_weights = None if weights is None else weights[direction_mask]
        self.direction_model.fit(
            self._direction_X(X[direction_mask]),
            direction_y,
            sample_weight=dir_weights,
            verbose=False,
        )
        return self

    def _predict_trade_probability(self, X: np.ndarray) -> np.ndarray:
        return self.trade_model.predict_proba(self._trade_X(X))[:, 1]

    def _predict_up_given_trade(self, X: np.ndarray) -> np.ndarray:
        return self.direction_model.predict_proba(self._direction_X(X))[:, 1]

    def feature_importance(self, feature_cols: List[str]) -> Dict[str, float]:
        combined = np.zeros(len(feature_cols), dtype=np.float64)
        combined[self._stage1_idx] += np.asarray(
            self.trade_model.feature_importances_, dtype=np.float64
        )
        combined[self._stage2_idx] += np.asarray(
            self.direction_model.feature_importances_, dtype=np.float64
        )
        total = float(combined.sum())
        if total <= 0:
            return {name: 0.0 for name in feature_cols}
        return {
            name: float(value / total) for name, value in zip(feature_cols, combined)
        }


def _train_two_stage_walk_forward(
    df: pd.DataFrame,
    feature_cols: List[str],
    stage1_feature_cols: List[str],
    stage2_feature_cols: List[str],
    label_col: str,
    folds: List[WalkForwardFold],
    model_factory,
    model_family: str,
    sample_weights: Optional[np.ndarray] = None,
) -> TrainingResult:
    """Train a two-stage model with walk-forward validation."""
    fold_results: list[FoldResult] = []
    dates = df["date"].to_numpy()
    X_all = np.nan_to_num(df[feature_cols].to_numpy(dtype=np.float32, copy=True))
    y_all = df[label_col].to_numpy()
    weights_all = (
        None if sample_weights is None else np.asarray(sample_weights, dtype=np.float64)
    )

    for fold in folds:
        train_mask = np.isin(dates, fold.train_dates)
        val_mask = np.isin(dates, fold.val_dates)

        X_train = X_all[train_mask]
        y_train = y_all[train_mask]
        X_val = X_all[val_mask]
        y_val = y_all[val_mask]
        w_train = None if weights_all is None else weights_all[train_mask]

        train_valid = ~np.isnan(y_train)
        val_valid = ~np.isnan(y_val)
        X_train = X_train[train_valid]
        y_train = y_train[train_valid].astype(int)
        X_val = X_val[val_valid]
        y_val = y_val[val_valid].astype(int)
        if w_train is not None:
            w_train = w_train[train_valid]

        if len(X_train) < 100 or len(X_val) < 10:
            logger.warning("Fold %s: insufficient data, skipping", fold.fold_idx)
            continue

        model = model_factory(feature_cols, stage1_feature_cols, stage2_feature_cols)
        model.fit(X_train, y_train, sample_weight=w_train)
        train_pred = model.predict(X_train)
        val_pred = model.predict(X_val)
        train_acc = accuracy_score(y_train, train_pred)
        val_acc = accuracy_score(y_val, val_pred)
        report = classification_report(
            y_val,
            val_pred,
            target_names=["down", "flat", "up"],
            zero_division=0,
        )

        fold_results.append(
            FoldResult(
                fold_idx=fold.fold_idx,
                train_acc=train_acc,
                val_acc=val_acc,
                val_report=report,
                feature_importance=model.feature_importance(feature_cols),
                model=model,
            )
        )
        logger.info(
            "%s fold %s: train_acc=%.3f, val_acc=%.3f",
            model_family,
            fold.fold_idx,
            train_acc,
            val_acc,
        )

    if not fold_results:
        raise RuntimeError("No folds completed successfully")

    mean_val = float(np.mean([f.val_acc for f in fold_results]))
    mean_train = float(np.mean([f.train_acc for f in fold_results]))
    best_idx = int(np.argmax([f.val_acc for f in fold_results]))
    horizon = int(label_col.split("_")[-1].replace("s", "")) if "s" in label_col else 0

    return TrainingResult(
        fold_results=fold_results,
        best_fold_idx=best_idx,
        mean_val_acc=mean_val,
        train_val_gap=mean_train - mean_val,
        feature_columns=feature_cols,
        horizon=horizon,
        model_family=model_family,
    )


def train_two_stage_walk_forward(
    df: pd.DataFrame,
    feature_cols: List[str],
    stage1_feature_cols: List[str],
    stage2_feature_cols: List[str],
    label_col: str,
    folds: List[WalkForwardFold],
    sample_weights: Optional[np.ndarray] = None,
) -> TrainingResult:
    """Train the 2-stage logistic baseline with walk-forward validation."""
    return _train_two_stage_walk_forward(
        df,
        feature_cols,
        stage1_feature_cols,
        stage2_feature_cols,
        label_col,
        folds,
        lambda cols, s1, s2: TwoStageLogisticModel(
            feature_cols=cols,
            stage1_feature_cols=s1,
            stage2_feature_cols=s2,
        ),
        "two_stage_logistic",
        sample_weights=sample_weights,
    )


def train_two_stage_xgb_walk_forward(
    df: pd.DataFrame,
    feature_cols: List[str],
    stage1_feature_cols: List[str],
    stage2_feature_cols: List[str],
    label_col: str,
    folds: List[WalkForwardFold],
    sample_weights: Optional[np.ndarray] = None,
) -> TrainingResult:
    """Train the 2-stage binary XGBoost baseline with walk-forward validation."""
    return _train_two_stage_walk_forward(
        df,
        feature_cols,
        stage1_feature_cols,
        stage2_feature_cols,
        label_col,
        folds,
        lambda cols, s1, s2: TwoStageXGBModel(
            feature_cols=cols,
            stage1_feature_cols=s1,
            stage2_feature_cols=s2,
        ),
        "two_stage_xgb",
        sample_weights=sample_weights,
    )
