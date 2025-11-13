from __future__ import annotations

import pandas as pd

from extensions.intraday_ml.eval.eval_trading_performance import (
    SelectionPolicy,
    evaluate_trading_performance,
)


def _sample_bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["AAPL", "AAPL", "MSFT", "MSFT"],
            "ts": pd.to_datetime(
                [
                    "2024-01-02 09:35:00",
                    "2024-01-02 09:36:00",
                    "2024-01-02 09:35:00",
                    "2024-01-02 09:36:00",
                ]
            ),
            "close": [100.0, 101.0, 50.0, 49.0],
        }
    )


def _sample_predictions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["AAPL", "MSFT"],
            "ts": pd.to_datetime(
                [
                    "2024-01-02 09:35:00",
                    "2024-01-02 09:35:00",
                ]
            ),
            "prob_long": [0.7, 0.3],
            "prob_short": [0.2, 0.6],
            "prob_neutral": [0.1, 0.1],
        }
    )


def test_threshold_policy_evaluation(tmp_path) -> None:
    policies = [
        SelectionPolicy(name="threshold", kind="threshold", prob_threshold=0.55),
    ]
    results = evaluate_trading_performance(
        bars=_sample_bars(),
        predictions=_sample_predictions(),
        policies=policies,
        horizon_minutes=1,
        transaction_cost_bps=0.0,
        output_dir=tmp_path,
    )

    result = results["threshold"]
    assert len(result.trades) == 2
    assert result.metrics["total_trades"] == 2
    assert result.metrics["win_rate"] == 1.0
    # AAPL long: +1%, MSFT short: +2%
    assert abs(result.metrics["avg_return"] - 0.015) < 1e-9
    assert not result.daily_pnl.empty


def test_topk_policy_selects_highest_score() -> None:
    policies = [
        SelectionPolicy(name="topk", kind="topk", top_k=1, prob_threshold=0.5),
    ]
    results = evaluate_trading_performance(
        bars=_sample_bars(),
        predictions=_sample_predictions(),
        policies=policies,
        horizon_minutes=1,
        transaction_cost_bps=0.0,
    )

    result = results["topk"]
    assert len(result.trades) == 1
    assert set(result.trades["symbol"]) == {"AAPL"}
    assert "rank_within_day" in result.trades.columns
