#!/usr/bin/env python3
"""Diagnose why live execution underperforms the compact ML payoff scan."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.run_hypothesis_test import DEFAULT_CONFIG
from scripts.run_ml_phase3_matrix import (
    _build_config,
    _build_scored_bars,
    _load_overlap_keys,
    _simulate_from_scored_bars,
)
from src.backtest.engine import BacktestResult
from src.signals import MLSignal

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

COMMISSION_BPS = 1.0
TIME_ONLY_TARGET_STOP_PCT = 99.0
ONE_BAR_HOLD_MINUTES = 1
CONFIDENCE_BUCKETS = (0.45, 0.50, 0.55, 0.60, 0.70, 1.01)


@dataclass(frozen=True)
class AnalysisConfig:
    """Execution template to diagnose."""

    name: str
    threshold: float
    target_pct: float
    stop_pct: float
    time_limit_minutes: int


CONFIGS = (
    AnalysisConfig(
        name="compact_template",
        threshold=0.55,
        target_pct=0.40,
        stop_pct=0.10,
        time_limit_minutes=5,
    ),
    AnalysisConfig(
        name="live_best",
        threshold=0.45,
        target_pct=0.40,
        stop_pct=0.20,
        time_limit_minutes=8,
    ),
)


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


def _prepare_bars(
    scored_bars: pd.DataFrame, window_map: dict[str, str]
) -> pd.DataFrame:
    bars = scored_bars.copy()
    bars["ts"] = pd.to_datetime(bars["ts"])
    bars["date"] = bars["ts"].dt.strftime("%Y-%m-%d")
    bars["window"] = bars["date"].map(window_map).fillna(bars["date"])
    bars = bars.sort_values(["symbol", "ts"]).reset_index(drop=True)

    grouped = bars.groupby("symbol", sort=False)
    bars["next_ts"] = grouped["ts"].shift(-1)
    bars["next_open"] = grouped["open"].shift(-1)
    bars["next_close"] = grouped["close"].shift(-1)
    bars["next_date"] = grouped["date"].shift(-1)
    bars["next_window"] = grouped["window"].shift(-1)
    return bars


def _candidate_signals(prepared_bars: pd.DataFrame, signal: MLSignal) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for _, row in prepared_bars.iterrows():
        if (
            pd.isna(row["next_ts"])
            or pd.isna(row["p_up"])
            or pd.isna(row["p_down"])
            or pd.isna(row["p_flat"])
        ):
            continue
        event = signal.entry_event_from_probabilities(
            symbol=str(row["symbol"]),
            timestamp=pd.Timestamp(row["ts"]),
            p_down=float(row["p_down"]),
            p_flat=float(row["p_flat"]),
            p_up=float(row["p_up"]),
        )
        if event is None:
            continue
        side_mult = 1.0 if event.side.value == "long" else -1.0
        rows.append(
            {
                "symbol": row["symbol"],
                "analysis_date": row["date"],
                "window": row["window"],
                "signal_ts": row["ts"],
                "entry_ts": row["next_ts"],
                "side": event.side.value,
                "confidence": event.confidence,
                "signal_close": row["close"],
                "entry_open": row["next_open"],
                "horizon_close": row["next_close"],
                "signal_close_to_next_close_bps": side_mult
                * (row["next_close"] - row["close"])
                / row["close"]
                * 10000,
                "signal_close_to_entry_open_bps": side_mult
                * (row["next_open"] - row["close"])
                / row["close"]
                * 10000,
                "entry_open_to_next_close_bps": side_mult
                * (row["next_close"] - row["next_open"])
                / row["next_open"]
                * 10000,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "symbol",
                "analysis_date",
                "signal_window",
                "signal_ts",
                "entry_ts",
                "side",
                "confidence",
                "signal_close",
                "entry_open",
                "horizon_close",
                "signal_close_to_next_close_bps",
                "signal_close_to_entry_open_bps",
                "entry_open_to_next_close_bps",
            ]
        )

    candidates = pd.DataFrame(rows)
    return candidates.rename(
        columns={
            "window": "signal_window",
        }
    )


def _clip_bps(values_bps: pd.Series, target_pct: float, stop_pct: float) -> pd.Series:
    tp_bps = float(target_pct) * 100.0
    sl_bps = float(stop_pct) * 100.0
    return values_bps.clip(lower=-sl_bps, upper=tp_bps)


def _profit_factor(pnl_bps: pd.Series) -> float:
    wins = pnl_bps[pnl_bps > 0]
    losses = pnl_bps[pnl_bps < 0]
    if losses.empty:
        return 999.0 if not wins.empty else 0.0
    return float(wins.sum() / abs(losses.sum()))


def _trade_level_metrics(pnl_bps: pd.Series) -> dict[str, float]:
    if pnl_bps.empty:
        return {
            "num_trades": 0,
            "total_pnl_bps": 0.0,
            "avg_pnl_bps": 0.0,
            "median_pnl_bps": 0.0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
        }
    return {
        "num_trades": int(len(pnl_bps)),
        "total_pnl_bps": float(pnl_bps.sum()),
        "avg_pnl_bps": float(pnl_bps.mean()),
        "median_pnl_bps": float(pnl_bps.median()),
        "win_rate": float((pnl_bps > 0).mean()),
        "profit_factor": _profit_factor(pnl_bps),
    }


def _compact_ideal_from_candidates(
    candidates: pd.DataFrame,
    config: AnalysisConfig,
) -> tuple[pd.DataFrame, dict[str, float]]:
    ideal = candidates.copy()
    ideal["scenario"] = "compact_ideal"
    ideal["config_name"] = config.name
    ideal["pnl_bps"] = (
        _clip_bps(
            ideal["signal_close_to_next_close_bps"],
            target_pct=config.target_pct,
            stop_pct=config.stop_pct,
        )
        - COMMISSION_BPS
    )
    return ideal, _trade_level_metrics(ideal["pnl_bps"])


def _trades_to_frame(
    result: BacktestResult,
    config: AnalysisConfig,
    scenario: str,
    candidates: pd.DataFrame,
    window_map: dict[str, str],
) -> tuple[pd.DataFrame, dict[str, float]]:
    trade_rows = [
        {
            "symbol": trade.symbol,
            "side": trade.side.value,
            "entry_time": trade.entry_time,
            "exit_time": trade.exit_time,
            "exit_reason": trade.exit_reason,
            "pnl": trade.pnl,
            "pnl_pct": trade.pnl_pct,
            "pnl_bps": trade.pnl_pct * 100.0,
            "hold_minutes": trade.hold_minutes,
        }
        for trade in result.trades
    ]
    trade_df = pd.DataFrame(trade_rows)
    if trade_df.empty:
        trade_df = pd.DataFrame(
            columns=[
                "symbol",
                "side",
                "entry_time",
                "exit_time",
                "exit_reason",
                "pnl",
                "pnl_pct",
                "pnl_bps",
                "hold_minutes",
            ]
        )
    else:
        trade_df["entry_time"] = pd.to_datetime(trade_df["entry_time"])
        trade_df["exit_time"] = pd.to_datetime(trade_df["exit_time"])

    join_cols = [
        "symbol",
        "side",
        "entry_ts",
        "signal_ts",
        "analysis_date",
        "signal_window",
        "confidence",
        "signal_close",
        "entry_open",
        "horizon_close",
        "signal_close_to_next_close_bps",
        "signal_close_to_entry_open_bps",
        "entry_open_to_next_close_bps",
    ]
    enriched = trade_df.merge(
        candidates[join_cols],
        left_on=["symbol", "side", "entry_time"],
        right_on=["symbol", "side", "entry_ts"],
        how="left",
    )
    if not enriched.empty:
        enriched["entry_date"] = enriched["entry_time"].dt.strftime("%Y-%m-%d")
        enriched["exit_date"] = enriched["exit_time"].dt.strftime("%Y-%m-%d")
        enriched["entry_window"] = (
            enriched["entry_date"].map(window_map).fillna(enriched["entry_date"])
        )
        enriched["exit_window"] = (
            enriched["exit_date"].map(window_map).fillna(enriched["exit_date"])
        )
    else:
        enriched["entry_date"] = pd.Series(dtype="object")
        enriched["exit_date"] = pd.Series(dtype="object")
        enriched["entry_window"] = pd.Series(dtype="object")
        enriched["exit_window"] = pd.Series(dtype="object")

    enriched["scenario"] = scenario
    enriched["config_name"] = config.name
    return enriched, _trade_level_metrics(enriched["pnl_bps"])


def _simulate_live_variants(
    scored_bars: pd.DataFrame,
    config: AnalysisConfig,
    candidates: pd.DataFrame,
    window_map: dict[str, str],
) -> tuple[list[dict[str, float]], pd.DataFrame]:
    scenario_rows: list[dict[str, float]] = []
    trade_frames: list[pd.DataFrame] = []

    scenario_specs = [
        (
            "one_bar_hold",
            _build_config(
                threshold=config.threshold,
                tp_pct=TIME_ONLY_TARGET_STOP_PCT,
                sl_pct=TIME_ONLY_TARGET_STOP_PCT,
                time_limit=ONE_BAR_HOLD_MINUTES,
            ),
        ),
        (
            "time_only",
            _build_config(
                threshold=config.threshold,
                tp_pct=TIME_ONLY_TARGET_STOP_PCT,
                sl_pct=TIME_ONLY_TARGET_STOP_PCT,
                time_limit=config.time_limit_minutes,
            ),
        ),
        (
            "full_live",
            _build_config(
                threshold=config.threshold,
                tp_pct=config.target_pct,
                sl_pct=config.stop_pct,
                time_limit=config.time_limit_minutes,
            ),
        ),
    ]

    for scenario_name, scenario_config in scenario_specs:
        logger.info("Running %s scenario for %s", scenario_name, config.name)
        signal = scenario_config["signals"]["ml"]
        result = _simulate_from_scored_bars(
            scored_bars=scored_bars,
            config=scenario_config,
            signal=MLSignal(scenario_config),
        )
        trade_df, metrics = _trades_to_frame(
            result=result,
            config=config,
            scenario=scenario_name,
            candidates=candidates,
            window_map=window_map,
        )
        trade_frames.append(trade_df)
        scenario_rows.append(
            {
                "config_name": config.name,
                "scenario": scenario_name,
                "confidence_threshold": config.threshold,
                "target_pct": signal["target_pct"],
                "stop_pct": signal["stop_pct"],
                "time_limit_minutes": signal["time_limit_minutes"],
                **metrics,
            }
        )

    return scenario_rows, pd.concat(trade_frames, ignore_index=True)


def _aggregate(
    df: pd.DataFrame,
    group_col: str,
    pnl_col: str,
    confidence_col: str = "confidence",
) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    grouped = df.groupby(group_col, dropna=False, observed=False)
    summary = grouped.agg(
        trades=(pnl_col, "size"),
        total_pnl_bps=(pnl_col, "sum"),
        avg_pnl_bps=(pnl_col, "mean"),
        median_pnl_bps=(pnl_col, "median"),
        win_rate=(pnl_col, lambda s: float((s > 0).mean())),
        avg_confidence=(confidence_col, "mean"),
    )
    summary["profit_factor"] = grouped[pnl_col].apply(_profit_factor)
    return summary.reset_index().sort_values("total_pnl_bps")


def _confidence_bucket_summary(df: pd.DataFrame, pnl_col: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    bucket_labels = [
        "0.45-0.50",
        "0.50-0.55",
        "0.55-0.60",
        "0.60-0.70",
        "0.70+",
    ]
    bucketed = df.copy()
    bucketed["confidence_bucket"] = pd.cut(
        bucketed["confidence"],
        bins=CONFIDENCE_BUCKETS,
        labels=bucket_labels,
        include_lowest=True,
        right=False,
    )
    return _aggregate(
        bucketed.dropna(subset=["confidence_bucket"]), "confidence_bucket", pnl_col
    )


def _root_cause_calls(
    scenario_df: pd.DataFrame,
    live_trades: pd.DataFrame,
    compact_ideal: pd.DataFrame,
) -> list[str]:
    calls: list[str] = []

    compact_rows = scenario_df[scenario_df["scenario"] == "compact_ideal"].set_index(
        "config_name"
    )
    one_bar_rows = scenario_df[scenario_df["scenario"] == "one_bar_hold"].set_index(
        "config_name"
    )
    time_only_rows = scenario_df[scenario_df["scenario"] == "time_only"].set_index(
        "config_name"
    )
    full_live_rows = scenario_df[scenario_df["scenario"] == "full_live"].set_index(
        "config_name"
    )

    for config_name in compact_rows.index:
        ideal_avg = float(compact_rows.loc[config_name, "avg_pnl_bps"])
        one_bar_avg = float(one_bar_rows.loc[config_name, "avg_pnl_bps"])
        time_only_avg = float(time_only_rows.loc[config_name, "avg_pnl_bps"])
        full_live_avg = float(full_live_rows.loc[config_name, "avg_pnl_bps"])

        if ideal_avg > 0 and one_bar_avg < 0:
            calls.append(
                f"{config_name}: positive close-to-close edge flips negative after next-open entry, "
                "so entry timing/adverse selection is a primary loss source."
            )
        elif ideal_avg <= 0:
            calls.append(
                f"{config_name}: even the overlap-only compact ideal payoff is non-positive, so this "
                "window set does not preserve the broader compact-scan edge."
            )

        if time_only_avg > full_live_avg + 0.5:
            calls.append(
                f"{config_name}: removing TP/SL improves avg trade PnL materially, so bar-path exit "
                "logic is likely too punitive."
            )
        else:
            calls.append(
                f"{config_name}: time-only exits do not repair PnL, so the dominant issue is signal "
                "quality after executable entry rather than target/stop tuning alone."
            )

    if not live_trades.empty:
        symbol_losses = live_trades.groupby("symbol")["pnl_bps"].sum()
        negative_losses = symbol_losses[symbol_losses < 0].abs()
        top_loss_share = (
            float(
                negative_losses.sort_values(ascending=False).head(3).sum()
                / negative_losses.sum()
            )
            if not negative_losses.empty and float(negative_losses.sum()) > 0
            else 0.0
        )
        if top_loss_share > 0.5:
            calls.append(
                "Losses are concentrated in a small symbol subset, so symbol-level gating or "
                "universe filtering is worth testing before broader redesign."
            )

        side_perf = live_trades.groupby("side")["pnl_bps"].mean()
        if len(side_perf) == 2:
            worst_side = side_perf.idxmin()
            best_side = side_perf.idxmax()
            if side_perf[worst_side] + 2.0 < side_perf[best_side]:
                calls.append(
                    f"{worst_side} entries underperform {best_side} materially, so side-specific "
                    "thresholding or one-sided deployment should be considered."
                )

        confidence_perf = compact_ideal.groupby(
            pd.cut(
                compact_ideal["confidence"],
                bins=CONFIDENCE_BUCKETS,
                include_lowest=True,
                right=False,
            ),
            observed=False,
        )["pnl_bps"].mean()
        if confidence_perf.notna().is_monotonic_increasing is False:
            calls.append(
                "Higher model confidence is not producing monotonic trade quality on the overlap set, "
                "which points to calibration/regime mismatch rather than a simple threshold problem."
            )

    return calls


def _write_report(
    output_dir: Path,
    summary: dict[str, Any],
    scenario_df: pd.DataFrame,
    window_df: pd.DataFrame,
    symbol_df: pd.DataFrame,
    side_df: pd.DataFrame,
    exit_df: pd.DataFrame,
    confidence_df: pd.DataFrame,
) -> Path:
    report_path = output_dir / "report.md"
    lines = [
        "# Phase 3 Root-Cause Diagnostics",
        "",
        "## Scope",
        "",
        f"- Verified overlap symbol-days: `{summary['symbol_days']}`",
        f"- Verified overlap windows: `{', '.join(summary['windows'])}`",
        f"- Bars scored: `{summary['bars_scored']}`",
        f"- Candidate signals analyzed: `{summary['candidate_signals']}`",
        f"- Model path: `{summary['model_path']}`",
        "",
        "## Scenario Comparison",
        "",
    ]

    for _, row in scenario_df.iterrows():
        lines.append(
            f"- `{row['config_name']}` / `{row['scenario']}`: trades `{int(row['num_trades'])}`, "
            f"avg `{row['avg_pnl_bps']:+.2f}` bp, total `{row['total_pnl_bps']:+.1f}` bp, "
            f"WR `{row['win_rate']:.1%}`, PF `{row['profit_factor']:.2f}`"
        )

    lines.extend(["", "## Root Cause Calls", ""])
    for call in summary["root_cause_calls"]:
        lines.append(f"- {call}")

    lines.extend(["", "## Worst Windows", ""])
    for _, row in window_df.head(5).iterrows():
        lines.append(
            f"- `{row['entry_window']}`: trades `{int(row['trades'])}`, avg "
            f"`{row['avg_pnl_bps']:+.2f}` bp, total `{row['total_pnl_bps']:+.1f}` bp, "
            f"WR `{row['win_rate']:.1%}`"
        )

    lines.extend(["", "## Worst Symbols", ""])
    for _, row in symbol_df.head(10).iterrows():
        lines.append(
            f"- `{row['symbol']}`: trades `{int(row['trades'])}`, avg "
            f"`{row['avg_pnl_bps']:+.2f}` bp, total `{row['total_pnl_bps']:+.1f}` bp, "
            f"WR `{row['win_rate']:.1%}`"
        )

    lines.extend(["", "## Side / Exit Mix", ""])
    for _, row in side_df.iterrows():
        lines.append(
            f"- side `{row['side']}`: trades `{int(row['trades'])}`, avg "
            f"`{row['avg_pnl_bps']:+.2f}` bp, total `{row['total_pnl_bps']:+.1f}` bp, "
            f"WR `{row['win_rate']:.1%}`"
        )
    for _, row in exit_df.iterrows():
        lines.append(
            f"- exit `{row['exit_reason']}`: trades `{int(row['trades'])}`, avg "
            f"`{row['avg_pnl_bps']:+.2f}` bp, total `{row['total_pnl_bps']:+.1f}` bp, "
            f"WR `{row['win_rate']:.1%}`"
        )

    lines.extend(["", "## Confidence Buckets", ""])
    for _, row in confidence_df.iterrows():
        lines.append(
            f"- `{row['confidence_bucket']}`: trades `{int(row['trades'])}`, avg "
            f"`{row['avg_pnl_bps']:+.2f}` bp, total `{row['total_pnl_bps']:+.1f}` bp, "
            f"WR `{row['win_rate']:.1%}`"
        )

    lines.extend(["", "## Next Step", "", summary["next_step"], ""])
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def run_root_cause_diagnostics(overlap_path: Path, output_dir: Path) -> dict[str, Any]:
    overlap_keys = _load_overlap_keys(overlap_path)
    scored_bars, _ = _build_scored_bars(overlap_keys, DEFAULT_CONFIG.copy())
    window_map = _window_labels(overlap_keys)
    prepared_bars = _prepare_bars(scored_bars, window_map)

    scenario_rows: list[dict[str, float]] = []
    live_trade_frames: list[pd.DataFrame] = []
    compact_frames: list[pd.DataFrame] = []

    for config in CONFIGS:
        config_dict = _build_config(
            threshold=config.threshold,
            min_probability_gap=0.0,
            exit_mode="target_stop_time",
            tp_pct=config.target_pct,
            sl_pct=config.stop_pct,
            time_limit=config.time_limit_minutes,
        )
        signal = MLSignal(config_dict)
        candidates = _candidate_signals(prepared_bars, signal)
        compact_df, compact_metrics = _compact_ideal_from_candidates(candidates, config)
        compact_frames.append(compact_df)
        scenario_rows.append(
            {
                "config_name": config.name,
                "scenario": "compact_ideal",
                "confidence_threshold": config.threshold,
                "target_pct": config.target_pct,
                "stop_pct": config.stop_pct,
                "time_limit_minutes": config.time_limit_minutes,
                **compact_metrics,
            }
        )
        live_rows, live_trades = _simulate_live_variants(
            scored_bars=scored_bars,
            config=config,
            candidates=candidates,
            window_map=window_map,
        )
        scenario_rows.extend(live_rows)
        live_trade_frames.append(live_trades)

    scenario_df = (
        pd.DataFrame(scenario_rows)
        .sort_values(["config_name", "scenario"])
        .reset_index(drop=True)
    )
    live_trade_df = pd.concat(live_trade_frames, ignore_index=True)
    compact_df = pd.concat(compact_frames, ignore_index=True)

    live_best_trades = live_trade_df[
        (live_trade_df["config_name"] == "live_best")
        & (live_trade_df["scenario"] == "full_live")
    ].copy()
    live_best_windows = _aggregate(live_best_trades, "entry_window", "pnl_bps")
    live_best_symbols = _aggregate(live_best_trades, "symbol", "pnl_bps")
    live_best_sides = _aggregate(live_best_trades, "side", "pnl_bps").sort_values(
        "side"
    )
    live_best_exits = _aggregate(live_best_trades, "exit_reason", "pnl_bps")
    compact_live_best = compact_df[compact_df["config_name"] == "live_best"].copy()
    confidence_df = _confidence_bucket_summary(compact_live_best, "pnl_bps")

    summary = {
        "symbol_days": int(len(overlap_keys)),
        "windows": sorted(set(window_map.values())),
        "bars_scored": int(len(scored_bars)),
        "candidate_signals": int(len(compact_live_best)),
        "model_path": DEFAULT_CONFIG["signals"]["ml"]["model_path"],
    }
    summary["root_cause_calls"] = _root_cause_calls(
        scenario_df=scenario_df,
        live_trades=live_best_trades,
        compact_ideal=compact_live_best,
    )
    summary["next_step"] = (
        "Do not widen the TP/SL grid. First validate whether entry lag is the dominant leak by "
        "testing delayed-entry filters or side-specific deployment, then rerun a narrow live "
        "matrix on the surviving windows/symbols."
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    scenario_df.to_csv(output_dir / "scenario_comparison.csv", index=False)
    compact_df.to_csv(output_dir / "compact_signal_attribution.csv", index=False)
    live_trade_df.to_csv(output_dir / "live_trade_attribution.csv", index=False)
    live_best_windows.to_csv(output_dir / "live_best_by_window.csv", index=False)
    live_best_symbols.to_csv(output_dir / "live_best_by_symbol.csv", index=False)
    live_best_sides.to_csv(output_dir / "live_best_by_side.csv", index=False)
    live_best_exits.to_csv(output_dir / "live_best_by_exit_reason.csv", index=False)
    confidence_df.to_csv(
        output_dir / "live_best_compact_by_confidence.csv", index=False
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    report_path = _write_report(
        output_dir=output_dir,
        summary=summary,
        scenario_df=scenario_df,
        window_df=live_best_windows,
        symbol_df=live_best_symbols,
        side_df=live_best_sides,
        exit_df=live_best_exits,
        confidence_df=confidence_df,
    )
    logger.info("Phase 3 root-cause report written to %s", report_path)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ML Phase 3 root-cause diagnostics"
    )
    parser.add_argument(
        "--overlap-path",
        type=Path,
        default=Path("output/ml_phase1_diagnostics_2026-03-12/overlap_symbol_days.csv"),
        help="Verified overlap symbol-day CSV",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/ml_phase3_root_cause_2026-03-12"),
        help="Directory for diagnostic artifacts",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_root_cause_diagnostics(args.overlap_path, args.output_dir)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
