"""XGBoost trainer with walk-forward cross-validation."""

import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report
from sklearn.isotonic import IsotonicRegression
from xgboost import XGBClassifier

from ..data.ml_labels import WalkForwardFold, walk_forward_folds

logger = logging.getLogger(__name__)

DEFAULT_PARAMS = dict(
    max_depth=3,
    n_estimators=120,
    learning_rate=0.05,
    subsample=0.7,
    colsample_bytree=0.5,
    min_child_weight=100,
    gamma=1.0,
    reg_alpha=0.5,
    reg_lambda=2.0,
    objective="multi:softprob",
    num_class=3,
    eval_metric="mlogloss",
    tree_method="hist",
    random_state=42,
    n_jobs=1,
    verbosity=0,
)


@dataclass
class FoldResult:
    fold_idx: int
    train_acc: float
    val_acc: float
    val_report: str
    feature_importance: Dict[str, float]
    model: XGBClassifier


@dataclass
class TrainingResult:
    fold_results: List[FoldResult]
    best_fold_idx: int
    mean_val_acc: float
    train_val_gap: float
    feature_columns: List[str]
    horizon: int
    model_family: str = "xgb_multiclass"
    calibrator: Optional["MulticlassIsotonicCalibrator"] = None
    threshold_selection: list[dict] = field(default_factory=list)
    recommended_threshold: Optional[float] = None

    @property
    def best_model(self) -> XGBClassifier:
        return self.fold_results[self.best_fold_idx].model


@dataclass
class MulticlassIsotonicCalibrator:
    """One-vs-rest isotonic calibration for 3-class probabilities."""

    class_labels: tuple[int, ...] = (0, 1, 2)
    calibrators: list[IsotonicRegression] = field(default_factory=list)

    def fit(
        self, probabilities: np.ndarray, labels: np.ndarray
    ) -> "MulticlassIsotonicCalibrator":
        """Fit one isotonic regressor per class on validation probabilities."""
        probs = np.asarray(probabilities, dtype=np.float64)
        y = np.asarray(labels, dtype=int)
        if probs.ndim != 2 or probs.shape[1] != len(self.class_labels):
            raise ValueError(
                "probabilities must be shape (n_samples, 3) for multiclass isotonic calibration"
            )
        if len(probs) != len(y):
            raise ValueError(
                "probabilities and labels must have the same number of rows"
            )

        self.calibrators = []
        for class_idx, class_label in enumerate(self.class_labels):
            calibrator = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            calibrator.fit(probs[:, class_idx], (y == class_label).astype(np.float64))
            self.calibrators.append(calibrator)
        return self

    def predict_proba(self, probabilities: np.ndarray) -> np.ndarray:
        """Calibrate class probabilities and renormalize them to sum to one."""
        probs = np.asarray(probabilities, dtype=np.float64)
        if probs.ndim != 2 or probs.shape[1] != len(self.class_labels):
            raise ValueError(
                "probabilities must be shape (n_samples, 3) for multiclass isotonic calibration"
            )
        if not self.calibrators:
            raise RuntimeError("calibrator has not been fit")

        calibrated = np.column_stack(
            [
                calibrator.predict(probs[:, idx])
                for idx, calibrator in enumerate(self.calibrators)
            ]
        )
        calibrated = np.clip(calibrated, 1e-9, None)
        row_sums = calibrated.sum(axis=1, keepdims=True)
        row_sums = np.where(row_sums <= 0, 1.0, row_sums)
        return calibrated / row_sums


def predict_calibrated_proba(
    model: XGBClassifier, X: np.ndarray, calibrator=None
) -> np.ndarray:
    """Predict class probabilities and apply optional post-hoc calibration."""
    probabilities = np.asarray(model.predict_proba(X), dtype=np.float64)
    if calibrator is None:
        return probabilities
    return calibrator.predict_proba(probabilities)


def fit_probability_calibrator(
    model: XGBClassifier,
    X_val: np.ndarray,
    y_val: np.ndarray,
) -> MulticlassIsotonicCalibrator:
    """Fit a multiclass isotonic calibrator on validation predictions only."""
    calibrator = MulticlassIsotonicCalibrator()
    calibrator.fit(model.predict_proba(X_val), y_val)
    return calibrator


def select_confidence_threshold(
    probabilities: np.ndarray,
    labels: np.ndarray,
    thresholds: Sequence[float],
    min_directional_precision: float = 0.0,
    min_trigger_count: int = 1,
) -> tuple[Optional[float], list[dict]]:
    """Select a directional entry threshold from validation probabilities.

    Score balances precision and activation density, with optional precision / trigger
    floors so threshold selection does not collapse into low-quality activation.
    """
    probs = np.asarray(probabilities, dtype=np.float64)
    y = np.asarray(labels, dtype=int)
    if probs.ndim != 2 or probs.shape[1] != 3:
        raise ValueError("probabilities must be shape (n_samples, 3)")
    if len(probs) != len(y):
        raise ValueError("probabilities and labels must have the same number of rows")

    p_down = probs[:, 0]
    p_up = probs[:, 2]
    predicted = np.where(p_up >= p_down, 2, 0)
    results: list[dict] = []

    best_threshold: Optional[float] = None
    best_score = -np.inf
    best_precision = -np.inf
    best_activation = -np.inf

    for threshold in thresholds:
        triggered = ((p_up >= threshold) & (p_up > p_down)) | (
            (p_down >= threshold) & (p_down > p_up)
        )
        trigger_count = int(triggered.sum())
        activation_rate = float(trigger_count / len(probs)) if len(probs) else 0.0
        if trigger_count:
            triggered_correct = (predicted[triggered] == y[triggered]).astype(
                np.float64
            )
            precision = float(triggered_correct.mean())
        else:
            precision = 0.0
        tradeoff_score = (
            float(precision * np.sqrt(activation_rate)) if trigger_count else 0.0
        )
        row = {
            "threshold": float(threshold),
            "trigger_count": trigger_count,
            "activation_rate": activation_rate,
            "directional_precision": precision,
            "tradeoff_score": tradeoff_score,
            "meets_precision_floor": bool(precision >= min_directional_precision),
            "meets_trigger_floor": bool(trigger_count >= min_trigger_count),
        }
        results.append(row)

        if precision < min_directional_precision or trigger_count < min_trigger_count:
            continue

        if tradeoff_score > best_score or (
            np.isclose(tradeoff_score, best_score)
            and (
                precision > best_precision
                or (
                    np.isclose(precision, best_precision)
                    and activation_rate > best_activation
                )
            )
        ):
            best_threshold = float(threshold)
            best_score = tradeoff_score
            best_precision = precision
            best_activation = activation_rate

    if best_threshold is None:
        for row in results:
            threshold = float(row["threshold"])
            precision = float(row["directional_precision"])
            activation_rate = float(row["activation_rate"])
            if precision > best_precision or (
                np.isclose(precision, best_precision)
                and activation_rate > best_activation
            ):
                best_threshold = threshold
                best_precision = precision
                best_activation = activation_rate

    return best_threshold, results


@dataclass(frozen=True)
class QualityGate:
    """Minimum thresholds required to accept a trained model."""

    min_val_accuracy: float = 0.38
    max_train_val_gap: float = 0.15
    min_test_accuracy: float = 0.34
    require_walk_forward: bool = True
    min_folds: int = 2


def train_walk_forward(
    df: pd.DataFrame,
    feature_cols: List[str],
    label_col: str,
    folds: List[WalkForwardFold],
    params: Optional[dict] = None,
    early_stopping_rounds: int = 20,
) -> TrainingResult:
    """Train XGBoost with walk-forward CV.

    Args:
        df: Full dataset with features, labels, and 'date' column.
        feature_cols: List of feature column names.
        label_col: Label column name (e.g. 'label_180s').
        folds: Walk-forward fold definitions.
        params: XGBoost params (defaults used if None).
        early_stopping_rounds: Early stopping patience.

    Returns:
        TrainingResult with per-fold metrics and best model.
    """
    xgb_params = {**DEFAULT_PARAMS, **(params or {})}
    fold_results = []
    dates = df["date"].to_numpy()
    X_all = np.nan_to_num(df[feature_cols].to_numpy(dtype=np.float32, copy=True))
    y_all = df[label_col].to_numpy()

    for fold in folds:
        train_mask = np.isin(dates, fold.train_dates)
        val_mask = np.isin(dates, fold.val_dates)

        X_train = X_all[train_mask]
        y_train = y_all[train_mask]
        X_val = X_all[val_mask]
        y_val = y_all[val_mask]

        # Drop NaN labels
        train_valid = ~np.isnan(y_train)
        val_valid = ~np.isnan(y_val)
        X_train, y_train = X_train[train_valid], y_train[train_valid].astype(int)
        X_val, y_val = X_val[val_valid], y_val[val_valid].astype(int)

        if len(X_train) < 100 or len(X_val) < 10:
            logger.warning(f"Fold {fold.fold_idx}: insufficient data, skipping")
            continue

        model = XGBClassifier(**xgb_params)
        fit_kwargs = {"eval_set": [(X_val, y_val)], "verbose": False}
        if "early_stopping_rounds" in inspect.signature(model.fit).parameters:
            fit_kwargs["early_stopping_rounds"] = early_stopping_rounds
        model.fit(X_train, y_train, **fit_kwargs)

        train_pred = model.predict(X_train)
        val_pred = model.predict(X_val)
        train_acc = accuracy_score(y_train, train_pred)
        val_acc = accuracy_score(y_val, val_pred)

        # Feature importance
        imp = dict(zip(feature_cols, model.feature_importances_))

        report = classification_report(
            y_val, val_pred, target_names=["down", "flat", "up"], zero_division=0
        )

        logger.info(
            f"Fold {fold.fold_idx}: train_acc={train_acc:.3f}, val_acc={val_acc:.3f}"
        )
        fold_results.append(
            FoldResult(
                fold_idx=fold.fold_idx,
                train_acc=train_acc,
                val_acc=val_acc,
                val_report=report,
                feature_importance=imp,
                model=model,
            )
        )

    if not fold_results:
        raise RuntimeError("No folds completed successfully")

    mean_val = np.mean([f.val_acc for f in fold_results])
    mean_train = np.mean([f.train_acc for f in fold_results])
    best_idx = int(np.argmax([f.val_acc for f in fold_results]))

    horizon = int(label_col.split("_")[-1].replace("s", "")) if "s" in label_col else 0

    return TrainingResult(
        fold_results=fold_results,
        best_fold_idx=best_idx,
        mean_val_acc=mean_val,
        train_val_gap=mean_train - mean_val,
        feature_columns=feature_cols,
        horizon=horizon,
    )


def resolve_training_folds(
    df: pd.DataFrame,
    label_col: str,
    candidate_folds: List[WalkForwardFold],
    fallback_folds: Optional[List[WalkForwardFold]] = None,
    min_train_rows: int = 100,
    min_val_rows: int = 10,
) -> Tuple[List[WalkForwardFold], str]:
    """Select viable folds, falling back to simpler temporal validation when needed."""

    valid_mask = df[label_col].notna()

    def _is_viable(fold: WalkForwardFold) -> bool:
        train_rows = int((df["date"].isin(fold.train_dates) & valid_mask).sum())
        val_rows = int((df["date"].isin(fold.val_dates) & valid_mask).sum())
        return train_rows >= min_train_rows and val_rows >= min_val_rows

    viable = [fold for fold in candidate_folds if _is_viable(fold)]
    if viable:
        return viable, "walk_forward"

    fallback = [fold for fold in (fallback_folds or []) if _is_viable(fold)]
    if fallback:
        return fallback, "temporal_holdout"

    raise RuntimeError(
        "No viable training folds. Increase max-total-rows / max-rows-per-symbol-day, "
        "reduce horizon, or add more dates so train/validation samples exceed the minimums."
    )


def quality_gate_failures(
    result: TrainingResult,
    fold_strategy: str,
    gate: QualityGate,
    test_accuracy: Optional[float] = None,
) -> List[str]:
    """Return quality-gate violations for a trained model."""
    failures: List[str] = []

    if gate.require_walk_forward and fold_strategy != "walk_forward":
        failures.append(f"training strategy was {fold_strategy}, expected walk_forward")

    if len(result.fold_results) < gate.min_folds:
        failures.append(
            f"only {len(result.fold_results)} fold(s), require at least {gate.min_folds}"
        )

    if result.mean_val_acc < gate.min_val_accuracy:
        failures.append(
            f"mean_val_acc={result.mean_val_acc:.3f} below minimum {gate.min_val_accuracy:.3f}"
        )

    if result.train_val_gap > gate.max_train_val_gap:
        failures.append(
            f"train_val_gap={result.train_val_gap:.3f} above maximum {gate.max_train_val_gap:.3f}"
        )

    if test_accuracy is None:
        failures.append("test accuracy unavailable")
    elif test_accuracy < gate.min_test_accuracy:
        failures.append(
            f"test_accuracy={test_accuracy:.3f} below minimum {gate.min_test_accuracy:.3f}"
        )

    return failures


def grid_search(
    df: pd.DataFrame,
    feature_cols: List[str],
    label_col: str,
    folds: List[WalkForwardFold],
    param_grid: Optional[dict] = None,
) -> Tuple[dict, List[dict]]:
    """Small grid search over key hyperparameters.

    Returns (best_params, all_results).
    """
    if param_grid is None:
        param_grid = {
            "max_depth": [2, 3],
            "n_estimators": [80, 120],
            "min_child_weight": [80, 100],
            "colsample_bytree": [0.4, 0.5],
        }

    # Generate all combinations
    from itertools import product

    keys = list(param_grid.keys())
    combos = list(product(*[param_grid[k] for k in keys]))

    results = []
    best_acc = -1
    best_params = {}

    for combo in combos:
        params = dict(zip(keys, combo))
        try:
            tr = train_walk_forward(df, feature_cols, label_col, folds, params=params)
            results.append(
                {
                    "params": params,
                    "mean_val_acc": tr.mean_val_acc,
                    "train_val_gap": tr.train_val_gap,
                }
            )
            if tr.mean_val_acc > best_acc:
                best_acc = tr.mean_val_acc
                best_params = params
            logger.info(f"Grid: {params} -> val_acc={tr.mean_val_acc:.3f}")
        except Exception as e:
            logger.warning(f"Grid: {params} failed: {e}")
            results.append({"params": params, "mean_val_acc": 0, "error": str(e)})

    return best_params, results


def save_model(result: TrainingResult, path: str) -> None:
    """Save best model and metadata."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "model": result.best_model,
            "model_family": result.model_family,
            "feature_columns": result.feature_columns,
            "horizon": result.horizon,
            "mean_val_acc": result.mean_val_acc,
            "train_val_gap": result.train_val_gap,
            "calibrator": result.calibrator,
            "threshold_selection": result.threshold_selection,
            "recommended_threshold": result.recommended_threshold,
        },
        p,
    )
    logger.info(f"Saved model to {p}")


def load_model(path: str) -> dict:
    """Load saved model artifact."""
    return joblib.load(path)


def permutation_test(
    df: pd.DataFrame,
    feature_cols: List[str],
    label_col: str,
    folds: List[WalkForwardFold],
    n_permutations: int = 5,
) -> dict:
    """Shuffle labels and retrain to verify signal is real."""
    real = train_walk_forward(df, feature_cols, label_col, folds)
    perm_accs = []
    for i in range(n_permutations):
        shuffled = df.copy()
        rng = np.random.RandomState(i)
        shuffled[label_col] = rng.permutation(shuffled[label_col].values)
        try:
            pr = train_walk_forward(shuffled, feature_cols, label_col, folds)
            perm_accs.append(pr.mean_val_acc)
        except Exception:
            perm_accs.append(1 / 3)  # random baseline for 3-class

    return {
        "real_acc": real.mean_val_acc,
        "perm_mean_acc": np.mean(perm_accs),
        "perm_std_acc": np.std(perm_accs),
        "signal_real": real.mean_val_acc > np.mean(perm_accs) + 2 * np.std(perm_accs),
    }
