#!/usr/bin/env python3
"""Build the Phase 2 long-side regime comparison report."""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_hypothesis_test import (
    DEFAULT_CONFIG,
    load_polygon_bars,
    run_single_hypothesis,
)
from src.backtest import AlphaBacktestEngine
from src.data import L2Loader

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WindowSpec:
    label: str
    start: str
    end: str


def _parse_windows(value: str) -> list[WindowSpec]:
    windows: list[WindowSpec] = []
    for chunk in value.split(","):
        label, start, end = [part.strip() for part in chunk.split(":")]
        windows.append(WindowSpec(label=label, start=start, end=end))
    if not windows:
        raise ValueError("At least one window must be provided")
    return windows


def _source_type_from_features(features: dict[str, Any]) -> str:
    if float(features.get("source_is_features", 0.0)) > 0.5:
        return "features"
    if float(features.get("source_is_raw", 0.0)) > 0.5:
        return "raw"
    return "unknown"


def _config(
    *,
    model_path: str,
    threshold: float,
    long_threshold: float,
    short_threshold: float,
    bar_source: str,
    time_limit_minutes: int,
) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["data"]["bar_source"] = bar_source
    config["signals"]["ml"]["model_path"] = model_path
    config["signals"]["ml"]["confidence_threshold"] = threshold
    config["signals"]["ml"]["long_confidence_threshold"] = long_threshold
    config["signals"]["ml"]["short_confidence_threshold"] = short_threshold
    config["signals"]["ml"]["min_probability_gap"] = 0.0
    config["signals"]["ml"]["max_flat_probability"] = 1.0
    config["signals"]["ml"]["exit_mode"] = "time_only"
    config["signals"]["ml"]["time_limit_minutes"] = time_limit_minutes
    config["signals"]["ml"]["target_pct"] = 0.0
    config["signals"]["ml"]["stop_pct"] = 0.0
    config["ml"]["max_symbols"] = 0
    return config


def _load_symbol_day_payload(
    symbol: str,
    date: str,
    config: dict[str, Any],
    cache: dict[tuple[str, str], tuple[pd.DataFrame, pd.DataFrame]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    key = (symbol, date)
    if key in cache:
        return cache[key]

    bars = load_polygon_bars(symbol, date, date, config)
    bars["symbol"] = symbol
    l2_loader = L2Loader()
    l2_df = l2_loader.load_snapshots(symbol, date, source_type="any")
    cache[key] = (bars, l2_df)
    return cache[key]


def _entry_context(
    trade_row: dict[str, Any],
    config: dict[str, Any],
    cache: dict[tuple[str, str], tuple[pd.DataFrame, pd.DataFrame]],
) -> dict[str, Any]:
    entry_ts = pd.Timestamp(trade_row["entry_time"])
    symbol = str(trade_row["symbol"])
    date = entry_ts.strftime("%Y-%m-%d")
    bars_df, l2_df = _load_symbol_day_payload(symbol, date, config, cache)
    bar_match = bars_df.loc[pd.to_datetime(bars_df["ts"]) == entry_ts]
    if bar_match.empty:
        raise RuntimeError(f"Could not find entry bar for {symbol} at {entry_ts}")

    engine = AlphaBacktestEngine(config)
    bar_data = engine._prepare_bar_data(bar_match.iloc[0], l2_df, entry_ts)
    features = bar_data.features
    return {
        "session_bucket": features.get("session_bucket"),
        "source_type": _source_type_from_features(features),
        "spread": features.get("spread"),
        "spread_std_30s": features.get("spread_std_30s"),
        "spread_std_60s": features.get("spread_std_60s"),
        "micro_off": features.get("micro_off"),
        "micro_off_std_30s": features.get("micro_off_std_30s"),
        "micro_off_std_60s": features.get("micro_off_std_60s"),
        "depth_imb_k": features.get("depth_imb_k"),
        "depth_imb_k_mean_10s": features.get("depth_imb_k_mean_10s"),
        "depth_imb_k_mean_60s": features.get("depth_imb_k_mean_60s"),
        "pressure_k": features.get("pressure_k"),
    }


def run_regime_report(
    *,
    model_path: str,
    windows: list[WindowSpec],
    threshold: float,
    long_threshold: float,
    short_threshold: float,
    output_dir: Path,
    bar_source: str = "polygon",
    time_limit_minutes: int = 5,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    config = _config(
        model_path=model_path,
        threshold=threshold,
        long_threshold=long_threshold,
        short_threshold=short_threshold,
        bar_source=bar_source,
        time_limit_minutes=time_limit_minutes,
    )

    trade_rows: list[dict[str, Any]] = []
    for window in windows:
        logger.info("Running forensic baseline for %s", window.label)
        payload = run_single_hypothesis("ml", window.start, window.end, config)
        for trade in payload["result"].trades:
            trade_rows.append(
                {
                    "window": window.label,
                    "window_start": window.start,
                    "window_end": window.end,
                    "symbol": trade.symbol,
                    "side": trade.side.value,
                    "entry_time": trade.entry_time,
                    "exit_time": trade.exit_time,
                    "pnl": trade.pnl,
                    "pnl_pct": trade.pnl_pct,
                    "hold_minutes": trade.hold_minutes,
                    "exit_reason": trade.exit_reason,
                    "is_winner": trade.pnl > 0,
                }
            )

    trades_df = pd.DataFrame(trade_rows)
    long_df = trades_df[trades_df["side"] == "long"].copy()
    cohorts = {
        "w1_winning_longs": long_df[
            (long_df["window"] == "w1") & (long_df["is_winner"])
        ].copy(),
        "w2_losing_longs": long_df[
            (long_df["window"] == "w2") & (~long_df["is_winner"])
        ].copy(),
    }

    cache: dict[tuple[str, str], tuple[pd.DataFrame, pd.DataFrame]] = {}
    context_rows: list[dict[str, Any]] = []
    for cohort_name, cohort_df in cohorts.items():
        for _, row in cohort_df.iterrows():
            context = _entry_context(row.to_dict(), config, cache)
            context_rows.append({**row.to_dict(), "cohort": cohort_name, **context})

    context_df = pd.DataFrame(context_rows)
    context_df.to_csv(output_dir / "entry_contexts.csv", index=False)
    trades_df.to_csv(output_dir / "all_trades.csv", index=False)

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
    ]
    summary_rows: list[dict[str, Any]] = []
    for column in compare_cols:
        w1_values = pd.to_numeric(
            context_df.loc[context_df["cohort"] == "w1_winning_longs", column],
            errors="coerce",
        )
        w2_values = pd.to_numeric(
            context_df.loc[context_df["cohort"] == "w2_losing_longs", column],
            errors="coerce",
        )
        summary_rows.append(
            {
                "feature": column,
                "w1_mean": (
                    float(w1_values.mean()) if not w1_values.empty else float("nan")
                ),
                "w2_mean": (
                    float(w2_values.mean()) if not w2_values.empty else float("nan")
                ),
                "mean_diff": (
                    float(w2_values.mean() - w1_values.mean())
                    if not w1_values.empty and not w2_values.empty
                    else float("nan")
                ),
                "w1_count": int(w1_values.notna().sum()),
                "w2_count": int(w2_values.notna().sum()),
            }
        )
    summary_df = pd.DataFrame(summary_rows).sort_values(
        "mean_diff", key=lambda s: s.abs(), ascending=False
    )
    summary_df.to_csv(output_dir / "feature_comparison.csv", index=False)

    source_counts = (
        context_df.groupby(["cohort", "source_type"])
        .size()
        .rename("count")
        .reset_index()
        if not context_df.empty
        else pd.DataFrame(columns=["cohort", "source_type", "count"])
    )
    source_counts.to_csv(output_dir / "source_type_comparison.csv", index=False)

    top_diffs = summary_df.head(3)["feature"].tolist()
    root_cause = (
        "Later-window losing longs differ most on "
        + ", ".join(f"`{feature}`" for feature in top_diffs)
        + ". These should drive the next side-aware gating and feature changes."
        if top_diffs
        else "No comparative feature differences were available."
    )
    summary = {
        "model_path": model_path,
        "threshold": threshold,
        "long_threshold": long_threshold,
        "short_threshold": short_threshold,
        "windows": [window.__dict__ for window in windows],
        "counts": {
            "all_trades": int(len(trades_df)),
            "all_longs": int(len(long_df)),
            "w1_winning_longs": int(len(cohorts["w1_winning_longs"])),
            "w2_losing_longs": int(len(cohorts["w2_losing_longs"])),
        },
        "top_differences": top_diffs,
        "root_cause_note": root_cause,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    report_lines = [
        "# Phase 2 Long-Side Regime Comparison",
        "",
        f"- model: `{model_path}`",
        f"- threshold: `{threshold:.2f}`",
        f"- long threshold: `{long_threshold:.2f}`",
        f"- short threshold: `{short_threshold:.2f}`",
        "",
        "## Cohort Counts",
        "",
        f"- all trades: `{summary['counts']['all_trades']}`",
        f"- all longs: `{summary['counts']['all_longs']}`",
        f"- w1 winning longs: `{summary['counts']['w1_winning_longs']}`",
        f"- w2 losing longs: `{summary['counts']['w2_losing_longs']}`",
        "",
        "## Root Cause Note",
        "",
        root_cause,
        "",
        "## Top Mean Differences",
        "",
    ]
    for _, row in summary_df.head(10).iterrows():
        report_lines.append(
            f"- `{row['feature']}`: w1 mean `{row['w1_mean']:.4f}`, "
            f"w2 mean `{row['w2_mean']:.4f}`, diff `{row['mean_diff']:.4f}`"
        )
    (output_dir / "report.md").write_text("\n".join(report_lines), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the ML long-side regime comparison"
    )
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
    parser.add_argument("--threshold", type=float, default=0.40)
    parser.add_argument("--long-threshold", type=float, default=0.40)
    parser.add_argument("--short-threshold", type=float, default=0.40)
    parser.add_argument("--bar-source", default="polygon", choices=["gold", "polygon"])
    parser.add_argument("--time-limit-minutes", type=int, default=5)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/ml_v4_long_side_regime_2026-03-15"),
        help="Output directory for regime artifacts",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_regime_report(
        model_path=args.model_path,
        windows=_parse_windows(args.windows),
        threshold=args.threshold,
        long_threshold=args.long_threshold,
        short_threshold=args.short_threshold,
        output_dir=args.output_dir,
        bar_source=args.bar_source,
        time_limit_minutes=args.time_limit_minutes,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
