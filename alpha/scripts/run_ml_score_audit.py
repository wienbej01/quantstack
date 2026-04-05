#!/usr/bin/env python3
"""Audit live ML score distributions on exact validation or test dates.

This script uses the same bar/L2/live feature path as the backtest runner, but stops
at probability generation. It is intended to answer whether a no-trade regime comes
from missing ML-ready bars, compressed confidence, or threshold selection.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.run_hypothesis_test import DEFAULT_CONFIG, load_polygon_bars
from src.backtest import AlphaBacktestEngine
from src.data import GoldLoader, L2Loader
from src.signals import MLSignal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _parse_thresholds(raw: str) -> tuple[float, ...]:
    thresholds = tuple(
        float(value.strip()) for value in raw.split(",") if value.strip()
    )
    if not thresholds:
        raise ValueError("At least one threshold is required")
    return thresholds


def _resolve_dates(args: argparse.Namespace) -> list[str]:
    if args.dates:
        return sorted(
            {value.strip() for value in args.dates.split(",") if value.strip()}
        )

    if not args.split_file or not args.date_split:
        raise ValueError("Provide --dates or both --split-file and --date-split")

    payload = json.loads(Path(args.split_file).read_text(encoding="utf-8"))
    split_info = payload.get("split_info", {})
    dates = split_info.get(args.date_split)
    if not dates:
        raise ValueError(
            f"No dates found for split '{args.date_split}' in {args.split_file}"
        )
    return sorted(str(value) for value in dates)


def _load_bars(
    symbol: str,
    date: str,
    *,
    bar_source: str,
    config: dict[str, Any],
    gold_loader: GoldLoader,
) -> pd.DataFrame:
    if bar_source == "polygon":
        return load_polygon_bars(symbol, date, date, config)
    return gold_loader.load_bars(symbol, date, date)


def _available_symbols_by_date(
    l2_loader: L2Loader, dates: list[str]
) -> dict[str, list[str]]:
    return {
        date: sorted(l2_loader.get_available_symbols(date, source_type="any"))
        for date in dates
    }


def _summarize_group(
    group: pd.DataFrame, thresholds: tuple[float, ...]
) -> dict[str, Any]:
    record = {
        "eligible_bars": int(len(group)),
        "p_up_p50": float(group["p_up"].quantile(0.50)),
        "p_up_p90": float(group["p_up"].quantile(0.90)),
        "p_up_p95": float(group["p_up"].quantile(0.95)),
        "p_down_p50": float(group["p_down"].quantile(0.50)),
        "p_down_p90": float(group["p_down"].quantile(0.90)),
        "p_down_p95": float(group["p_down"].quantile(0.95)),
        "confidence_p50": float(group["confidence"].quantile(0.50)),
        "confidence_p90": float(group["confidence"].quantile(0.90)),
        "confidence_p95": float(group["confidence"].quantile(0.95)),
    }
    for threshold in thresholds:
        hits = int((group["confidence"] >= threshold).sum())
        record[f"fraction_ge_{threshold:.2f}"] = (
            float(hits / len(group)) if len(group) else 0.0
        )
    return record


def _write_report(
    output_dir: Path,
    summary: dict[str, Any],
    thresholds: tuple[float, ...],
) -> None:
    lines = [
        "# ML Score Audit",
        "",
        "## Scope",
        "",
        f"- dates: `{', '.join(summary['dates'])}`",
        f"- bar source: `{summary['bar_source']}`",
        f"- model path: `{summary['model_path']}`",
        f"- symbols scanned: `{summary['symbols_scanned']}`",
        f"- total bars: `{summary['total_bars']}`",
        f"- ML-ready bars: `{summary['ml_ready_bars']}`",
        f"- scored bars: `{summary['scored_bars']}`",
        f"- readiness ratio: `{summary['ml_ready_ratio']:.1%}`",
        f"- scored ratio: `{summary['scored_ratio']:.1%}`",
        "",
        "## Overall Probabilities",
        "",
        f"- p_up p50 / p90 / p95: `{summary['overall']['p_up_p50']:.3f}` / "
        f"`{summary['overall']['p_up_p90']:.3f}` / `{summary['overall']['p_up_p95']:.3f}`",
        f"- p_down p50 / p90 / p95: `{summary['overall']['p_down_p50']:.3f}` / "
        f"`{summary['overall']['p_down_p90']:.3f}` / `{summary['overall']['p_down_p95']:.3f}`",
        f"- confidence p50 / p90 / p95: `{summary['overall']['confidence_p50']:.3f}` / "
        f"`{summary['overall']['confidence_p90']:.3f}` / `{summary['overall']['confidence_p95']:.3f}`",
        "",
        "## Threshold Fractions",
        "",
    ]
    for threshold in thresholds:
        lines.append(
            f"- confidence >= `{threshold:.2f}`: "
            f"`{summary['overall'][f'fraction_ge_{threshold:.2f}']:.2%}` of scored bars"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            summary["interpretation"],
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_score_audit(args: argparse.Namespace) -> dict[str, Any]:
    dates = _resolve_dates(args)
    thresholds = _parse_thresholds(args.thresholds)
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["data"]["bar_source"] = args.bar_source
    if args.model_path:
        config["signals"]["ml"]["model_path"] = args.model_path

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    gold_loader = GoldLoader()
    l2_loader = L2Loader()
    signal = MLSignal(config)
    symbols_by_date = _available_symbols_by_date(l2_loader, dates)

    scored_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    total_bars = 0
    ml_ready_bars = 0
    symbols_scanned = set()

    for date in dates:
        for symbol in symbols_by_date.get(date, []):
            try:
                bars = _load_bars(
                    symbol,
                    date,
                    bar_source=args.bar_source,
                    config=config,
                    gold_loader=gold_loader,
                )
                l2_df = l2_loader.load_snapshots(symbol, date, source_type="any")
            except (
                Exception
            ) as exc:  # noqa: BLE001 - audit should continue past missing symbols
                logger.debug("Skipping %s %s during score audit: %s", date, symbol, exc)
                continue

            if bars.empty or l2_df.empty:
                continue

            symbols_scanned.add(symbol)
            engine = AlphaBacktestEngine(config)
            engine._build_l2_index(l2_df)

            ready_for_symbol_day = 0
            scored_for_symbol_day = 0
            for _, bar in bars.sort_values("ts").iterrows():
                total_bars += 1
                bar_data = engine._prepare_bar_data(bar, l2_df, bar["ts"])
                if bar_data.features.get("_ml_features_ready") is False:
                    continue
                ml_ready_bars += 1
                ready_for_symbol_day += 1
                probabilities = signal.predict_probabilities(
                    bar_data.features,
                    symbol=str(symbol),
                    timestamp=pd.Timestamp(bar["ts"]),
                )
                if probabilities is None:
                    continue
                scored_for_symbol_day += 1
                p_down, p_flat, p_up = probabilities
                confidence = max(p_up, p_down)
                scored_rows.append(
                    {
                        "date": date,
                        "symbol": symbol,
                        "ts": pd.Timestamp(bar["ts"]),
                        "p_down": p_down,
                        "p_flat": p_flat,
                        "p_up": p_up,
                        "confidence": confidence,
                    }
                )

            coverage_rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "bars_total": int(len(bars)),
                    "ml_ready_bars": ready_for_symbol_day,
                    "scored_bars": scored_for_symbol_day,
                    "ml_ready_ratio": (
                        float(ready_for_symbol_day / len(bars)) if len(bars) else 0.0
                    ),
                    "scored_ratio": (
                        float(scored_for_symbol_day / len(bars)) if len(bars) else 0.0
                    ),
                }
            )

    scored_df = (
        pd.DataFrame(scored_rows)
        .sort_values(["date", "symbol", "ts"])
        .reset_index(drop=True)
    )
    coverage_df = (
        pd.DataFrame(coverage_rows)
        .sort_values(["date", "symbol"])
        .reset_index(drop=True)
    )
    if scored_df.empty:
        overall = {
            "eligible_bars": 0,
            "p_up_p50": 0.0,
            "p_up_p90": 0.0,
            "p_up_p95": 0.0,
            "p_down_p50": 0.0,
            "p_down_p90": 0.0,
            "p_down_p95": 0.0,
            "confidence_p50": 0.0,
            "confidence_p90": 0.0,
            "confidence_p95": 0.0,
            **{f"fraction_ge_{threshold:.2f}": 0.0 for threshold in thresholds},
        }
    else:
        overall = _summarize_group(scored_df, thresholds)

    by_date = []
    if not scored_df.empty:
        for date, group in scored_df.groupby("date", sort=True):
            row = {"date": date, **_summarize_group(group, thresholds)}
            by_date.append(row)
    by_symbol = []
    if not scored_df.empty:
        for (date, symbol), group in scored_df.groupby(["date", "symbol"], sort=True):
            row = {
                "date": date,
                "symbol": symbol,
                **_summarize_group(group, thresholds),
            }
            by_symbol.append(row)

    scored_ratio = float(len(scored_df) / total_bars) if total_bars else 0.0
    summary = {
        "dates": dates,
        "bar_source": args.bar_source,
        "model_path": config["signals"]["ml"]["model_path"],
        "symbols_scanned": int(len(symbols_scanned)),
        "total_bars": int(total_bars),
        "ml_ready_bars": int(ml_ready_bars),
        "scored_bars": int(len(scored_df)),
        "ml_ready_ratio": float(ml_ready_bars / total_bars) if total_bars else 0.0,
        "scored_ratio": scored_ratio,
        "overall": overall,
        "interpretation": (
            "The model is reaching live-ready bars, but confidence remains below practical entry "
            "levels on this date slice."
            if len(scored_df) > 0
            else "No scored bars were available even after ML readiness filtering."
        ),
    }

    coverage_df.to_csv(output_dir / "coverage_by_symbol_day.csv", index=False)
    scored_df.to_csv(output_dir / "bar_level_probabilities.csv", index=False)
    pd.DataFrame(by_date).to_csv(output_dir / "probabilities_by_date.csv", index=False)
    pd.DataFrame(by_symbol).to_csv(
        output_dir / "probabilities_by_symbol_day.csv", index=False
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    _write_report(output_dir, summary, thresholds)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit live ML score distributions")
    parser.add_argument(
        "--dates", type=str, help="Comma-separated YYYY-MM-DD dates to audit"
    )
    parser.add_argument(
        "--split-file",
        type=Path,
        help="training_metrics.json path used to resolve validation or test dates",
    )
    parser.add_argument(
        "--date-split",
        choices=["val_dates", "test_dates", "train_dates"],
        help="Which split to read from --split-file when --dates is omitted",
    )
    parser.add_argument(
        "--bar-source",
        choices=["gold", "polygon"],
        default="polygon",
        help="Minute bar source for the audit",
    )
    parser.add_argument(
        "--model-path",
        type=str,
        help="Optional model artifact override",
    )
    parser.add_argument(
        "--thresholds",
        default="0.35,0.40,0.45,0.50",
        help="Comma-separated confidence thresholds to summarize",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output") / "ml_score_audit",
        help="Directory for audit artifacts",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_score_audit(args)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
