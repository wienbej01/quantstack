#!/usr/bin/env python3
"""Run a cached direct-engine cross-check for one ML policy config."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.run_ml_phase3_matrix import (
    _build_config,
    _load_overlap_data,
    _load_overlap_keys,
)
from src.backtest import AlphaBacktestEngine
from src.backtest.engine import BacktestResult
from src.metrics import compute_all_metrics
from src.signals import MLSignal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)
INITIAL_CAPITAL = 100000.0


def _config_slug(
    threshold: float,
    long_threshold: float,
    short_threshold: float,
    min_probability_gap: float,
    max_flat_probability: float,
    exit_mode: str,
    target_pct: float,
    stop_pct: float,
    time_limit_minutes: int,
) -> str:
    return (
        f"thr{int(round(threshold * 100)):03d}_"
        f"l{int(round(long_threshold * 100)):03d}_"
        f"s{int(round(short_threshold * 100)):03d}_"
        f"gap{int(round(min_probability_gap * 100)):03d}_"
        f"flat{int(round(max_flat_probability * 100)):03d}_"
        f"{exit_mode}_"
        f"tp{int(round(target_pct * 100)):03d}_"
        f"sl{int(round(stop_pct * 100)):03d}_"
        f"tl{int(time_limit_minutes):02d}"
    )


def _cache_overlap_data(
    overlap_path: Path,
    cache_dir: Path,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    overlap_keys = _load_overlap_keys(overlap_path)
    bars_cache = cache_dir / "bars.parquet"
    l2_cache = cache_dir / "l2.parquet"
    keys_cache = cache_dir / "overlap_keys.csv"

    if bars_cache.exists() and l2_cache.exists() and keys_cache.exists():
        logger.info("Loading cached overlap data from %s", cache_dir)
        bars_df = pd.read_parquet(bars_cache)
        l2_df = pd.read_parquet(l2_cache)
        cached_keys = pd.read_csv(keys_cache)
        return cached_keys, bars_df, l2_df

    logger.info("Building overlap cache at %s", cache_dir)
    bars_df, l2_df = _load_overlap_data(overlap_keys)
    bars_df.to_parquet(bars_cache, index=False)
    l2_df.to_parquet(l2_cache, index=False)
    overlap_keys.to_csv(keys_cache, index=False)
    return overlap_keys, bars_df, l2_df


def _window_labels(overlap_keys: pd.DataFrame) -> dict[str, str]:
    dates = pd.to_datetime(sorted(overlap_keys["date"].unique()))
    if len(dates) == 0:
        return {}

    windows: dict[str, str] = {}
    start = dates[0]
    prev = dates[0]
    for current in dates[1:]:
        if (current - prev).days == 1:
            prev = current
            continue
        label = f"{start.strftime('%Y-%m-%d')} to {prev.strftime('%Y-%m-%d')}"
        for date in pd.date_range(start, prev, freq="D"):
            windows[date.strftime("%Y-%m-%d")] = label
        start = current
        prev = current

    label = f"{start.strftime('%Y-%m-%d')} to {prev.strftime('%Y-%m-%d')}"
    for date in pd.date_range(start, prev, freq="D"):
        windows[date.strftime("%Y-%m-%d")] = label
    return windows


def _run_windowed_engine(
    *,
    bars_df: pd.DataFrame,
    l2_df: pd.DataFrame,
    overlap_keys: pd.DataFrame,
    config: dict[str, Any],
) -> tuple[BacktestResult, pd.DataFrame]:
    bars = bars_df.copy()
    bars["date"] = pd.to_datetime(bars["ts"]).dt.strftime("%Y-%m-%d")
    l2 = l2_df.copy()
    l2["date"] = (
        pd.to_datetime(l2["ts_utc"], utc=True)
        .dt.tz_convert("America/New_York")
        .dt.strftime("%Y-%m-%d")
    )
    window_map = _window_labels(overlap_keys)
    ordered_windows = list(
        dict.fromkeys(window_map[date] for date in overlap_keys["date"])
    )

    stitched_trades = []
    stitched_equity_parts: list[pd.Series] = []
    window_rows: list[dict[str, Any]] = []
    running_capital = float(config.get("initial_capital", INITIAL_CAPITAL))

    for window_name in ordered_windows:
        window_dates = [
            date for date, label in window_map.items() if label == window_name
        ]
        window_bars = (
            bars[bars["date"].isin(window_dates)].drop(columns=["date"]).copy()
        )
        window_l2 = l2[l2["date"].isin(window_dates)].drop(columns=["date"]).copy()
        if window_bars.empty:
            continue

        logger.info(
            "Running engine cross-check window %s (%s bars, %s L2 rows)",
            window_name,
            len(window_bars),
            len(window_l2),
        )
        engine = AlphaBacktestEngine(config)
        signal = MLSignal(config)
        window_result = engine.run(window_bars, l2_df=window_l2, signals=[signal])
        window_metrics = compute_all_metrics(
            window_result,
            initial_capital=float(config.get("initial_capital", INITIAL_CAPITAL)),
        )
        window_trade_count = int(window_metrics["num_trades"])
        window_sharpe = (
            float(window_metrics["sharpe_ratio"]) if window_trade_count > 0 else 0.0
        )
        window_rows.append(
            {
                "window": window_name,
                "num_trades": window_trade_count,
                "signals_generated": int(window_result.signals_generated),
                "entries_executed": int(engine.entries_executed),
                "exits_executed": int(engine.exits_executed),
                "sharpe_ratio": window_sharpe,
                "profit_factor": float(window_metrics["profit_factor"]),
                "win_rate": float(window_metrics["win_rate"]),
                "expectancy": float(window_metrics["expectancy"]),
                "total_return_pct": float(window_metrics["total_return_pct"]),
                "avg_hold_minutes": float(window_metrics["avg_hold_minutes"]),
            }
        )
        stitched_trades.extend(window_result.trades)
        if len(window_result.equity_curve) > 0:
            adjusted = (window_result.equity_curve - INITIAL_CAPITAL) + running_capital
            stitched_equity_parts.append(adjusted)
        running_capital += float(window_metrics["total_pnl"])

    combined = BacktestResult()
    combined.trades = stitched_trades
    combined.signals_generated = int(
        sum(row["signals_generated"] for row in window_rows)
    )
    combined.entries_executed = int(sum(row["entries_executed"] for row in window_rows))
    combined.exits_executed = int(sum(row["exits_executed"] for row in window_rows))
    combined.start_date = bars_df["ts"].min().strftime("%Y-%m-%d")
    combined.end_date = bars_df["ts"].max().strftime("%Y-%m-%d")
    combined.symbols_tested = sorted(bars_df["symbol"].unique().tolist())
    if stitched_equity_parts:
        combined.equity_curve = pd.concat(stitched_equity_parts)
        combined.equity_curve = combined.equity_curve[
            ~combined.equity_curve.index.duplicated(keep="last")
        ]
    else:
        combined.equity_curve = pd.Series(dtype=float)
    return combined, pd.DataFrame(window_rows)


def _write_report(
    output_dir: Path,
    summary: dict[str, Any],
    window_df: pd.DataFrame,
) -> Path:
    report_path = output_dir / "report.md"
    lines = [
        "# Phase 4 Engine Cross-Check",
        "",
        "## Config",
        "",
        f"- slug: `{summary['slug']}`",
        f"- threshold: `{summary['confidence_threshold']:.2f}`",
        f"- long threshold: `{summary['long_confidence_threshold']:.2f}`",
        f"- short threshold: `{summary['short_confidence_threshold']:.2f}`",
        f"- probability gap: `{summary['min_probability_gap']:.2f}`",
        f"- max flat probability: `{summary['max_flat_probability']:.2f}`",
        f"- exit mode: `{summary['exit_mode']}`",
        f"- TP: `{summary['target_pct']:.2f}`",
        f"- SL: `{summary['stop_pct']:.2f}`",
        f"- time limit: `{summary['time_limit_minutes']}` min",
        "",
        "## Scope",
        "",
        f"- overlap symbol-days: `{summary['symbol_days']}`",
        f"- bars loaded: `{summary['bars_loaded']}`",
        f"- l2 snapshots loaded: `{summary['l2_loaded']}`",
        "",
        "## Result",
        "",
        f"- trades: `{summary['num_trades']}`",
        f"- signals generated: `{summary['signals_generated']}`",
        f"- entries executed: `{summary['entries_executed']}`",
        f"- exits executed: `{summary['exits_executed']}`",
        f"- sharpe: `{summary['sharpe_ratio']:.2f}`",
        f"- profit factor: `{summary['profit_factor']:.2f}`",
        f"- win rate: `{summary['win_rate']:.1f}%`",
        f"- expectancy: `{summary['expectancy']:.2f}` bp/trade",
        f"- total return: `{summary['total_return_pct']:.3f}%`",
        f"- max drawdown: `{summary['max_drawdown_pct']:.3f}%`",
        f"- avg hold: `{summary['avg_hold_minutes']:.2f}` min",
        "",
    ]
    if not window_df.empty:
        lines.extend(["## Window Breakdown", ""])
        for _, row in window_df.iterrows():
            lines.append(
                f"- `{row['window']}`: trades `{int(row['num_trades'])}`, sharpe "
                f"`{row['sharpe_ratio']:.2f}`, PF `{row['profit_factor']:.2f}`, "
                f"return `{row['total_return_pct']:.3f}%`"
            )
        lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def run_engine_crosscheck(
    *,
    overlap_path: Path,
    cache_dir: Path,
    output_root: Path,
    threshold: float,
    long_threshold: float | None,
    short_threshold: float | None,
    min_probability_gap: float,
    max_flat_probability: float,
    exit_mode: str,
    target_pct: float,
    stop_pct: float,
    time_limit_minutes: int,
) -> dict[str, Any]:
    long_threshold = threshold if long_threshold is None else long_threshold
    short_threshold = threshold if short_threshold is None else short_threshold
    slug = _config_slug(
        threshold=threshold,
        long_threshold=long_threshold,
        short_threshold=short_threshold,
        min_probability_gap=min_probability_gap,
        max_flat_probability=max_flat_probability,
        exit_mode=exit_mode,
        target_pct=target_pct,
        stop_pct=stop_pct,
        time_limit_minutes=time_limit_minutes,
    )
    output_dir = output_root / slug
    output_dir.mkdir(parents=True, exist_ok=True)

    overlap_keys, bars_df, l2_df = _cache_overlap_data(overlap_path, cache_dir)
    config = _build_config(
        threshold=threshold,
        min_probability_gap=min_probability_gap,
        exit_mode=exit_mode,
        tp_pct=target_pct,
        sl_pct=stop_pct,
        time_limit=time_limit_minutes,
    )
    config["signals"]["ml"]["long_confidence_threshold"] = long_threshold
    config["signals"]["ml"]["short_confidence_threshold"] = short_threshold
    config["signals"]["ml"]["max_flat_probability"] = max_flat_probability
    config["max_symbols"] = 0

    logger.info("Running engine cross-check for %s", slug)
    result, window_df = _run_windowed_engine(
        bars_df=bars_df,
        l2_df=l2_df,
        overlap_keys=overlap_keys,
        config=config,
    )
    metrics = compute_all_metrics(result, initial_capital=config["initial_capital"])

    summary = {
        "slug": slug,
        "confidence_threshold": threshold,
        "long_confidence_threshold": long_threshold,
        "short_confidence_threshold": short_threshold,
        "min_probability_gap": min_probability_gap,
        "max_flat_probability": max_flat_probability,
        "exit_mode": exit_mode,
        "target_pct": target_pct,
        "stop_pct": stop_pct,
        "time_limit_minutes": time_limit_minutes,
        "symbol_days": int(len(overlap_keys)),
        "bars_loaded": int(len(bars_df)),
        "l2_loaded": int(len(l2_df)),
        "num_trades": int(metrics["num_trades"]),
        "signals_generated": int(result.signals_generated),
        "entries_executed": int(result.entries_executed),
        "exits_executed": int(result.exits_executed),
        "sharpe_ratio": float(metrics["sharpe_ratio"]),
        "profit_factor": float(metrics["profit_factor"]),
        "win_rate": float(metrics["win_rate"]),
        "expectancy": float(metrics["expectancy"]),
        "total_return_pct": float(metrics["total_return_pct"]),
        "max_drawdown_pct": float(metrics["max_drawdown_pct"]),
        "avg_hold_minutes": float(metrics["avg_hold_minutes"]),
    }

    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    window_df.to_csv(output_dir / "window_metrics.csv", index=False)
    trade_rows = pd.DataFrame(
        [
            {
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
            for trade in result.trades
        ]
    )
    trade_rows.to_csv(output_dir / "trades.csv", index=False)
    _write_report(output_dir, summary, window_df)
    logger.info("Engine cross-check artifacts written to %s", output_dir)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a cached ML engine cross-check")
    parser.add_argument(
        "--overlap-path",
        type=Path,
        default=Path("output/ml_phase1_diagnostics_2026-03-12/overlap_symbol_days.csv"),
        help="Verified overlap symbol-day CSV",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("output/ml_phase4_engine_cache_2026-03-12"),
        help="Directory for cached overlap bars/L2 data",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("output/ml_phase4_engine_crosscheck_2026-03-12"),
        help="Root directory for per-config engine cross-check outputs",
    )
    parser.add_argument("--threshold", type=float, required=True)
    parser.add_argument("--long-threshold", type=float)
    parser.add_argument("--short-threshold", type=float)
    parser.add_argument("--min-probability-gap", type=float, default=0.0)
    parser.add_argument("--max-flat-probability", type=float, default=1.0)
    parser.add_argument(
        "--exit-mode",
        type=str,
        required=True,
        choices=["target_stop_time", "time_only", "target_only_time", "stop_only_time"],
    )
    parser.add_argument("--target-pct", type=float, default=0.0)
    parser.add_argument("--stop-pct", type=float, default=0.0)
    parser.add_argument("--time-limit-minutes", type=int, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_engine_crosscheck(
        overlap_path=args.overlap_path,
        cache_dir=args.cache_dir,
        output_root=args.output_root,
        threshold=args.threshold,
        long_threshold=args.long_threshold,
        short_threshold=args.short_threshold,
        min_probability_gap=args.min_probability_gap,
        max_flat_probability=args.max_flat_probability,
        exit_mode=args.exit_mode,
        target_pct=args.target_pct,
        stop_pct=args.stop_pct,
        time_limit_minutes=args.time_limit_minutes,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
