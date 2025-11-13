"""Walk-forward policy optimizer with simple cost-aware metrics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class PolicyThresholds:
    """Probability thresholds for long/short decisions."""

    prob_long: float
    prob_short: float
    min_gap: float


class WalkForwardPolicyOptimizer:
    """Tune policy thresholds via purged walk-forward evaluation."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.n_folds = int(config.get("folds", 3))
        self.purge_days = int(config.get("purge_days", 2))
        self.target_trades_per_day = float(config.get("target_trades_per_day", 4.0))
        self.min_gap = float(config.get("min_directional_gap", 0.05))
        self.costs_bps = float(config.get("costs_bps", 12.5))
        self.target_r_multiple = float(config.get("target_r_multiple", 1.5))

    def run(self, data: pd.DataFrame) -> dict[str, Any]:
        if data.empty:
            raise ValueError("Walk-forward optimizer requires non-empty dataset.")

        required = {"ts", "prob_long", "prob_short", "label"}
        missing = required - set(data.columns)
        if missing:
            raise ValueError(f"Missing required columns for WFO: {', '.join(sorted(missing))}")

        df = data.copy()
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
        df = df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)

        splits = self._create_splits(df)
        fold_results: list[dict[str, Any]] = []

        for fold_idx, (train_df, val_df) in enumerate(splits, start=1):
            thresholds = self._derive_thresholds(train_df)
            metrics = self._evaluate_fold(val_df, thresholds)
            fold_results.append(
                {
                    "fold": fold_idx,
                    "thresholds": thresholds.__dict__,
                    "metrics": metrics,
                }
            )

        aggregated = self._aggregate_results(fold_results)
        return {"folds": fold_results, "aggregated": aggregated}

    def _create_splits(self, df: pd.DataFrame) -> list[tuple[pd.DataFrame, pd.DataFrame]]:
        unique_dates = df["ts"].dt.floor("D").drop_duplicates().sort_values().to_list()
        if len(unique_dates) < self.n_folds + 1:
            raise ValueError("Not enough unique dates for requested folds.")

        fold_size = len(unique_dates) // self.n_folds
        splits: list[tuple[pd.DataFrame, pd.DataFrame]] = []

        for fold in range(self.n_folds):
            val_start = fold * fold_size
            val_end = (fold + 1) * fold_size if fold < self.n_folds - 1 else len(unique_dates)

            val_dates = unique_dates[val_start:val_end]
            if not val_dates:
                continue
            val_mask = df["ts"].dt.floor("D").isin(val_dates)
            train_mask = df["ts"].dt.floor("D") < val_dates[0]

            if self.purge_days > 0:
                purge_start = val_dates[0] - pd.Timedelta(days=self.purge_days)
                train_mask &= df["ts"].dt.floor("D") < purge_start

            train_df = df.loc[train_mask].copy()
            val_df = df.loc[val_mask].copy()
            if train_df.empty or val_df.empty:
                continue
            splits.append((train_df, val_df))

        if not splits:
            raise ValueError("Unable to create walk-forward splits with provided parameters.")

        return splits

    def _derive_thresholds(self, train_df: pd.DataFrame) -> PolicyThresholds:
        days = max(1, train_df["ts"].dt.floor("D").nunique())
        target_trades = max(1, int(self.target_trades_per_day * days))

        def quantile_threshold(probs: np.ndarray) -> float:
            if len(probs) <= target_trades:
                return float(np.min(probs)) if len(probs) else 1.0
            sorted_probs = np.sort(probs)
            idx = max(0, len(sorted_probs) - target_trades)
            return float(sorted_probs[idx])

        prob_long = quantile_threshold(train_df["prob_long"].to_numpy())
        prob_short = quantile_threshold(train_df["prob_short"].to_numpy())

        return PolicyThresholds(
            prob_long=min(0.999, max(0.0, prob_long)),
            prob_short=min(0.999, max(0.0, prob_short)),
            min_gap=self.min_gap,
        )

    def _evaluate_fold(self, val_df: pd.DataFrame, thresholds: PolicyThresholds) -> dict[str, Any]:
        signals = val_df.copy()
        signals["direction"] = 0
        long_mask = signals["prob_long"] >= thresholds.prob_long
        short_mask = signals["prob_short"] >= thresholds.prob_short
        gap = np.abs(signals["prob_long"] - signals["prob_short"])
        long_mask &= gap >= thresholds.min_gap
        short_mask &= gap >= thresholds.min_gap

        signals.loc[long_mask, "direction"] = 1
        signals.loc[short_mask, "direction"] = -1

        trades = signals[signals["direction"] != 0].copy()
        days = max(1, signals["ts"].dt.floor("D").nunique())
        trades_per_day = len(trades) / days if days else 0.0

        if trades.empty:
            return {
                "trades": 0,
                "trades_per_day": 0.0,
                "win_rate": 0.0,
                "avg_r": -self._cost_per_trade(),
                "sharpe_proxy": 0.0,
            }

        wins = trades["direction"] == trades["label"]
        win_rate = float(np.mean(wins)) if len(trades) else 0.0
        returns = self._compute_trade_returns(wins)
        avg_r = float(np.mean(returns)) if len(returns) else 0.0
        sharpe = float(
            avg_r / np.std(returns)
        ) if len(returns) > 1 and np.std(returns) > 1e-9 else float("nan")

        return {
            "trades": int(len(trades)),
            "trades_per_day": trades_per_day,
            "win_rate": win_rate,
            "avg_r": avg_r,
            "sharpe_proxy": sharpe,
        }

    def _compute_trade_returns(self, wins: pd.Series) -> np.ndarray:
        """Return per-trade R multiples after costs."""

        cost = self._cost_per_trade()
        r_win = self.target_r_multiple - cost
        r_loss = -(1.0 + cost)
        return np.where(wins.to_numpy(dtype=bool), r_win, r_loss)

    def _cost_per_trade(self) -> float:
        return float(self.costs_bps) / 10000.0

    def _aggregate_results(self, folds: list[dict[str, Any]]) -> dict[str, Any]:
        if not folds:
            return {}

        avg_metrics = {
            key: float(np.nanmean([fold["metrics"].get(key, np.nan) for fold in folds]))
            for key in ["trades_per_day", "win_rate", "avg_r", "sharpe_proxy"]
        }
        avg_thresholds = {
            key: float(np.mean([fold["thresholds"].get(key, np.nan) for fold in folds]))
            for key in ["prob_long", "prob_short", "min_gap"]
        }
        return {"metrics": avg_metrics, "thresholds": avg_thresholds}
