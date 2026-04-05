#!/usr/bin/env python3
"""Run the Phase 1 side-threshold matrix on a fixed ML model and policy."""

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

from scripts.run_hypothesis_test import DEFAULT_CONFIG, run_single_hypothesis

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowSpec:
    label: str
    start: str
    end: str


def _parse_float_list(value: str) -> list[float]:
    return [float(item.strip()) for item in value.split(",") if item.strip()]


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
    long_threshold: float,
    short_threshold: float,
    bar_source: str,
    time_limit_minutes: int,
    min_probability_gap: float,
    max_flat_probability: float,
) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["data"]["bar_source"] = bar_source
    config["signals"]["ml"]["model_path"] = model_path
    config["signals"]["ml"]["confidence_threshold"] = min(
        long_threshold, short_threshold
    )
    config["signals"]["ml"]["long_confidence_threshold"] = long_threshold
    config["signals"]["ml"]["short_confidence_threshold"] = short_threshold
    config["signals"]["ml"]["min_probability_gap"] = min_probability_gap
    config["signals"]["ml"]["max_flat_probability"] = max_flat_probability
    config["signals"]["ml"]["exit_mode"] = "time_only"
    config["signals"]["ml"]["time_limit_minutes"] = time_limit_minutes
    config["signals"]["ml"]["target_pct"] = 0.0
    config["signals"]["ml"]["stop_pct"] = 0.0
    config["ml"]["max_symbols"] = 0
    return config


def _trade_rows(result: Any, window_label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trade in result.trades:
        rows.append(
            {
                "window": window_label,
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
    return rows


def run_matrix(
    *,
    model_path: str,
    windows: list[WindowSpec],
    long_thresholds: list[float],
    short_thresholds: list[float],
    output_dir: Path,
    bar_source: str = "polygon",
    time_limit_minutes: int = 5,
    min_probability_gap: float = 0.0,
    max_flat_probability: float = 1.0,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    trade_rows_by_key: dict[tuple[float, float], list[dict[str, Any]]] = {}

    day_count = sum(
        len(pd.date_range(window.start, window.end, freq="D")) for window in windows
    )

    for long_threshold in long_thresholds:
        for short_threshold in short_thresholds:
            logger.info(
                "Running side-threshold config L=%.2f S=%.2f",
                long_threshold,
                short_threshold,
            )
            combined = {
                "long_threshold": long_threshold,
                "short_threshold": short_threshold,
                "confidence_threshold": min(long_threshold, short_threshold),
                "exit_mode": "time_only",
                "time_limit_minutes": time_limit_minutes,
                "min_probability_gap": min_probability_gap,
                "max_flat_probability": max_flat_probability,
                "combined_total_pnl": 0.0,
                "combined_total_return_pct": 0.0,
                "combined_trades": 0,
                "combined_signals_generated": 0,
                "combined_entries_executed": 0,
                "combined_exits_executed": 0,
                "combined_wins": 0,
                "combined_losses": 0,
                "combined_gross_profit": 0.0,
                "combined_gross_loss": 0.0,
                "combined_max_drawdown_pct": 0.0,
                "days_in_scope": day_count,
            }
            combined_trade_rows: list[dict[str, Any]] = []

            for window in windows:
                config = _base_config(
                    model_path=model_path,
                    long_threshold=long_threshold,
                    short_threshold=short_threshold,
                    bar_source=bar_source,
                    time_limit_minutes=time_limit_minutes,
                    min_probability_gap=min_probability_gap,
                    max_flat_probability=max_flat_probability,
                )
                payload = run_single_hypothesis("ml", window.start, window.end, config)
                metrics = payload["metrics"]
                result = payload["result"]

                combined["combined_total_pnl"] += float(metrics["total_pnl"])
                combined["combined_total_return_pct"] += float(
                    metrics["total_return_pct"]
                )
                combined["combined_trades"] += int(metrics["num_trades"])
                combined["combined_signals_generated"] += int(result.signals_generated)
                combined["combined_entries_executed"] += int(result.entries_executed)
                combined["combined_exits_executed"] += int(result.exits_executed)
                combined["combined_max_drawdown_pct"] = max(
                    combined["combined_max_drawdown_pct"],
                    float(metrics["max_drawdown_pct"]),
                )

                wins = 0
                losses = 0
                gross_profit = 0.0
                gross_loss = 0.0
                for trade in result.trades:
                    if trade.pnl > 0:
                        wins += 1
                        gross_profit += float(trade.pnl)
                    elif trade.pnl < 0:
                        losses += 1
                        gross_loss += abs(float(trade.pnl))

                combined["combined_wins"] += wins
                combined["combined_losses"] += losses
                combined["combined_gross_profit"] += gross_profit
                combined["combined_gross_loss"] += gross_loss
                combined_trade_rows.extend(_trade_rows(result, window.label))

                combined[f"{window.label}_trades"] = int(metrics["num_trades"])
                combined[f"{window.label}_signals_generated"] = int(
                    result.signals_generated
                )
                combined[f"{window.label}_entries_executed"] = int(
                    result.entries_executed
                )
                combined[f"{window.label}_exits_executed"] = int(result.exits_executed)
                combined[f"{window.label}_return_pct"] = float(
                    metrics["total_return_pct"]
                )
                combined[f"{window.label}_pnl"] = float(metrics["total_pnl"])
                combined[f"{window.label}_profit_factor"] = float(
                    metrics["profit_factor"]
                )
                combined[f"{window.label}_win_rate"] = float(metrics["win_rate"])

            combined["combined_profit_factor"] = (
                combined["combined_gross_profit"] / combined["combined_gross_loss"]
                if combined["combined_gross_loss"] > 0
                else (999.0 if combined["combined_gross_profit"] > 0 else 0.0)
            )
            combined["combined_win_rate"] = (
                combined["combined_wins"] / combined["combined_trades"] * 100.0
                if combined["combined_trades"] > 0
                else 0.0
            )
            combined["combined_avg_pnl_per_trade"] = (
                combined["combined_total_pnl"] / combined["combined_trades"]
                if combined["combined_trades"] > 0
                else 0.0
            )
            combined["combined_trades_per_day"] = (
                combined["combined_trades"] / day_count if day_count > 0 else 0.0
            )
            combined["trade_budget_pass"] = (
                3.0 <= combined["combined_trades_per_day"] <= 5.0
            )
            results.append(combined)
            trade_rows_by_key[(long_threshold, short_threshold)] = combined_trade_rows

    results.sort(
        key=lambda row: (
            row["combined_total_pnl"],
            row["combined_profit_factor"],
            row["combined_trades_per_day"],
        ),
        reverse=True,
    )

    best = results[0]
    best_trade_rows = trade_rows_by_key.get(
        (best["long_threshold"], best["short_threshold"]), []
    )
    csv_path = output_dir / "matrix_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    if best_trade_rows:
        pd.DataFrame(best_trade_rows).to_csv(
            output_dir / "best_config_trades.csv", index=False
        )

    summary = {
        "model_path": model_path,
        "windows": [window.__dict__ for window in windows],
        "grid": {
            "long_thresholds": long_thresholds,
            "short_thresholds": short_thresholds,
            "exit_mode": "time_only",
            "time_limit_minutes": time_limit_minutes,
            "min_probability_gap": min_probability_gap,
            "max_flat_probability": max_flat_probability,
            "bar_source": bar_source,
        },
        "configs_tested": len(results),
        "best_config": best,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    report_lines = [
        "# Phase 1 Side-Threshold Matrix",
        "",
        "## Scope",
        "",
        f"- model: `{model_path}`",
        f"- exit: `time_only / {time_limit_minutes}m`",
        f"- bar source: `{bar_source}`",
        f"- windows: `{', '.join(f'{w.start} to {w.end}' for w in windows)}`",
        f"- long thresholds: `{', '.join(f'{value:.2f}' for value in long_thresholds)}`",
        f"- short thresholds: `{', '.join(f'{value:.2f}' for value in short_thresholds)}`",
        "",
        "## Best Config",
        "",
        f"- long threshold: `{best['long_threshold']:.2f}`",
        f"- short threshold: `{best['short_threshold']:.2f}`",
        f"- combined trades: `{best['combined_trades']}`",
        f"- combined trades/day: `{best['combined_trades_per_day']:.2f}`",
        f"- combined pnl: `${best['combined_total_pnl']:.2f}`",
        f"- combined return: `{best['combined_total_return_pct']:.3f}%`",
        f"- combined PF: `{best['combined_profit_factor']:.2f}`",
        f"- combined win rate: `{best['combined_win_rate']:.1f}%`",
        "",
        "## Ranked Results",
        "",
    ]
    for row in results:
        report_lines.append(
            f"- `L {row['long_threshold']:.2f} / S {row['short_threshold']:.2f}`: "
            f"trades `{row['combined_trades']}`, trades/day `{row['combined_trades_per_day']:.2f}`, "
            f"pnl `${row['combined_total_pnl']:.2f}`, PF `{row['combined_profit_factor']:.2f}`, "
            f"w2 pnl `${row.get('w2_pnl', 0.0):.2f}`"
        )
    (output_dir / "report.md").write_text("\n".join(report_lines), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the ML side-threshold matrix")
    parser.add_argument(
        "--model-path",
        default="models/h60_two_stage_logistic_v4_2026-03-15.pkl",
        help="Path to the model artifact",
    )
    parser.add_argument(
        "--windows",
        default="w1:2026-03-06:2026-03-11,w2:2026-03-12:2026-03-13",
        help="Comma-separated label:start:end windows",
    )
    parser.add_argument(
        "--long-thresholds",
        default="0.40,0.45,0.50",
        help="Comma-separated long thresholds",
    )
    parser.add_argument(
        "--short-thresholds",
        default="0.35,0.40,0.45",
        help="Comma-separated short thresholds",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/ml_v4_side_threshold_matrix_2026-03-15"),
        help="Output directory for matrix artifacts",
    )
    parser.add_argument("--bar-source", default="polygon", choices=["gold", "polygon"])
    parser.add_argument("--time-limit-minutes", type=int, default=5)
    parser.add_argument("--min-probability-gap", type=float, default=0.0)
    parser.add_argument("--max-flat-probability", type=float, default=1.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_matrix(
        model_path=args.model_path,
        windows=_parse_windows(args.windows),
        long_thresholds=_parse_float_list(args.long_thresholds),
        short_thresholds=_parse_float_list(args.short_thresholds),
        output_dir=args.output_dir,
        bar_source=args.bar_source,
        time_limit_minutes=args.time_limit_minutes,
        min_probability_gap=args.min_probability_gap,
        max_flat_probability=args.max_flat_probability,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
