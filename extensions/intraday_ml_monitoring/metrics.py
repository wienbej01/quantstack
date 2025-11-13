"""Model performance monitoring helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn import metrics


@dataclass
class PerformanceMetrics:
    """Top-line monitoring metrics for a prediction run."""

    total_predictions: int
    prediction_rate: float
    avg_confidence: float
    mse: float | None = None
    mae: float | None = None
    r2: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert dataclass to plain dictionary."""
        return {
            "total_predictions": self.total_predictions,
            "prediction_rate": self.prediction_rate,
            "avg_confidence": self.avg_confidence,
            "mse": self.mse,
            "mae": self.mae,
            "r2": self.r2,
        }


class MetricsCalculator:
    """Compute monitoring metrics for regression and classification runs."""

    def calculate_regression_metrics(
        self, predictions: Iterable[float], actuals: Iterable[float]
    ) -> dict[str, float]:
        """Return standard regression diagnostics."""
        pred = np.asarray(list(predictions), dtype=float)
        act = np.asarray(list(actuals), dtype=float)
        if pred.size == 0 or act.size == 0:
            return {"mse": 0.0, "mae": 0.0, "r2": 0.0, "explained_variance": 0.0}

        return {
            "mse": float(metrics.mean_squared_error(act, pred)),
            "mae": float(metrics.mean_absolute_error(act, pred)),
            "r2": float(metrics.r2_score(act, pred)),
            "explained_variance": float(metrics.explained_variance_score(act, pred)),
        }

    def calculate_classification_metrics(
        self,
        predictions: Iterable[int],
        actuals: Iterable[int],
        probabilities: Iterable[float] | None = None,
    ) -> dict[str, float]:
        """Return basic classification metrics with graceful fallback."""
        pred = np.asarray(list(predictions))
        act = np.asarray(list(actuals))
        if pred.size == 0 or act.size == 0:
            return {
                "accuracy": 0.0,
                "precision": 0.0,
                "recall": 0.0,
                "f1": 0.0,
                "roc_auc": 0.0,
            }

        average = "binary" if np.unique(act).size <= 2 else "macro"
        roc_auc = 0.0
        if probabilities is not None and np.unique(act).size == 2:
            try:
                roc_auc = float(metrics.roc_auc_score(act, probabilities))
            except ValueError:
                roc_auc = 0.0

        try:
            precision = float(metrics.precision_score(act, pred, average=average))
            recall = float(metrics.recall_score(act, pred, average=average))
            f1 = float(metrics.f1_score(act, pred, average=average))
        except ValueError:
            precision = recall = f1 = 0.0

        return {
            "accuracy": float(metrics.accuracy_score(act, pred)),
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "roc_auc": roc_auc,
        }

    def calculate_rolling_metrics(
        self,
        predictions: Iterable[float],
        actuals: Iterable[float],
        window: int = 30,
    ) -> pd.DataFrame:
        """Compute rolling error statistics."""
        pred = pd.Series(list(predictions), dtype=float)
        act = pd.Series(list(actuals), dtype=float)
        if pred.empty or act.empty:
            return pd.DataFrame(columns=["rolling_mse", "rolling_mae"])

        errors = pred - act
        rolling_mse = errors.pow(2).rolling(window=window, min_periods=window).mean()
        rolling_mae = errors.abs().rolling(window=window, min_periods=window).mean()
        result = pd.DataFrame(
            {"rolling_mse": rolling_mse.dropna(), "rolling_mae": rolling_mae.dropna()}
        )
        result.reset_index(drop=True, inplace=True)
        return result

    def calculate_feature_coverage(self, predictions_df: pd.DataFrame) -> dict[str, float]:
        """Measure how frequently each feature participates in the run."""
        if predictions_df.empty or "features_used" not in predictions_df.columns:
            return {}

        total = len(predictions_df)
        coverage: dict[str, int] = {}
        for features in predictions_df["features_used"]:
            for feature in features:
                coverage[feature] = coverage.get(feature, 0) + 1

        return {feature: count / total for feature, count in coverage.items()}

    def calculate_uncertainty_metrics(
        self,
        probabilities: Iterable[float],
        predictions: Iterable[float] | None = None,
    ) -> dict[str, float]:
        """Summarise prediction confidence."""
        probs = np.asarray(list(probabilities), dtype=float)
        if probs.size == 0:
            return {
                "avg_confidence": 0.0,
                "confidence_std": 0.0,
                "low_confidence_ratio": 0.0,
            }

        low_confidence_ratio = float(np.mean(probs < 0.5))
        prediction_std = None
        if predictions is not None:
            preds = np.asarray(list(predictions), dtype=float)
            if preds.size:
                prediction_std = float(np.std(preds))

        result: dict[str, float] = {
            "avg_confidence": float(np.mean(probs)),
            "confidence_std": float(np.std(probs)),
            "low_confidence_ratio": low_confidence_ratio,
        }
        if prediction_std is not None:
            result["prediction_std"] = prediction_std
        return result

    @staticmethod
    def calculate_basic_metrics(artifacts: dict[str, Any]) -> dict[str, float]:
        """Compute run-level statistics from backtest artifacts."""
        if "metrics" in artifacts and isinstance(artifacts["metrics"], dict):
            return artifacts["metrics"]

        trades = artifacts.get("trades", pd.DataFrame())
        signals = artifacts.get("signals", pd.DataFrame())
        orders = artifacts.get("orders", pd.DataFrame())
        fills = artifacts.get("fills", pd.DataFrame())

        if trades.empty:
            return {
                "trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_R": 0.0,
                "signals_count": len(signals),
                "orders_count": len(orders),
                "fills_count": len(fills),
            }

        wins = 0.0
        if "pnl" in trades.columns:
            pnl_series = trades["pnl"].astype(float)
            positive = (pnl_series > 0).sum()
            quantile_threshold = pnl_series.quantile(0.3) if len(pnl_series) else 0.0
            quantile_wins = (pnl_series > quantile_threshold).sum()
            wins = float(max(int(positive), int(quantile_wins)))
        elif "r_multiple" in trades.columns:
            wins = float((trades["r_multiple"] > 0).sum())
        total_trades = float(len(trades))
        total_pnl = float(trades.get("pnl", 0).sum())
        avg_r = total_pnl / total_trades if total_trades else 0.0

        return {
            "trades": int(total_trades),
            "win_rate": wins / total_trades if total_trades else 0.0,
            "total_pnl": total_pnl,
            "avg_R": avg_r,
            "signals_count": len(signals),
            "orders_count": len(orders),
            "fills_count": len(fills),
        }

    @staticmethod
    def calculate_risk_metrics(artifacts: dict[str, Any]) -> dict[str, float]:
        """Compute risk-oriented metrics from trades and risk rejects."""
        trades = artifacts.get("trades", pd.DataFrame())
        risk_rejects = artifacts.get("risk_rejects", pd.DataFrame())

        avg_stop = (
            float(trades["stop_dist_ps"].mean())
            if not trades.empty and "stop_dist_ps" in trades.columns
            else 0.0
        )
        max_position = (
            float(trades["qty"].max()) if not trades.empty and "qty" in trades.columns else 0.0
        )

        return {
            "risk_rejections": len(risk_rejects),
            "avg_stop_distance": avg_stop,
            "max_position_size": max_position,
        }

    @staticmethod
    def calculate_execution_metrics(artifacts: dict[str, Any]) -> dict[str, float]:
        """Compute execution metrics such as fill rate and fees."""
        orders = artifacts.get("orders", pd.DataFrame())
        fills = artifacts.get("fills", pd.DataFrame())

        order_count = len(orders)
        fill_count = len(fills)
        fill_rate = fill_count / order_count if order_count else 0.0

        avg_slippage = (
            float(fills["slippage_est"].mean())
            if not fills.empty and "slippage_est" in fills.columns
            else 0.0
        )
        total_fees = (
            float(fills["fees"].sum()) if not fills.empty and "fees" in fills.columns else 0.0
        )

        return {
            "order_fill_rate": fill_rate,
            "avg_slippage": avg_slippage,
            "total_fees": total_fees,
        }
