#!/usr/bin/env python3
"""Run Phase 1 diagnostics for the ML backtest regime.

This inventories exact Gold/L2 overlap, measures causal L2 coverage on bar-aligned
features, and logs model probability / trigger density on the same feature path used
by the backtest engine.
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest import AlphaBacktestEngine
from src.data import GoldLoader, L2Loader
from src.data.ml_compact_cache import compute_event_score
from src.features.ml_features import compute_ml_features
from src.signals import MLSignal

from scripts.run_hypothesis_test import DEFAULT_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


THRESHOLDS = (0.55, 0.50, 0.45)


@dataclass(frozen=True)
class OverlapKey:
    """Single symbol/day overlap unit."""

    date: str
    symbol: str


def _gold_symbol_path(loader: GoldLoader, symbol: str) -> Path:
    return loader.min_1_path / symbol


def _find_overlap_keys(
    gold_loader: GoldLoader,
    l2_loader: L2Loader,
    start_date: str | None,
    end_date: str | None,
) -> list[OverlapKey]:
    available_dates = l2_loader.get_available_dates(source_type="any")
    overlap: list[OverlapKey] = []

    for date in available_dates:
        if start_date and date < start_date:
            continue
        if end_date and date > end_date:
            continue

        for symbol in l2_loader.get_available_symbols(date, source_type="any"):
            try:
                l2_loader._find_data_path(symbol, date, source_type="any")
            except FileNotFoundError:
                continue
            if not _gold_symbol_path(gold_loader, symbol).exists():
                continue
            try:
                bars = gold_loader.load_bars(symbol, date, date)
            except FileNotFoundError:
                continue
            if bars.empty:
                continue
            overlap.append(OverlapKey(date=date, symbol=symbol))

    return overlap


def _date_ranges(dates: list[str]) -> list[str]:
    if not dates:
        return []
    ordered = pd.to_datetime(sorted(set(dates)))
    ranges: list[str] = []
    start = ordered[0]
    prev = ordered[0]

    for current in ordered[1:]:
        if (current - prev).days == 1:
            prev = current
            continue
        ranges.append(f"{start.strftime('%Y-%m-%d')} to {prev.strftime('%Y-%m-%d')}")
        start = current
        prev = current

    ranges.append(f"{start.strftime('%Y-%m-%d')} to {prev.strftime('%Y-%m-%d')}")
    return ranges


def _load_model_signal(config: dict[str, Any]) -> MLSignal:
    return MLSignal(config)


def _score_bar(
    signal: MLSignal,
    feature_view: dict[str, Any],
) -> tuple[float, float, float]:
    x = np.array([[feature_view.get(column, 0.0) for column in signal._feature_cols]])
    x = np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)
    p_down, p_flat, p_up = signal._model.predict_proba(x)[0]
    return float(p_down), float(p_flat), float(p_up)


def _bar_date_string(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def _analyze_overlap_key(
    key: OverlapKey,
    config: dict[str, Any],
    gold_loader: GoldLoader,
    l2_loader: L2Loader,
    signal: MLSignal,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    bars = gold_loader.load_bars(key.symbol, key.date, key.date).copy()
    l2_df = l2_loader.load_snapshots(key.symbol, key.date, source_type="any")

    engine = AlphaBacktestEngine(config)
    engine._build_l2_index(l2_df)
    normalized_l2 = engine._normalize_ml_window(l2_df, symbol=key.symbol, date=key.date)
    featured_l2 = compute_ml_features(normalized_l2)
    featured_l2["event_score"] = compute_event_score(featured_l2)
    featured_l2 = featured_l2.sort_values("ts_utc").reset_index(drop=True)
    featured_ts = featured_l2["ts_utc"].astype("int64").to_numpy()

    if not pd.api.types.is_datetime64_any_dtype(bars["ts"]):
        bars["ts"] = pd.to_datetime(bars["ts"])
    bars = bars.sort_values("ts").reset_index(drop=True)

    valid_bars = 0
    bar_rows: list[dict[str, Any]] = []

    for _, bar in bars.iterrows():
        ts = pd.Timestamp(bar["ts"])
        ts_utc = (
            ts.tz_localize("America/New_York").tz_convert("UTC")
            if ts.tz is None
            else ts.tz_convert("UTC")
        )
        ts_ns = int(ts_utc.value)
        latest_idx = int(np.searchsorted(featured_ts, ts_ns, side="right")) - 1
        if latest_idx < 0:
            continue
        latest_ts_ns = int(featured_ts[latest_idx])
        if ts_ns - latest_ts_ns > engine._l2_staleness_seconds * 1_000_000_000:
            continue
        latest_row = featured_l2.iloc[latest_idx]
        numeric_cols = featured_l2.select_dtypes(include=[np.number, bool]).columns
        feature_view = {column: latest_row[column] for column in numeric_cols}
        p_down, p_flat, p_up = _score_bar(signal, feature_view)
        confidence = max(p_up, p_down)
        side = "long" if p_up >= p_down else "short"
        valid_bars += 1
        bar_rows.append(
            {
                "date": key.date,
                "symbol": key.symbol,
                "ts": ts,
                "p_down": p_down,
                "p_flat": p_flat,
                "p_up": p_up,
                "confidence": confidence,
                "predicted_side": side,
            }
        )

    summary = {
        "date": key.date,
        "symbol": key.symbol,
        "bars_total": int(len(bars)),
        "l2_snapshots": int(len(l2_df)),
        "bars_with_valid_l2": int(valid_bars),
        "valid_bar_ratio": float(valid_bars / len(bars)) if len(bars) else 0.0,
    }
    return summary, bar_rows


def _summarize_probabilities(bar_df: pd.DataFrame) -> dict[str, float]:
    if bar_df.empty:
        return {}
    return {
        "count": int(len(bar_df)),
        "confidence_mean": float(bar_df["confidence"].mean()),
        "confidence_p50": float(bar_df["confidence"].quantile(0.50)),
        "confidence_p90": float(bar_df["confidence"].quantile(0.90)),
        "confidence_p95": float(bar_df["confidence"].quantile(0.95)),
        "p_up_mean": float(bar_df["p_up"].mean()),
        "p_down_mean": float(bar_df["p_down"].mean()),
        "p_flat_mean": float(bar_df["p_flat"].mean()),
        "p_up_max": float(bar_df["p_up"].max()),
        "p_down_max": float(bar_df["p_down"].max()),
    }


def _trigger_summary(bar_df: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    total_bars = int(len(bar_df))
    for threshold in THRESHOLDS:
        long_hits = int(
            ((bar_df["p_up"] > threshold) & (bar_df["p_up"] > bar_df["p_down"])).sum()
        )
        short_hits = int(
            ((bar_df["p_down"] > threshold) & (bar_df["p_down"] > bar_df["p_up"])).sum()
        )
        total_hits = long_hits + short_hits
        rows.append(
            {
                "threshold": threshold,
                "candidate_entries": total_hits,
                "long_entries": long_hits,
                "short_entries": short_hits,
                "entry_rate_on_valid_bars": (
                    float(total_hits / total_bars) if total_bars else 0.0
                ),
            }
        )
    return rows


def _bottleneck_call(
    overlap_df: pd.DataFrame, bar_df: pd.DataFrame
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if overlap_df.empty or bar_df.empty:
        return "data_overlap", ["No overlap bars were available for ML scoring."]

    valid_ratio = float(overlap_df["valid_bar_ratio"].mean())
    overlap_dates = int(overlap_df["date"].nunique())
    trigger_055 = int(
        ((bar_df["p_up"] > 0.55) & (bar_df["p_up"] > bar_df["p_down"])).sum()
        + ((bar_df["p_down"] > 0.55) & (bar_df["p_down"] > bar_df["p_up"])).sum()
    )
    trigger_rate_055 = float(trigger_055 / len(bar_df))

    if overlap_dates <= 2:
        reasons.append(
            f"Only {overlap_dates} overlap date(s) are available in the scanned range."
        )
    if valid_ratio < 0.25:
        reasons.append(
            f"Mean valid-bar ratio is only {valid_ratio:.1%}, so most bars lack a usable causal L2 window."
        )
    if trigger_rate_055 < 0.01:
        reasons.append(
            f"Entry rate at 0.55 is only {trigger_rate_055:.2%} of valid bars, so threshold density is thin."
        )

    if overlap_dates <= 2 or valid_ratio < 0.25:
        return "data_overlap", reasons
    if trigger_rate_055 < 0.01:
        return "trigger_density", reasons
    return "mixed", reasons or [
        "Overlap exists and trigger density is non-zero, but both remain limited."
    ]


def _write_report(
    output_dir: Path,
    overlap_df: pd.DataFrame,
    bar_df: pd.DataFrame,
    trigger_rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> Path:
    report_path = output_dir / "report.md"
    lines = [
        "# Phase 1 ML Overlap Diagnostics",
        "",
        "## Scope",
        "",
        f"- Scan date range: `{summary['date_min']}` to `{summary['date_max']}`",
        f"- Overlap symbol-days: `{summary['symbol_days']}`",
        f"- Distinct overlap dates: `{summary['overlap_dates']}`",
        f"- Distinct overlap symbols: `{summary['overlap_symbols']}`",
        f"- Date windows: `{', '.join(summary['date_windows']) if summary['date_windows'] else 'none'}`",
        "",
        "## Coverage",
        "",
        f"- Gold bars across overlap symbol-days: `{summary['bars_total']}`",
        f"- Bars with valid causal L2 windows: `{summary['bars_with_valid_l2']}`",
        f"- Valid-bar ratio: `{summary['valid_bar_ratio']:.1%}`",
        f"- Mean symbol-day valid-bar ratio: `{summary['mean_symbol_day_valid_ratio']:.1%}`",
        f"- Median symbol-day valid-bar ratio: `{summary['median_symbol_day_valid_ratio']:.1%}`",
        "",
        "## Probability Distribution",
        "",
        f"- Mean confidence: `{summary['probability_summary']['confidence_mean']:.3f}`",
        f"- Confidence p50 / p90 / p95: "
        f"`{summary['probability_summary']['confidence_p50']:.3f}` / "
        f"`{summary['probability_summary']['confidence_p90']:.3f}` / "
        f"`{summary['probability_summary']['confidence_p95']:.3f}`",
        f"- Mean `p_up`: `{summary['probability_summary']['p_up_mean']:.3f}`",
        f"- Mean `p_down`: `{summary['probability_summary']['p_down_mean']:.3f}`",
        f"- Mean `p_flat`: `{summary['probability_summary']['p_flat_mean']:.3f}`",
        f"- Max `p_up`: `{summary['probability_summary']['p_up_max']:.3f}`",
        f"- Max `p_down`: `{summary['probability_summary']['p_down_max']:.3f}`",
        "",
        "## Trigger Density",
        "",
    ]

    for row in trigger_rows:
        lines.append(
            f"- Threshold `{row['threshold']:.2f}`: `{row['candidate_entries']}` entries "
            f"({row['entry_rate_on_valid_bars']:.2%} of valid bars), "
            f"`{row['long_entries']}` long / `{row['short_entries']}` short"
        )

    lines.extend(
        [
            "",
            "## Bottleneck Call",
            "",
            f"- Primary bottleneck: `{summary['bottleneck']}`",
        ]
    )
    for reason in summary["bottleneck_reasons"]:
        lines.append(f"- {reason}")

    lines.extend(
        [
            "",
            "## Highest-coverage Symbol-Days",
            "",
        ]
    )
    if overlap_df.empty:
        lines.append("- none")
    else:
        top_rows = overlap_df.sort_values(
            ["bars_with_valid_l2", "valid_bar_ratio"], ascending=[False, False]
        ).head(10)
        for _, row in top_rows.iterrows():
            lines.append(
                f"- `{row['date']}` `{row['symbol']}`: `{int(row['bars_with_valid_l2'])}` / "
                f"`{int(row['bars_total'])}` valid bars ({row['valid_bar_ratio']:.1%})"
            )

    lines.extend(
        [
            "",
            "## Next Step",
            "",
            summary["next_step"],
            "",
        ]
    )

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def run_phase1_diagnostics(
    start_date: str | None, end_date: str | None, output_dir: Path
) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    gold_loader = GoldLoader()
    l2_loader = L2Loader()
    signal = _load_model_signal(config)

    overlap_keys = _find_overlap_keys(gold_loader, l2_loader, start_date, end_date)
    if not overlap_keys:
        raise RuntimeError(
            "No Gold/L2 overlap symbol-days found in the requested range."
        )

    overlap_rows: list[dict[str, Any]] = []
    bar_rows: list[dict[str, Any]] = []

    for key in overlap_keys:
        logger.info("Analyzing %s %s", key.date, key.symbol)
        try:
            overlap_summary, bar_summary = _analyze_overlap_key(
                key=key,
                config=config,
                gold_loader=gold_loader,
                l2_loader=l2_loader,
                signal=signal,
            )
        except FileNotFoundError as exc:
            logger.warning(
                "Skipping %s %s due to missing L2 data: %s", key.date, key.symbol, exc
            )
            continue
        overlap_rows.append(overlap_summary)
        bar_rows.extend(bar_summary)

    overlap_df = (
        pd.DataFrame(overlap_rows)
        .sort_values(["date", "symbol"])
        .reset_index(drop=True)
    )
    bar_df = pd.DataFrame(bar_rows).sort_values(["ts", "symbol"]).reset_index(drop=True)

    probability_summary = _summarize_probabilities(bar_df)
    trigger_rows = _trigger_summary(bar_df)
    bottleneck, bottleneck_reasons = _bottleneck_call(overlap_df, bar_df)

    date_windows = _date_ranges(overlap_df["date"].tolist())
    summary = {
        "date_min": overlap_df["date"].min(),
        "date_max": overlap_df["date"].max(),
        "symbol_days": int(len(overlap_df)),
        "overlap_dates": int(overlap_df["date"].nunique()),
        "overlap_symbols": int(overlap_df["symbol"].nunique()),
        "date_windows": date_windows,
        "bars_total": int(overlap_df["bars_total"].sum()),
        "bars_with_valid_l2": int(overlap_df["bars_with_valid_l2"].sum()),
        "valid_bar_ratio": (
            float(
                overlap_df["bars_with_valid_l2"].sum() / overlap_df["bars_total"].sum()
            )
            if overlap_df["bars_total"].sum()
            else 0.0
        ),
        "mean_symbol_day_valid_ratio": float(overlap_df["valid_bar_ratio"].mean()),
        "median_symbol_day_valid_ratio": float(overlap_df["valid_bar_ratio"].median()),
        "probability_summary": probability_summary,
        "trigger_summary": trigger_rows,
        "bottleneck": bottleneck,
        "bottleneck_reasons": bottleneck_reasons,
        "next_step": (
            "Restrict Phase 2/3 backtests to the verified overlap windows and inspect "
            "whether lowering the live threshold materially changes candidate density."
            if bottleneck == "data_overlap"
            else "Proceed to threshold calibration on the verified overlap windows."
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    overlap_df.to_csv(output_dir / "overlap_symbol_days.csv", index=False)
    bar_df.to_csv(output_dir / "bar_level_probabilities.csv", index=False)
    pd.DataFrame(trigger_rows).to_csv(output_dir / "trigger_summary.csv", index=False)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    report_path = _write_report(output_dir, overlap_df, bar_df, trigger_rows, summary)
    logger.info("Phase 1 report written to %s", report_path)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ML Phase 1 overlap diagnostics")
    parser.add_argument("--start", type=str, help="Optional start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, help="Optional end date YYYY-MM-DD")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output") / "ml_phase1_diagnostics_2026-03-12",
        help="Directory for reports and CSV outputs",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_phase1_diagnostics(
        start_date=args.start,
        end_date=args.end,
        output_dir=args.output_dir,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
