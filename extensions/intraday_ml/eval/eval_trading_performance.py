"""Trading performance evaluation for intraday ML Sprint 1."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

import numpy as np
import pandas as pd

from .prediction_loader import ProbabilityColumnMap, score_predictions


@dataclass(frozen=True, slots=True)
class SelectionPolicy:
    """Policy definition for selecting candidate trades."""

    name: str
    kind: Literal["threshold", "topk"]
    prob_threshold: float | None = None
    min_edge: float = 0.0
    min_score: float = 0.0
    top_k: int | None = None
    score_column: str = "trade_score"


@dataclass(slots=True)
class TradingEvaluationResult:
    """Container for per-policy evaluation outputs."""

    trades: pd.DataFrame
    daily_pnl: pd.DataFrame
    metrics: dict[str, Any]


def evaluate_trading_performance(
    *,
    bars: pd.DataFrame,
    predictions: pd.DataFrame,
    policies: Sequence[SelectionPolicy],
    horizon_minutes: int,
    transaction_cost_bps: float = 10.0,
    probability_columns: ProbabilityColumnMap | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, TradingEvaluationResult]:
    """Evaluate predictions using PnL-focused selection policies."""
    if not policies:
        raise ValueError("At least one selection policy must be provided.")

    output_path = Path(output_dir) if output_dir else None
    if output_path:
        output_path.mkdir(parents=True, exist_ok=True)

    scored = score_predictions(predictions, probability_columns)
    returns_frame = _compute_realized_returns(bars, horizon_minutes)
    merged = _merge_predictions_returns(scored, returns_frame)
    if merged.empty:
        return {
            policy.name: TradingEvaluationResult(
                trades=pd.DataFrame(),
                daily_pnl=pd.DataFrame(columns=["trade_date", "daily_pnl"]),
                metrics=_empty_metrics(),
            )
            for policy in policies
        }

    per_policy_results: dict[str, TradingEvaluationResult] = {}
    transaction_cost = float(transaction_cost_bps) / 10_000.0

    for policy in policies:
        trades = _select_trades(merged, policy)
        if trades.empty:
            result = TradingEvaluationResult(
                trades=pd.DataFrame(),
                daily_pnl=pd.DataFrame(columns=["trade_date", "daily_pnl"]),
                metrics=_empty_metrics(),
            )
        else:
            evaluated_trades = _compute_trade_pnl(trades, transaction_cost)
            daily = (
                evaluated_trades.groupby("trade_date", as_index=False)["net_return"]
                .sum()
                .rename(columns={"net_return": "daily_pnl"})
            )
            metrics = _compute_metrics(evaluated_trades, daily)
            result = TradingEvaluationResult(
                trades=evaluated_trades,
                daily_pnl=daily,
                metrics=metrics,
            )
            if output_path:
                _write_policy_outputs(result, policy, output_path)

        per_policy_results[policy.name] = result

    return per_policy_results


def _compute_realized_returns(
    bars: pd.DataFrame,
    horizon_minutes: int,
    price_column: str = "close",
) -> pd.DataFrame:
    required = {"symbol", "ts", price_column}
    missing = required - set(bars.columns)
    if missing:
        raise ValueError(f"Bars DataFrame missing required columns: {sorted(missing)}")

    frame = bars.copy()
    frame["ts"] = pd.to_datetime(frame["ts"], errors="coerce")
    if frame["ts"].isna().any():
        raise ValueError("Bars DataFrame contains malformed timestamps.")

    frame = frame.sort_values(["symbol", "ts"]).reset_index(drop=True)
    grouped = frame.groupby("symbol", group_keys=False)
    future_prices = grouped[price_column].shift(-horizon_minutes)
    start_price = frame[price_column].astype(float)

    returns = (future_prices - start_price) / start_price
    frame["realized_return"] = returns
    frame = frame.dropna(subset=["realized_return"])

    return frame[["symbol", "ts", "realized_return"]]


def _merge_predictions_returns(
    predictions: pd.DataFrame,
    returns_frame: pd.DataFrame,
) -> pd.DataFrame:
    if predictions.empty or returns_frame.empty:
        return pd.DataFrame()

    preds = predictions.copy()
    preds["ts"] = pd.to_datetime(preds["ts"], errors="coerce")
    if preds["ts"].isna().any():
        preds = preds.dropna(subset=["ts"])

    merged = preds.merge(
        returns_frame,
        on=["symbol", "ts"],
        how="inner",
        validate="one_to_one",
    )
    return merged.dropna(subset=["realized_return"])


def _select_trades(df: pd.DataFrame, policy: SelectionPolicy) -> pd.DataFrame:
    filtered = df.copy()
    if policy.prob_threshold is not None:
        filtered = filtered[filtered["trade_prob"] >= policy.prob_threshold]
    if policy.min_edge > 0:
        filtered = filtered[filtered["edge_margin"] >= policy.min_edge]
    if policy.min_score > 0:
        filtered = filtered[filtered["trade_score"] >= policy.min_score]

    if filtered.empty:
        return filtered

    if policy.kind == "threshold":
        filtered["selection_policy"] = policy.name
        return filtered

    if policy.kind != "topk":
        raise ValueError(f"Unsupported policy kind: {policy.kind}")
    if not policy.top_k or policy.top_k <= 0:
        raise ValueError("top_k must be positive for top-k policies.")
    if policy.score_column not in filtered.columns:
        raise ValueError(f"Score column '{policy.score_column}' not present.")

    filtered = filtered.copy()
    filtered["trade_date"] = filtered["ts"].dt.date.astype(str)
    filtered = filtered.sort_values(
        ["trade_date", policy.score_column],
        ascending=[True, False],
    )
    ranked = filtered.groupby("trade_date", group_keys=False).head(policy.top_k).copy()
    ranked["selection_policy"] = policy.name
    ranked["rank_within_day"] = (
        ranked.groupby("trade_date")[policy.score_column]
        .rank(method="first", ascending=False)
        .astype(int)
    )
    return ranked


def _compute_trade_pnl(trades: pd.DataFrame, transaction_cost: float) -> pd.DataFrame:
    evaluated = trades.copy()
    evaluated["trade_date"] = evaluated["ts"].dt.date.astype(str)
    evaluated["gross_return"] = evaluated["trade_direction"] * evaluated["realized_return"]
    evaluated["transaction_cost"] = transaction_cost
    evaluated["net_return"] = evaluated["gross_return"] - transaction_cost
    return evaluated


def _compute_metrics(trades: pd.DataFrame, daily: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return _empty_metrics()

    total_trades = len(trades)
    win_rate = float((trades["net_return"] > 0).mean()) if total_trades else 0.0
    avg_return = float(trades["net_return"].mean()) if total_trades else 0.0
    median_return = float(trades["net_return"].median()) if total_trades else 0.0

    daily_returns = daily["daily_pnl"].to_numpy(dtype=float)
    sharpe = _sharpe_ratio(daily_returns)
    sortino = _sortino_ratio(daily_returns)
    max_dd = _max_drawdown(daily_returns)

    return {
        "total_trades": total_trades,
        "win_rate": win_rate,
        "avg_return": avg_return,
        "median_return": median_return,
        "avg_daily_pnl": float(daily_returns.mean()) if len(daily_returns) else 0.0,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
    }


def _empty_metrics() -> dict[str, Any]:
    return {
        "total_trades": 0,
        "win_rate": 0.0,
        "avg_return": 0.0,
        "median_return": 0.0,
        "avg_daily_pnl": 0.0,
        "sharpe": 0.0,
        "sortino": 0.0,
        "max_drawdown": 0.0,
    }


def _sharpe_ratio(returns: np.ndarray) -> float:
    if returns.size == 0:
        return 0.0
    std = returns.std(ddof=0)
    if std == 0:
        return 0.0
    return float(returns.mean() / std * np.sqrt(252))


def _sortino_ratio(returns: np.ndarray) -> float:
    if returns.size == 0:
        return 0.0
    downside = returns[returns < 0]
    if downside.size == 0:
        return 0.0
    downside_std = downside.std(ddof=0)
    if downside_std == 0:
        return 0.0
    return float(returns.mean() / downside_std * np.sqrt(252))


def _max_drawdown(returns: np.ndarray) -> float:
    if returns.size == 0:
        return 0.0
    equity_curve = np.cumsum(returns)
    running_max = np.maximum.accumulate(equity_curve)
    drawdowns = equity_curve - running_max
    return float(drawdowns.min())


def _write_policy_outputs(
    result: TradingEvaluationResult,
    policy: SelectionPolicy,
    output_dir: Path,
) -> None:
    trades_path = output_dir / f"{policy.name}_trades.csv"
    result.trades.to_csv(trades_path, index=False)

    daily_path = output_dir / f"{policy.name}_daily_pnl.csv"
    result.daily_pnl.to_csv(daily_path, index=False)

    metrics_path = output_dir / f"{policy.name}_metrics.json"
    with open(metrics_path, "w") as handle:
        json.dump(result.metrics, handle, indent=2)
