#!/usr/bin/env python3
"""Run a top-K daily trade-budget backtest on an ML model.

This is the first explicit trade-budget allocator branch from the master plan.
It keeps the exact ML scoring path, then ranks same-day entry candidates and
selects only the top K, optionally capping long entries per day.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_hypothesis_test import DEFAULT_CONFIG, load_polygon_bars
from src.backtest import AlphaBacktestEngine
from src.backtest.engine import BacktestResult
from src.data import GoldLoader, L2Loader
from src.metrics import compute_all_metrics
from src.signals import MLSignal
from src.signals.base import ExitEvent, Position, Signal, SignalEvent, SignalSide

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowSpec:
    label: str
    start: str
    end: str


@dataclass(frozen=True)
class CandidateEntry:
    date: str
    symbol: str
    timestamp: pd.Timestamp
    side: SignalSide
    confidence: float
    probability_gap: float
    p_up: float
    p_down: float
    p_flat: float
    rank_score: float


class ScheduledBudgetSignal(Signal):
    """Replay only a preselected set of ML entries while keeping ML exit logic."""

    def __init__(
        self,
        config: dict,
        scheduled_entries: list[SignalEvent],
        model_artifact: dict[str, Any],
    ) -> None:
        super().__init__(config)
        self._delegate = MLSignal(config, model_artifact=model_artifact)
        self.signal_name = self._delegate.signal_name
        self._entries_by_key = {
            (event.symbol, pd.Timestamp(event.timestamp)): event
            for event in scheduled_entries
        }

    def check_entry(
        self,
        features: dict,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> SignalEvent | None:
        del features
        return self._entries_by_key.get((str(bar["symbol"]), pd.Timestamp(timestamp)))

    def check_exit(
        self,
        position: Position,
        features: dict,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> ExitEvent | None:
        return self._delegate.check_exit(position, features, bar, timestamp)

    def create_position(
        self,
        signal: SignalEvent,
        entry_price: float,
        entry_time: pd.Timestamp,
        quantity: int,
    ) -> Position:
        return self._delegate.create_position(signal, entry_price, entry_time, quantity)


def _parse_int_list(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _parse_windows(value: str) -> list[WindowSpec]:
    windows: list[WindowSpec] = []
    for chunk in value.split(","):
        label, start, end = [part.strip() for part in chunk.split(":")]
        windows.append(WindowSpec(label=label, start=start, end=end))
    if not windows:
        raise ValueError("At least one window must be provided")
    return windows


def _base_config(
    *,
    model_path: str,
    threshold: float,
    bar_source: str,
    time_limit_minutes: int,
) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["data"]["bar_source"] = bar_source
    config["signals"]["ml"]["model_path"] = model_path
    config["signals"]["ml"]["confidence_threshold"] = threshold
    config["signals"]["ml"]["long_confidence_threshold"] = threshold
    config["signals"]["ml"]["short_confidence_threshold"] = threshold
    config["signals"]["ml"]["min_probability_gap"] = 0.0
    config["signals"]["ml"]["max_flat_probability"] = 1.0
    config["signals"]["ml"]["exit_mode"] = "time_only"
    config["signals"]["ml"]["time_limit_minutes"] = time_limit_minutes
    config["signals"]["ml"]["target_pct"] = 0.0
    config["signals"]["ml"]["stop_pct"] = 0.0
    config["ml"]["max_symbols"] = 0
    return config


def _load_daily_payloads(
    *,
    start_date: str,
    end_date: str,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    l2_loader = L2Loader()
    gold_loader = GoldLoader()
    bar_source = config.get("data", {}).get("bar_source", "polygon")
    available_dates = [
        date
        for date in l2_loader.get_available_dates(source_type="any")
        if start_date <= date <= end_date
    ]
    daily_payloads: list[dict[str, Any]] = []

    for date in available_dates:
        symbols = sorted(l2_loader.get_available_symbols(date, source_type="any"))
        day_bar_frames: list[pd.DataFrame] = []
        day_l2_frames: list[pd.DataFrame] = []
        for symbol in symbols:
            try:
                if bar_source == "polygon":
                    bars = load_polygon_bars(symbol, date, date, config)
                else:
                    bars = gold_loader.load_bars(symbol, date, date)
                if not bars.empty:
                    bars["symbol"] = symbol
                    day_bar_frames.append(bars)
            except Exception as exc:
                logger.debug("Skipping bars for %s %s: %s", symbol, date, exc)
            try:
                day_l2_frames.append(
                    l2_loader.load_snapshots(symbol, date, source_type="any")
                )
            except FileNotFoundError:
                continue

        if day_bar_frames:
            daily_payloads.append(
                {
                    "date": date,
                    "bars": pd.concat(day_bar_frames, ignore_index=True),
                    "l2": (
                        pd.concat(day_l2_frames, ignore_index=True)
                        if day_l2_frames
                        else None
                    ),
                }
            )
    if not daily_payloads:
        raise ValueError(f"No ML payloads available for {start_date} to {end_date}")
    return daily_payloads


def _build_model_artifact(signal: MLSignal) -> dict[str, Any]:
    return {
        "model": signal._model,
        "model_family": getattr(signal, "_model_family", "xgb_multiclass"),
        "feature_columns": signal._feature_cols,
        "calibrator": getattr(signal, "_calibrator", None),
        "recommended_threshold": getattr(signal, "_recommended_threshold", None),
    }


def _score_day_candidates(
    *,
    bars_df: pd.DataFrame,
    l2_df: pd.DataFrame | None,
    model_signal: MLSignal,
    config: dict[str, Any],
) -> list[CandidateEntry]:
    engine = AlphaBacktestEngine(config)
    if l2_df is not None and not l2_df.empty:
        engine._build_l2_index(l2_df)

    executable_last_ts = bars_df.groupby("symbol")["ts"].max().to_dict()
    candidates: list[CandidateEntry] = []
    sorted_bars = bars_df.sort_values(["ts", "symbol"]).reset_index(drop=True)

    for ts, group in sorted_bars.groupby("ts", sort=True):
        for _, bar in group.iterrows():
            symbol = str(bar["symbol"])
            if pd.Timestamp(ts) >= pd.Timestamp(executable_last_ts[symbol]):
                continue
            bar_data = engine._prepare_bar_data(bar, l2_df, ts)
            probabilities = model_signal.predict_probabilities(
                bar_data.features,
                symbol=symbol,
                timestamp=pd.Timestamp(ts),
            )
            if probabilities is None:
                continue

            p_down, p_flat, p_up = probabilities
            event = model_signal.entry_event_from_probabilities(
                symbol=symbol,
                timestamp=pd.Timestamp(ts),
                p_down=p_down,
                p_flat=p_flat,
                p_up=p_up,
            )
            if event is None:
                continue

            probability_gap = float(event.features.get("probability_gap", 0.0))
            candidates.append(
                CandidateEntry(
                    date=pd.Timestamp(ts).strftime("%Y-%m-%d"),
                    symbol=symbol,
                    timestamp=pd.Timestamp(ts),
                    side=event.side,
                    confidence=float(event.confidence),
                    probability_gap=probability_gap,
                    p_up=float(p_up),
                    p_down=float(p_down),
                    p_flat=float(p_flat),
                    rank_score=float(event.confidence),
                )
            )

    return candidates


def _select_daily_topk(
    candidates: list[CandidateEntry],
    *,
    top_k: int,
    max_longs_per_day: int | None,
) -> list[CandidateEntry]:
    ordered = sorted(
        candidates,
        key=lambda row: (
            -row.rank_score,
            -row.probability_gap,
            row.timestamp,
            row.symbol,
        ),
    )

    selected: list[CandidateEntry] = []
    longs_selected = 0

    for row in ordered:
        if len(selected) >= top_k:
            break
        if (
            max_longs_per_day is not None
            and row.side == SignalSide.LONG
            and longs_selected >= max_longs_per_day
        ):
            continue
        selected.append(row)
        if row.side == SignalSide.LONG:
            longs_selected += 1

    return sorted(selected, key=lambda row: (row.timestamp, row.symbol))


def _candidate_to_event(candidate: CandidateEntry) -> SignalEvent:
    return SignalEvent(
        symbol=candidate.symbol,
        timestamp=candidate.timestamp,
        side=candidate.side,
        confidence=candidate.confidence,
        features={
            "p_up": candidate.p_up,
            "p_down": candidate.p_down,
            "p_flat": candidate.p_flat,
            "probability_gap": candidate.probability_gap,
            "rank_score": candidate.rank_score,
        },
        signal_name="MLSignal",
    )


def _run_day_budget(
    *,
    payload: dict[str, Any],
    config: dict[str, Any],
    model_artifact: dict[str, Any],
    model_signal: MLSignal,
    top_k: int,
    max_longs_per_day: int | None,
) -> tuple[BacktestResult, list[CandidateEntry]]:
    bars_df = payload["bars"].copy()
    l2_df = payload["l2"]
    date = payload["date"]

    candidates = _score_day_candidates(
        bars_df=bars_df,
        l2_df=l2_df,
        model_signal=model_signal,
        config=config,
    )
    selected = _select_daily_topk(
        candidates,
        top_k=top_k,
        max_longs_per_day=max_longs_per_day,
    )

    if not selected:
        empty = BacktestResult()
        empty.start_date = date
        empty.end_date = date
        empty.symbols_tested = sorted(bars_df["symbol"].unique().tolist())
        empty.equity_curve = pd.Series(
            [config["initial_capital"]], index=[bars_df["ts"].min()]
        )
        return empty, selected

    engine = AlphaBacktestEngine(config)
    scheduled_signal = ScheduledBudgetSignal(
        config,
        scheduled_entries=[_candidate_to_event(candidate) for candidate in selected],
        model_artifact=model_artifact,
    )
    result = engine.run(bars_df, l2_df=l2_df, signals=[scheduled_signal])
    return result, selected


def run_budget_matrix(
    *,
    model_path: str,
    windows: list[WindowSpec],
    daily_top_ks: list[int],
    max_longs_per_day_values: list[int],
    output_dir: Path,
    threshold: float = 0.35,
    bar_source: str = "polygon",
    time_limit_minutes: int = 5,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    all_results: list[dict[str, Any]] = []
    candidate_rows_by_key: dict[tuple[int, int], list[dict[str, Any]]] = {}
    trade_rows_by_key: dict[tuple[int, int], list[dict[str, Any]]] = {}

    base_config = _base_config(
        model_path=model_path,
        threshold=threshold,
        bar_source=bar_source,
        time_limit_minutes=time_limit_minutes,
    )
    model_signal = MLSignal(base_config)
    model_artifact = _build_model_artifact(model_signal)

    payloads_by_window = {
        window.label: _load_daily_payloads(
            start_date=window.start,
            end_date=window.end,
            config=base_config,
        )
        for window in windows
    }
    active_days = sum(len(payloads) for payloads in payloads_by_window.values())

    for top_k in daily_top_ks:
        for max_longs_per_day in max_longs_per_day_values:
            logger.info(
                "Running trade-budget config top_k=%s max_longs_per_day=%s",
                top_k,
                max_longs_per_day,
            )
            row: dict[str, Any] = {
                "top_k": top_k,
                "max_longs_per_day": max_longs_per_day,
                "threshold": threshold,
                "time_limit_minutes": time_limit_minutes,
                "combined_trades": 0,
                "combined_total_pnl": 0.0,
                "combined_total_return_pct": 0.0,
                "combined_gross_profit": 0.0,
                "combined_gross_loss": 0.0,
                "combined_signals_generated": 0,
                "combined_entries_executed": 0,
                "combined_exits_executed": 0,
                "combined_selected_candidates": 0,
                "active_days": active_days,
            }
            candidate_rows: list[dict[str, Any]] = []
            trade_rows: list[dict[str, Any]] = []

            for window in windows:
                window_trades = 0
                window_pnl = 0.0
                window_selected = 0
                window_signals = 0
                window_entries = 0
                window_exits = 0
                window_gp = 0.0
                window_gl = 0.0

                for payload in payloads_by_window[window.label]:
                    day_result, selected = _run_day_budget(
                        payload=payload,
                        config=base_config,
                        model_artifact=model_artifact,
                        model_signal=model_signal,
                        top_k=top_k,
                        max_longs_per_day=max_longs_per_day,
                    )
                    metrics = compute_all_metrics(
                        day_result,
                        initial_capital=base_config["initial_capital"],
                    )
                    window_trades += int(metrics["num_trades"])
                    window_pnl += float(metrics["total_pnl"])
                    window_selected += len(selected)
                    window_signals += int(day_result.signals_generated)
                    window_entries += int(day_result.entries_executed)
                    window_exits += int(day_result.exits_executed)

                    for trade in day_result.trades:
                        pnl = float(trade.pnl)
                        if pnl > 0:
                            window_gp += pnl
                        elif pnl < 0:
                            window_gl += abs(pnl)
                        trade_rows.append(
                            {
                                "window": window.label,
                                "date": payload["date"],
                                "symbol": trade.symbol,
                                "side": trade.side.value,
                                "entry_time": trade.entry_time,
                                "exit_time": trade.exit_time,
                                "entry_price": trade.entry_price,
                                "exit_price": trade.exit_price,
                                "quantity": trade.quantity,
                                "exit_reason": trade.exit_reason,
                                "pnl": trade.pnl,
                                "pnl_pct": trade.pnl_pct,
                                "hold_minutes": trade.hold_minutes,
                            }
                        )

                    for rank, candidate in enumerate(selected, start=1):
                        candidate_rows.append(
                            {
                                "window": window.label,
                                "date": payload["date"],
                                "top_k": top_k,
                                "max_longs_per_day": max_longs_per_day,
                                "selected_rank": rank,
                                "symbol": candidate.symbol,
                                "timestamp": candidate.timestamp,
                                "side": candidate.side.value,
                                "confidence": candidate.confidence,
                                "probability_gap": candidate.probability_gap,
                                "rank_score": candidate.rank_score,
                            }
                        )

                row[f"{window.label}_trades"] = window_trades
                row[f"{window.label}_pnl"] = window_pnl
                row[f"{window.label}_selected_candidates"] = window_selected
                row[f"{window.label}_signals_generated"] = window_signals
                row[f"{window.label}_entries_executed"] = window_entries
                row[f"{window.label}_exits_executed"] = window_exits
                row[f"{window.label}_profit_factor"] = (
                    window_gp / window_gl
                    if window_gl > 0
                    else (999.0 if window_gp > 0 else 0.0)
                )

                row["combined_trades"] += window_trades
                row["combined_total_pnl"] += window_pnl
                row["combined_selected_candidates"] += window_selected
                row["combined_signals_generated"] += window_signals
                row["combined_entries_executed"] += window_entries
                row["combined_exits_executed"] += window_exits
                row["combined_gross_profit"] += window_gp
                row["combined_gross_loss"] += window_gl

            row["combined_total_return_pct"] = (
                row["combined_total_pnl"] / base_config["initial_capital"] * 100.0
            )
            row["combined_profit_factor"] = (
                row["combined_gross_profit"] / row["combined_gross_loss"]
                if row["combined_gross_loss"] > 0
                else (999.0 if row["combined_gross_profit"] > 0 else 0.0)
            )
            row["combined_avg_pnl_per_trade"] = (
                row["combined_total_pnl"] / row["combined_trades"]
                if row["combined_trades"] > 0
                else 0.0
            )
            row["combined_trades_per_day"] = (
                row["combined_trades"] / active_days if active_days > 0 else 0.0
            )
            row["trade_budget_pass"] = 3.0 <= row["combined_trades_per_day"] <= 5.0
            all_results.append(row)
            key = (top_k, max_longs_per_day)
            candidate_rows_by_key[key] = candidate_rows
            trade_rows_by_key[key] = trade_rows

    all_results.sort(
        key=lambda current: (
            current["combined_total_pnl"],
            current["combined_profit_factor"],
            current["combined_trades_per_day"],
        ),
        reverse=True,
    )
    best = all_results[0]
    best_key = (best["top_k"], best["max_longs_per_day"])

    pd.DataFrame(all_results).to_csv(output_dir / "matrix_results.csv", index=False)
    if candidate_rows_by_key.get(best_key):
        pd.DataFrame(candidate_rows_by_key[best_key]).to_csv(
            output_dir / "best_config_candidates.csv",
            index=False,
        )
    if trade_rows_by_key.get(best_key):
        pd.DataFrame(trade_rows_by_key[best_key]).to_csv(
            output_dir / "best_config_trades.csv",
            index=False,
        )

    summary = {
        "model_path": model_path,
        "threshold": threshold,
        "time_limit_minutes": time_limit_minutes,
        "bar_source": bar_source,
        "windows": [window.__dict__ for window in windows],
        "grid": {
            "daily_top_ks": daily_top_ks,
            "max_longs_per_day_values": max_longs_per_day_values,
        },
        "configs_tested": len(all_results),
        "best_config": best,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    report_lines = [
        "# ML Top-K Trade-Budget Matrix",
        "",
        "## Scope",
        f"- model: `{model_path}`",
        f"- threshold: `{threshold:.2f}`",
        f"- hold: `time_only / {time_limit_minutes}m`",
        f"- configs tested: `{len(all_results)}`",
        f"- active days: `{active_days}`",
        "",
        "## Best Config",
        f"- top_k: `{best['top_k']}`",
        f"- max_longs_per_day: `{best['max_longs_per_day']}`",
        f"- trades: `{best['combined_trades']}`",
        f"- trades/day: `{best['combined_trades_per_day']:.2f}`",
        f"- return: `{best['combined_total_return_pct']:+.3f}%`",
        f"- total pnl: `${best['combined_total_pnl']:+.2f}`",
        f"- profit factor: `{best['combined_profit_factor']:.2f}`",
        "",
        "## Top 5",
    ]
    for rank, row in enumerate(all_results[:5], start=1):
        report_lines.append(
            f"{rank}. top_k={row['top_k']}, max_longs={row['max_longs_per_day']}, "
            f"trades={row['combined_trades']}, trades/day={row['combined_trades_per_day']:.2f}, "
            f"return={row['combined_total_return_pct']:+.3f}%, pf={row['combined_profit_factor']:.2f}"
        )
    (output_dir / "report.md").write_text(
        "\n".join(report_lines) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ML top-K trade-budget matrix")
    parser.add_argument(
        "--model-path",
        type=str,
        default="models/h60_two_stage_logistic_v5b_2026-03-16.pkl",
        help="ML model artifact path",
    )
    parser.add_argument(
        "--windows",
        type=str,
        default="w1:2026-03-06:2026-03-11,w2:2026-03-12:2026-03-13",
        help="Comma-separated windows label:start:end",
    )
    parser.add_argument(
        "--daily-top-ks",
        type=str,
        default="3,4,5",
        help="Comma-separated daily top-K budgets",
    )
    parser.add_argument(
        "--max-longs-per-day-values",
        type=str,
        default="1,2,3",
        help="Comma-separated per-day long caps",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.35,
        help="Symmetric ML confidence threshold floor",
    )
    parser.add_argument(
        "--time-limit-minutes",
        type=int,
        default=5,
        help="Time-only hold duration",
    )
    parser.add_argument(
        "--bar-source",
        type=str,
        choices=["gold", "polygon"],
        default="polygon",
        help="Minute-bar source",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output/ml_topk_budget_matrix_2026-03-16",
        help="Output directory",
    )
    args = parser.parse_args()

    summary = run_budget_matrix(
        model_path=args.model_path,
        windows=_parse_windows(args.windows),
        daily_top_ks=_parse_int_list(args.daily_top_ks),
        max_longs_per_day_values=_parse_int_list(args.max_longs_per_day_values),
        output_dir=Path(args.output_dir),
        threshold=args.threshold,
        bar_source=args.bar_source,
        time_limit_minutes=args.time_limit_minutes,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
