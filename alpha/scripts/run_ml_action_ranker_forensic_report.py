#!/usr/bin/env python3
"""Build a forensic report for the best action-ranker replay configuration."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import joblib
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_ml_action_ranker_budget_backtest import (
    RankedAction,
    ScheduledActionSignal,
    WeakContextGate,
    WindowSpec,
    _base_config,
    _is_rejected_by_weak_context_gate,
    _load_daily_payloads,
    _load_or_build_ranked_actions,
    _parse_windows,
    _select_topk,
    _to_signal_event,
)
from src.backtest import AlphaBacktestEngine
from src.models.action_ranker import (
    ACTION_QUALITY_BASE_COLUMNS,
    ACTION_QUALITY_PRICE_COLUMNS,
)

# RankedAction caches were written by a script entry point, so joblib may look for the class on __main__.
setattr(sys.modules["__main__"], "RankedAction", RankedAction)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

_QUALITY_CONTEXT_COLUMNS = tuple(
    column
    for column in (
        *ACTION_QUALITY_BASE_COLUMNS,
        *ACTION_QUALITY_PRICE_COLUMNS,
        "session_bucket",
    )
    if column != "rank_score"
)


def _source_type_from_features(features: dict[str, Any]) -> str:
    if float(features.get("source_is_features", 0.0)) > 0.5:
        return "features"
    if float(features.get("source_is_raw", 0.0)) > 0.5:
        return "raw"
    return "unknown"


def _load_best_config(matrix_dir: Path) -> tuple[str, float, int, int]:
    summary_path = matrix_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing matrix summary: {summary_path}")
    summary = json.loads(summary_path.read_text())
    best = summary["best_config"]
    return (
        str(summary["artifact_path"]),
        float(summary["min_score"]),
        int(best["top_k"]),
        int(best["max_longs_per_day"]),
    )


def _load_matrix_summary(matrix_dir: Path) -> dict[str, Any]:
    summary_path = matrix_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing matrix summary: {summary_path}")
    return json.loads(summary_path.read_text())


def _explicit_or_matrix_config(
    *,
    matrix_dir: Path,
    artifact_path: str | None,
    min_score: float | None,
    top_k: int | None,
    max_longs_per_day: int | None,
) -> tuple[str, float, int, int]:
    if (
        artifact_path is not None
        and min_score is not None
        and top_k is not None
        and max_longs_per_day is not None
    ):
        return artifact_path, float(min_score), int(top_k), int(max_longs_per_day)
    return _load_best_config(matrix_dir)


def _matrix_or_explicit_gate(
    *,
    matrix_dir: Path,
    max_pressure_k: float | None,
    max_spread: float | None,
    max_depth_imb_k: float | None,
) -> WeakContextGate | None:
    values = (max_pressure_k, max_spread, max_depth_imb_k)
    if any(value is not None for value in values):
        if not all(value is not None for value in values):
            raise ValueError(
                "weak-context gate requires all of --weak-context-max-pressure-k, "
                "--weak-context-max-spread, and --weak-context-max-depth-imb-k"
            )
        return WeakContextGate(
            max_pressure_k=float(max_pressure_k),
            max_spread=float(max_spread),
            max_depth_imb_k=float(max_depth_imb_k),
        )

    summary = _load_matrix_summary(matrix_dir)
    gate = summary.get("weak_context_gate")
    if not gate:
        return None
    return WeakContextGate(
        max_pressure_k=float(gate["max_pressure_k"]),
        max_spread=float(gate["max_spread"]),
        max_depth_imb_k=float(gate["max_depth_imb_k"]),
    )


def _match_action_to_trade(trade: Any, selected: list[Any]) -> dict[str, Any]:
    entry_time = pd.Timestamp(trade.entry_time)
    for action in selected:
        if (
            str(action.symbol) == str(trade.symbol)
            and pd.Timestamp(action.timestamp) == entry_time
        ):
            return {
                "rank_score": float(action.score),
                "scheduled_hold_minutes": int(action.hold_minutes),
            }
    return {"rank_score": float("nan"), "scheduled_hold_minutes": float("nan")}


def _entry_context(
    *,
    payload: dict[str, Any],
    trade: Any,
    config: dict[str, Any],
) -> dict[str, Any]:
    entry_ts = pd.Timestamp(trade.entry_time)
    symbol = str(trade.symbol)
    bars_df = payload["bars"]
    l2_df = payload["l2"]

    bar_match = bars_df[
        (bars_df["symbol"] == symbol) & (pd.to_datetime(bars_df["ts"]) == entry_ts)
    ]
    if bar_match.empty:
        raise RuntimeError(f"Could not find entry bar for {symbol} at {entry_ts}")

    symbol_l2 = None
    if l2_df is not None and not l2_df.empty:
        symbol_l2 = l2_df[l2_df["symbol"] == symbol].reset_index(drop=True)

    engine = AlphaBacktestEngine(config)
    bar_history = bars_df[
        (bars_df["symbol"] == symbol) & (pd.to_datetime(bars_df["ts"]) <= entry_ts)
    ].sort_values("ts")
    bar_data = engine._prepare_bar_data(
        bar_match.iloc[0], symbol_l2, entry_ts, bar_history=bar_history
    )
    features = bar_data.features

    return {
        "source_type": _source_type_from_features(features),
        "spread_std_30s": features.get("spread_std_30s"),
        "spread_std_60s": features.get("spread_std_60s"),
        "micro_off_std_30s": features.get("micro_off_std_30s"),
        "micro_off_std_60s": features.get("micro_off_std_60s"),
        **{column: features.get(column) for column in _QUALITY_CONTEXT_COLUMNS},
    }


def _compare_cohorts(context_df: pd.DataFrame, left: str, right: str) -> pd.DataFrame:
    compare_cols = [
        "spread",
        "spread_std_30s",
        "spread_std_60s",
        "micro_off",
        "micro_off_std_30s",
        "micro_off_std_60s",
        "depth_imb_k",
        "depth_imb_k_mean_10s",
        "depth_imb_k_mean_60s",
        "pressure_k",
        "session_bucket",
        *ACTION_QUALITY_PRICE_COLUMNS,
    ]
    rows: list[dict[str, Any]] = []
    for column in compare_cols:
        if column not in context_df.columns:
            continue
        left_values = pd.to_numeric(
            context_df.loc[context_df["cohort"] == left, column], errors="coerce"
        )
        right_values = pd.to_numeric(
            context_df.loc[context_df["cohort"] == right, column], errors="coerce"
        )
        rows.append(
            {
                "feature": column,
                f"{left}_mean": (
                    float(left_values.mean()) if not left_values.empty else float("nan")
                ),
                f"{right}_mean": (
                    float(right_values.mean())
                    if not right_values.empty
                    else float("nan")
                ),
                "mean_diff": (
                    float(right_values.mean() - left_values.mean())
                    if not left_values.empty and not right_values.empty
                    else float("nan")
                ),
                f"{left}_count": int(left_values.notna().sum()),
                f"{right}_count": int(right_values.notna().sum()),
            }
        )
    return pd.DataFrame(rows).sort_values(
        "mean_diff", key=lambda s: s.abs(), ascending=False
    )


def run_forensic_report(
    *,
    matrix_dir: Path,
    output_dir: Path,
    windows: list[WindowSpec],
    bar_source: str = "polygon",
    artifact_path: str | None = None,
    min_score: float | None = None,
    top_k: int | None = None,
    max_longs_per_day: int | None = None,
    weak_context_gate: WeakContextGate | None = None,
    cache_dir: Path | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    artifact_path, min_score, top_k, max_longs = _explicit_or_matrix_config(
        matrix_dir=matrix_dir,
        artifact_path=artifact_path,
        min_score=min_score,
        top_k=top_k,
        max_longs_per_day=max_longs_per_day,
    )
    artifact = joblib.load(artifact_path)
    config = _base_config(bar_source)
    payloads_by_window = {
        window.label: _load_daily_payloads(window.start, window.end, config)
        for window in windows
    }

    selected_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    context_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []

    for window in windows:
        for payload in payloads_by_window[window.label]:
            ranked = _load_or_build_ranked_actions(
                payload=payload,
                window_label=window.label,
                config=config,
                artifact=artifact,
                output_dir=matrix_dir,
                score_cache=True,
                cache_dir=cache_dir,
            )
            for action in ranked:
                if action.score < min_score:
                    continue
                if not _is_rejected_by_weak_context_gate(action, weak_context_gate):
                    continue
                rejected_rows.append(
                    {
                        "window": window.label,
                        "date": payload["date"],
                        "symbol": action.symbol,
                        "timestamp": action.timestamp,
                        "side": action.side.value,
                        "hold_minutes": action.hold_minutes,
                        "score": action.score,
                        "pressure_k": (action.context or {}).get("pressure_k"),
                        "spread": (action.context or {}).get("spread"),
                        "depth_imb_k": (action.context or {}).get("depth_imb_k"),
                    }
                )
            selected = _select_topk(
                ranked,
                top_k=top_k,
                max_longs_per_day=max_longs,
                min_score=min_score,
                weak_context_gate=weak_context_gate,
            )
            for action in selected:
                selected_rows.append(
                    {
                        "window": window.label,
                        "date": payload["date"],
                        "symbol": action.symbol,
                        "timestamp": action.timestamp,
                        "side": action.side.value,
                        "hold_minutes": action.hold_minutes,
                        "score": action.score,
                    }
                )
            if not selected:
                continue

            engine = AlphaBacktestEngine(config)
            signal = ScheduledActionSignal(
                config, [_to_signal_event(item) for item in selected]
            )
            result = engine.run(payload["bars"], l2_df=payload["l2"], signals=[signal])
            for trade in result.trades:
                action_meta = _match_action_to_trade(trade, selected)
                row = {
                    "window": window.label,
                    "date": payload["date"],
                    "symbol": trade.symbol,
                    "side": trade.side.value,
                    "entry_time": trade.entry_time,
                    "exit_time": trade.exit_time,
                    "entry_price": trade.entry_price,
                    "exit_price": trade.exit_price,
                    "quantity": trade.quantity,
                    "pnl": trade.pnl,
                    "pnl_pct": trade.pnl_pct,
                    "hold_minutes": trade.hold_minutes,
                    "exit_reason": trade.exit_reason,
                    "is_winner": bool(trade.pnl > 0),
                    **action_meta,
                }
                trade_rows.append(row)
                context_rows.append(
                    {
                        **row,
                        **_entry_context(payload=payload, trade=trade, config=config),
                    }
                )

    selected_df = pd.DataFrame(selected_rows)
    trades_df = pd.DataFrame(trade_rows)
    context_df = pd.DataFrame(context_rows)
    rejected_df = pd.DataFrame(rejected_rows)

    selected_df.to_csv(output_dir / "selected_actions.csv", index=False)
    trades_df.to_csv(output_dir / "best_config_trades.csv", index=False)
    context_df.to_csv(output_dir / "entry_contexts.csv", index=False)
    rejected_df.to_csv(output_dir / "gate_rejections.csv", index=False)

    cohort_df = context_df.copy()
    cohort_df["cohort"] = "other"
    cohort_df.loc[
        (cohort_df["window"] == "w1") & (~cohort_df["is_winner"]), "cohort"
    ] = "w1_losers"
    cohort_df.loc[
        (cohort_df["window"] == "w2") & (cohort_df["is_winner"]), "cohort"
    ] = "w2_winners"
    cohort_df.to_csv(output_dir / "trade_contexts_with_cohorts.csv", index=False)

    comparison_df = _compare_cohorts(cohort_df, "w1_losers", "w2_winners")
    comparison_df.to_csv(output_dir / "feature_comparison.csv", index=False)

    source_counts = (
        cohort_df.groupby(["cohort", "source_type"])
        .size()
        .rename("count")
        .reset_index()
        if not cohort_df.empty
        else pd.DataFrame(columns=["cohort", "source_type", "count"])
    )
    source_counts.to_csv(output_dir / "source_type_comparison.csv", index=False)

    symbol_concentration = (
        trades_df.groupby("symbol")
        .agg(trades=("symbol", "size"), total_pnl=("pnl", "sum"))
        .sort_values(["total_pnl", "trades"], ascending=[False, False])
        .reset_index()
        if not trades_df.empty
        else pd.DataFrame(columns=["symbol", "trades", "total_pnl"])
    )
    symbol_concentration.to_csv(output_dir / "symbol_concentration.csv", index=False)

    day_concentration = (
        trades_df.groupby(["window", "date"])
        .agg(trades=("date", "size"), total_pnl=("pnl", "sum"))
        .sort_values(["date", "total_pnl"], ascending=[True, False])
        .reset_index()
        if not trades_df.empty
        else pd.DataFrame(columns=["window", "date", "trades", "total_pnl"])
    )
    day_concentration.to_csv(output_dir / "day_concentration.csv", index=False)

    session_concentration = (
        context_df.groupby("session_bucket")
        .agg(trades=("session_bucket", "size"), total_pnl=("pnl", "sum"))
        .sort_values(["total_pnl", "trades"], ascending=[False, False])
        .reset_index()
        if not context_df.empty
        else pd.DataFrame(columns=["session_bucket", "trades", "total_pnl"])
    )
    session_concentration.to_csv(output_dir / "session_concentration.csv", index=False)

    top_diffs = comparison_df.head(3)["feature"].tolist()
    summary = {
        "artifact_path": artifact_path,
        "matrix_dir": str(matrix_dir),
        "top_k": top_k,
        "max_longs_per_day": max_longs,
        "min_score": min_score,
        "counts": {
            "selected_actions": int(len(selected_df)),
            "trades": int(len(trades_df)),
            "gate_rejections": int(len(rejected_df)),
            "w1_losers": (
                int(((cohort_df["cohort"] == "w1_losers")).sum())
                if not cohort_df.empty
                else 0
            ),
            "w2_winners": (
                int(((cohort_df["cohort"] == "w2_winners")).sum())
                if not cohort_df.empty
                else 0
            ),
        },
        "top_differences": top_diffs,
        "root_cause_note": (
            "Winning later-window trades differ most from weak early-window losers on "
            + ", ".join(f"`{feature}`" for feature in top_diffs)
            + ". Use these contexts for the first robustness gate."
            if top_diffs
            else "No cohort differences were available."
        ),
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    report_lines = [
        "# Action Ranker Forensic Report",
        "",
        f"- artifact: `{artifact_path}`",
        f"- source matrix: `{matrix_dir}`",
        f"- best config: `top_k={top_k}, max_longs_per_day={max_longs}, min_score={min_score}`",
        f"- selected actions: `{summary['counts']['selected_actions']}`",
        f"- completed trades: `{summary['counts']['trades']}`",
        f"- gate rejections: `{summary['counts']['gate_rejections']}`",
        f"- `w1` losing trades: `{summary['counts']['w1_losers']}`",
        f"- `w2` winning trades: `{summary['counts']['w2_winners']}`",
        "",
        "## Top Differences",
        "",
    ]
    report_lines.extend(f"- {feature}" for feature in top_diffs)
    report_lines.extend(["", "## Root Cause Note", "", summary["root_cause_note"], ""])
    (output_dir / "report.md").write_text("\n".join(report_lines), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build forensic report for best action-ranker config"
    )
    parser.add_argument(
        "--matrix-dir",
        default="output/ml_action_ranker_xgb_budget_matrix_2026-03-19",
        help="Completed action-ranker replay output directory",
    )
    parser.add_argument(
        "--windows",
        default="w1:2026-03-06:2026-03-11,w2:2026-03-12:2026-03-13",
        help="Comma-separated forensic windows",
    )
    parser.add_argument(
        "--output-dir",
        default="output/ml_action_ranker_xgb_forensic_2026-03-19",
        help="Output directory for forensic artifacts",
    )
    parser.add_argument("--bar-source", choices=["gold", "polygon"], default="polygon")
    parser.add_argument("--artifact-path", default=None)
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--max-longs-per-day", type=int, default=None)
    parser.add_argument("--weak-context-max-pressure-k", type=float, default=None)
    parser.add_argument("--weak-context-max-spread", type=float, default=None)
    parser.add_argument("--weak-context-max-depth-imb-k", type=float, default=None)
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional shared cache directory for scored actions.",
    )
    args = parser.parse_args()

    summary = run_forensic_report(
        matrix_dir=Path(args.matrix_dir),
        output_dir=Path(args.output_dir),
        windows=_parse_windows(args.windows),
        bar_source=args.bar_source,
        artifact_path=args.artifact_path,
        min_score=args.min_score,
        top_k=args.top_k,
        max_longs_per_day=args.max_longs_per_day,
        weak_context_gate=_matrix_or_explicit_gate(
            matrix_dir=Path(args.matrix_dir),
            max_pressure_k=args.weak_context_max_pressure_k,
            max_spread=args.weak_context_max_spread,
            max_depth_imb_k=args.weak_context_max_depth_imb_k,
        ),
        cache_dir=Path(args.cache_dir) if args.cache_dir else None,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
