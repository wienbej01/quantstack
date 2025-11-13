"""Unit tests for WalkForwardPolicyOptimizer."""

from __future__ import annotations

import numpy as np
import pandas as pd

from extensions.intraday_ml_policies.wfo_optimizer import WalkForwardPolicyOptimizer


def _synthetic_predictions(days: int = 10) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    timestamps: list[pd.Timestamp] = []
    for day in range(days):
        day_start = pd.Timestamp("2024-05-01 09:30") + pd.Timedelta(days=day)
        for bar in range(39):
            timestamps.append(day_start + pd.Timedelta(minutes=10 * bar))
    labels = rng.choice([-1, 0, 1], size=len(timestamps), p=[0.15, 0.7, 0.15])
    prob_long = rng.uniform(0, 1, size=len(timestamps))
    prob_short = rng.uniform(0, 1, size=len(timestamps))
    return pd.DataFrame(
        {
            "ts": timestamps,
            "symbol": "TEST",
            "prob_long": prob_long,
            "prob_short": prob_short,
            "label": labels,
        }
    )


def test_wfo_optimizer_runs_and_returns_metrics():
    data = _synthetic_predictions()
    config = {
        "folds": 3,
        "purge_days": 1,
        "target_trades_per_day": 4,
        "costs_bps": 10,
        "target_r_multiple": 1.5,
    }
    optimizer = WalkForwardPolicyOptimizer(config)
    result = optimizer.run(data)

    assert "folds" in result and len(result["folds"]) >= 1
    assert "aggregated" in result
    agg_metrics = result["aggregated"].get("metrics", {})
    assert set(["trades_per_day", "win_rate", "avg_r"]).issubset(agg_metrics.keys())


def test_wfo_thresholds_change_with_target_trades():
    data = _synthetic_predictions()
    aggressive_cfg = {
        "folds": 2,
        "target_trades_per_day": 6,
    }
    conservative_cfg = {
        "folds": 2,
        "target_trades_per_day": 2,
    }
    aggressive = WalkForwardPolicyOptimizer(aggressive_cfg).run(data)
    conservative = WalkForwardPolicyOptimizer(conservative_cfg).run(data)

    agg_thresh_aggressive = aggressive["aggregated"]["thresholds"]
    agg_thresh_conservative = conservative["aggregated"]["thresholds"]

    assert agg_thresh_aggressive["prob_long"] <= agg_thresh_conservative["prob_long"]
    assert agg_thresh_aggressive["prob_short"] <= agg_thresh_conservative["prob_short"]
