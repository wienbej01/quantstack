#!/usr/bin/env python3
"""Run Phase 3 ML live-threshold calibration on verified overlap windows."""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest import AlphaBacktestEngine
from src.backtest.engine import BacktestResult, Trade
from src.data import GoldLoader, L2Loader
from src.features.ml_features import compute_ml_features
from src.metrics import compute_all_metrics
from src.signals.base import ExitEvent, SignalEvent, SignalSide
from src.signals import MLSignal

from scripts.run_hypothesis_test import DEFAULT_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


THRESHOLDS = (0.45, 0.50, 0.55)
ENTRY_GAPS = (0.00, 0.05, 0.10)
EXIT_MODES = ("target_stop_time", "time_only", "target_only_time", "stop_only_time")
TP_PCTS = (0.25, 0.30, 0.40)
SL_PCTS = (0.10, 0.15, 0.20)
TIME_LIMITS = (3, 5, 8, 12)


def _load_overlap_keys(path: Path) -> pd.DataFrame:
    overlap_df = pd.read_csv(path)
    required = {"date", "symbol"}
    missing = required - set(overlap_df.columns)
    if missing:
        raise ValueError(f"Overlap file missing columns: {sorted(missing)}")
    return (
        overlap_df[["date", "symbol"]].drop_duplicates().sort_values(["date", "symbol"])
    )


def _load_overlap_data(overlap_keys: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    gold_loader = GoldLoader()
    l2_loader = L2Loader()
    bars_frames: list[pd.DataFrame] = []
    l2_frames: list[pd.DataFrame] = []

    for _, row in overlap_keys.iterrows():
        date = str(row["date"])
        symbol = str(row["symbol"])
        logger.info("Loading overlap data for %s %s", date, symbol)
        bars = gold_loader.load_bars(symbol, date, date).copy()
        if bars.empty:
            continue
        bars["symbol"] = symbol
        bars_frames.append(bars)

        l2_df = l2_loader.load_snapshots(symbol, date, source_type="any").copy()
        l2_df["symbol"] = symbol
        l2_frames.append(l2_df)

    if not bars_frames or not l2_frames:
        raise RuntimeError("No overlap bars/L2 data available for Phase 3.")

    bars_df = (
        pd.concat(bars_frames, ignore_index=True)
        .sort_values(["ts", "symbol"])
        .reset_index(drop=True)
    )
    l2_df = (
        pd.concat(l2_frames, ignore_index=True)
        .sort_values(["ts_utc", "symbol"])
        .reset_index(drop=True)
    )
    return bars_df, l2_df


def _build_scored_bars(
    overlap_keys: pd.DataFrame, config: dict[str, Any]
) -> tuple[pd.DataFrame, int]:
    gold_loader = GoldLoader()
    l2_loader = L2Loader()
    engine = AlphaBacktestEngine(config)
    signal = MLSignal(config)
    scored_frames: list[pd.DataFrame] = []
    total_l2_rows = 0

    for _, row in overlap_keys.iterrows():
        date = str(row["date"])
        symbol = str(row["symbol"])
        logger.info("Scoring overlap bars for %s %s", date, symbol)
        bars = gold_loader.load_bars(symbol, date, date).copy()
        if bars.empty:
            continue
        bars["symbol"] = symbol
        bars = bars.sort_values("ts").reset_index(drop=True)

        l2_df = l2_loader.load_snapshots(symbol, date, source_type="any")
        total_l2_rows += len(l2_df)
        engine._build_l2_index(l2_df)
        normalized = engine._normalize_ml_window(l2_df, symbol=symbol, date=date)
        featured = (
            compute_ml_features(normalized).sort_values("ts_utc").reset_index(drop=True)
        )
        featured_ts = featured["ts_utc"].astype("int64").to_numpy()

        bar_ts = pd.to_datetime(bars["ts"])
        bar_ts_utc = (
            bar_ts.dt.tz_localize("America/New_York").dt.tz_convert("UTC")
            if bar_ts.dt.tz is None
            else bar_ts.dt.tz_convert("UTC")
        )
        bar_ts_ns = bar_ts_utc.astype("int64").to_numpy()
        latest_idx = np.searchsorted(featured_ts, bar_ts_ns, side="right") - 1
        valid = latest_idx >= 0
        valid_indices = np.where(valid)[0]
        if valid_indices.size > 0:
            latest_ns = featured_ts[latest_idx[valid_indices]]
            age_ok = (
                bar_ts_ns[valid_indices] - latest_ns
            ) <= engine._l2_staleness_seconds * 1_000_000_000
            valid[valid_indices] = age_ok

        scored = bars.copy()
        scored["p_down"] = np.nan
        scored["p_flat"] = np.nan
        scored["p_up"] = np.nan

        valid_positions = np.where(valid)[0]
        if valid_positions.size > 0:
            X = np.nan_to_num(
                featured.iloc[latest_idx[valid_positions]][
                    signal._feature_cols
                ].to_numpy(
                    dtype=np.float32,
                    copy=True,
                ),
                nan=0.0,
                posinf=0.0,
                neginf=0.0,
            )
            probs = signal._model.predict_proba(X)
            scored.loc[valid_positions, "p_down"] = probs[:, 0]
            scored.loc[valid_positions, "p_flat"] = probs[:, 1]
            scored.loc[valid_positions, "p_up"] = probs[:, 2]

        scored_frames.append(scored)

    if not scored_frames:
        raise RuntimeError("No scored bars available for Phase 3.")

    scored_bars = (
        pd.concat(scored_frames, ignore_index=True)
        .sort_values(["ts", "symbol"])
        .reset_index(drop=True)
    )
    return scored_bars, total_l2_rows


def _window_strings(overlap_keys: pd.DataFrame) -> list[str]:
    dates = pd.to_datetime(sorted(overlap_keys["date"].unique()))
    if len(dates) == 0:
        return []

    windows: list[str] = []
    start = dates[0]
    prev = dates[0]
    for current in dates[1:]:
        if (current - prev).days == 1:
            prev = current
            continue
        windows.append(f"{start.strftime('%Y-%m-%d')} to {prev.strftime('%Y-%m-%d')}")
        start = current
        prev = current
    windows.append(f"{start.strftime('%Y-%m-%d')} to {prev.strftime('%Y-%m-%d')}")
    return windows


def _build_config(
    threshold: float,
    min_probability_gap: float,
    exit_mode: str,
    tp_pct: float,
    sl_pct: float,
    time_limit: int,
) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    ml_cfg = config["signals"]["ml"]
    ml_cfg["confidence_threshold"] = threshold
    ml_cfg["long_confidence_threshold"] = threshold
    ml_cfg["short_confidence_threshold"] = threshold
    ml_cfg["min_probability_gap"] = min_probability_gap
    ml_cfg["target_pct"] = tp_pct
    ml_cfg["stop_pct"] = sl_pct
    ml_cfg["time_limit_minutes"] = time_limit
    ml_cfg["exit_mode"] = exit_mode
    return config


def _run_one_config(
    scored_bars: pd.DataFrame,
    threshold: float,
    min_probability_gap: float,
    exit_mode: str,
    tp_pct: float,
    sl_pct: float,
    time_limit: int,
) -> dict[str, Any]:
    config = _build_config(
        threshold,
        min_probability_gap,
        exit_mode,
        tp_pct,
        sl_pct,
        time_limit,
    )
    signal = MLSignal(config)
    result = _simulate_from_scored_bars(scored_bars, config, signal)
    metrics = compute_all_metrics(result, initial_capital=config["initial_capital"])
    return {
        "confidence_threshold": threshold,
        "min_probability_gap": min_probability_gap,
        "exit_mode": exit_mode,
        "target_pct": tp_pct,
        "stop_pct": sl_pct,
        "time_limit_minutes": time_limit,
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


def _simulate_from_scored_bars(
    scored_bars: pd.DataFrame,
    config: dict[str, Any],
    signal: MLSignal,
) -> BacktestResult:
    engine = AlphaBacktestEngine(config)
    result = BacktestResult()
    result.start_date = scored_bars["ts"].min().strftime("%Y-%m-%d")
    result.end_date = scored_bars["ts"].max().strftime("%Y-%m-%d")
    result.symbols_tested = sorted(scored_bars["symbol"].unique().tolist())

    capital = config["initial_capital"]
    positions: dict[str, Any] = {}
    pending_entries: list[SignalEvent] = []
    pending_exits: list[ExitEvent] = []
    slippage_bps = config["execution"]["slippage_bps"] / 10000
    commission_per_share = config["execution"]["commission_per_share"]
    position_size_pct = config["risk"]["max_position_pct"]
    max_positions = config["risk"]["max_positions"]

    equity_values = [capital]
    equity_timestamps = [scored_bars["ts"].iloc[0]]
    bars_by_ts = scored_bars.groupby("ts", sort=True)

    for ts, group in bars_by_ts:
        # Execute pending entries at this bar open.
        entries_to_execute = pending_entries.copy()
        pending_entries.clear()
        for event in entries_to_execute:
            symbol_bar = group[group["symbol"] == event.symbol]
            if symbol_bar.empty:
                continue
            if len(positions) >= max_positions:
                continue
            bar = symbol_bar.iloc[0]
            entry_price = bar["open"] * (
                1 + slippage_bps if event.side == SignalSide.LONG else 1 - slippage_bps
            )
            quantity = int((capital * position_size_pct) / entry_price)
            if quantity <= 0:
                continue
            positions[event.symbol] = signal.create_position(
                event, entry_price, bar["ts"], quantity
            )
            result.entries_executed += 1

        # Execute pending exits at this bar open.
        exits_to_execute = pending_exits.copy()
        pending_exits.clear()
        for exit_event in exits_to_execute:
            symbol = exit_event.symbol
            if symbol not in positions:
                continue
            symbol_bar = group[group["symbol"] == symbol]
            if symbol_bar.empty:
                continue
            bar = symbol_bar.iloc[0]
            position = positions[symbol]
            exit_price = (
                bar["open"] * (1 - slippage_bps)
                if position.side == SignalSide.LONG
                else bar["open"] * (1 + slippage_bps)
            )
            pnl = (
                (exit_price - position.entry_price) * position.quantity
                if position.side == SignalSide.LONG
                else (position.entry_price - exit_price) * position.quantity
            )
            pnl -= commission_per_share * position.quantity * 2
            capital += pnl
            hold_minutes = (bar["ts"] - position.entry_time).total_seconds() / 60
            pnl_pct = (pnl / (position.entry_price * position.quantity)) * 100
            result.trades.append(
                Trade(
                    symbol=position.symbol,
                    signal_name=position.signal_name,
                    side=position.side,
                    entry_time=position.entry_time,
                    entry_price=position.entry_price,
                    exit_time=bar["ts"],
                    exit_price=exit_price,
                    quantity=position.quantity,
                    exit_reason=exit_event.reason,
                    pnl=pnl,
                    pnl_pct=pnl_pct,
                    hold_minutes=hold_minutes,
                )
            )
            del positions[symbol]
            result.exits_executed += 1

        # Generate signals / exits from current bar close.
        for _, bar in group.iterrows():
            symbol = str(bar["symbol"])
            timestamp = pd.Timestamp(bar["ts"])
            if symbol not in positions:
                p_up = bar["p_up"]
                p_flat = bar["p_flat"]
                p_down = bar["p_down"]
                if pd.notna(p_up) and pd.notna(p_down) and pd.notna(p_flat):
                    entry_event = signal.entry_event_from_probabilities(
                        symbol=symbol,
                        timestamp=timestamp,
                        p_down=float(p_down),
                        p_flat=float(p_flat),
                        p_up=float(p_up),
                    )
                    if entry_event is not None:
                        pending_entries.append(entry_event)
                        result.signals_generated += 1

            if symbol in positions:
                position = positions[symbol]
                exit_event = signal.check_exit(position, {}, bar, timestamp)
                if exit_event is not None:
                    pending_exits.append(exit_event)

        equity = capital
        for symbol, position in positions.items():
            symbol_bar = group[group["symbol"] == symbol]
            if symbol_bar.empty:
                continue
            current_price = symbol_bar.iloc[0]["close"]
            unrealized = (
                (current_price - position.entry_price) * position.quantity
                if position.side == SignalSide.LONG
                else (position.entry_price - current_price) * position.quantity
            )
            equity += unrealized
        equity_values.append(equity)
        equity_timestamps.append(ts)

    # Close remaining positions at last close.
    last_ts = scored_bars["ts"].max()
    for symbol, position in list(positions.items()):
        symbol_bars = scored_bars[scored_bars["symbol"] == symbol]
        if symbol_bars.empty:
            continue
        last_price = symbol_bars.iloc[-1]["close"]
        pnl = (
            (last_price - position.entry_price) * position.quantity
            if position.side == SignalSide.LONG
            else (position.entry_price - last_price) * position.quantity
        )
        pnl -= commission_per_share * position.quantity * 2
        capital += pnl
        result.trades.append(
            Trade(
                symbol=position.symbol,
                signal_name=position.signal_name,
                side=position.side,
                entry_time=position.entry_time,
                entry_price=position.entry_price,
                exit_time=last_ts,
                exit_price=last_price,
                quantity=position.quantity,
                exit_reason="end_of_data",
                pnl=pnl,
                pnl_pct=(pnl / (position.entry_price * position.quantity)) * 100,
                hold_minutes=(last_ts - position.entry_time).total_seconds() / 60,
            )
        )
        result.exits_executed += 1

    result.equity_curve = pd.Series(equity_values, index=equity_timestamps)
    return result


def _is_non_trivial(row: pd.Series) -> bool:
    return bool(row["num_trades"] >= 5)


def _rank_results(results_df: pd.DataFrame) -> pd.DataFrame:
    ranked = results_df.copy()
    ranked["non_trivial"] = ranked.apply(_is_non_trivial, axis=1)
    ranked = ranked.sort_values(
        [
            "non_trivial",
            "sharpe_ratio",
            "profit_factor",
            "total_return_pct",
            "num_trades",
        ],
        ascending=[False, False, False, False, False],
    ).reset_index(drop=True)
    return ranked


def _iter_policy_configs() -> list[tuple[float, float, str, float, float, int]]:
    configs: list[tuple[float, float, str, float, float, int]] = []
    for threshold, gap, exit_mode, time_limit in product(
        THRESHOLDS,
        ENTRY_GAPS,
        EXIT_MODES,
        TIME_LIMITS,
    ):
        if exit_mode == "time_only":
            configs.append((threshold, gap, exit_mode, 0.0, 0.0, time_limit))
            continue
        if exit_mode == "target_only_time":
            for tp_pct in TP_PCTS:
                configs.append((threshold, gap, exit_mode, tp_pct, 0.0, time_limit))
            continue
        if exit_mode == "stop_only_time":
            for sl_pct in SL_PCTS:
                configs.append((threshold, gap, exit_mode, 0.0, sl_pct, time_limit))
            continue
        for tp_pct, sl_pct in product(TP_PCTS, SL_PCTS):
            configs.append((threshold, gap, exit_mode, tp_pct, sl_pct, time_limit))
    return configs


def _write_report(
    output_dir: Path,
    summary: dict[str, Any],
    ranked_df: pd.DataFrame,
) -> Path:
    report_path = output_dir / "report.md"
    lines = [
        "# Phase 3 ML Trigger Calibration",
        "",
        "## Scope",
        "",
        f"- Verified overlap symbol-days: `{summary['symbol_days']}`",
        f"- Verified overlap windows: `{', '.join(summary['windows'])}`",
        f"- Bars loaded: `{summary['bars_loaded']}`",
        f"- L2 snapshots loaded: `{summary['l2_loaded']}`",
        f"- Model path: `{summary['model_path']}`",
        f"- Configurations tested: `{summary['config_count']}`",
        f"- Entry gap grid: `{', '.join(f'{gap:.2f}' for gap in ENTRY_GAPS)}`",
        f"- Exit modes: `{', '.join(EXIT_MODES)}`",
        "",
        "## Acceptance",
        "",
        f"- Non-trivial configs: `{summary['non_trivial_configs']}`",
        f"- Acceptance status: `{summary['acceptance_status']}`",
        "",
        "## Best Config",
        "",
        f"- Confidence threshold: `{summary['best_config']['confidence_threshold']:.2f}`",
        f"- Probability gap: `{summary['best_config']['min_probability_gap']:.2f}`",
        f"- Exit mode: `{summary['best_config']['exit_mode']}`",
        f"- TP: `{summary['best_config']['target_pct']:.2f}`",
        f"- SL: `{summary['best_config']['stop_pct']:.2f}`",
        f"- Time limit: `{int(summary['best_config']['time_limit_minutes'])}` min",
        f"- Trades: `{int(summary['best_config']['num_trades'])}`",
        f"- Sharpe: `{summary['best_config']['sharpe_ratio']:.2f}`",
        f"- Profit factor: `{summary['best_config']['profit_factor']:.2f}`",
        f"- Win rate: `{summary['best_config']['win_rate']:.1f}%`",
        f"- Total return: `{summary['best_config']['total_return_pct']:.3f}%`",
        "",
        "## Top Configs",
        "",
    ]

    top = ranked_df.head(10)
    for _, row in top.iterrows():
        lines.append(
            f"- thr `{row['confidence_threshold']:.2f}` / gap `{row['min_probability_gap']:.2f}` / "
            f"mode `{row['exit_mode']}` / tp `{row['target_pct']:.2f}` / "
            f"sl `{row['stop_pct']:.2f}` / tl `{int(row['time_limit_minutes'])}`: "
            f"`{int(row['num_trades'])}` trades, Sharpe `{row['sharpe_ratio']:.2f}`, "
            f"PF `{row['profit_factor']:.2f}`, return `{row['total_return_pct']:.3f}%`"
        )

    lines.extend(["", "## Next Step", "", summary["next_step"], ""])
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def run_phase3_matrix(overlap_path: Path, output_dir: Path) -> dict[str, Any]:
    overlap_keys = _load_overlap_keys(overlap_path)
    base_config = copy.deepcopy(DEFAULT_CONFIG)
    scored_bars, l2_rows = _build_scored_bars(overlap_keys, base_config)

    results: list[dict[str, Any]] = []
    configs = _iter_policy_configs()
    for threshold, gap, exit_mode, tp_pct, sl_pct, time_limit in configs:
        logger.info(
            "Running config thr=%.2f gap=%.2f mode=%s tp=%.2f sl=%.2f tl=%s",
            threshold,
            gap,
            exit_mode,
            tp_pct,
            sl_pct,
            time_limit,
        )
        results.append(
            _run_one_config(
                scored_bars=scored_bars,
                threshold=threshold,
                min_probability_gap=gap,
                exit_mode=exit_mode,
                tp_pct=tp_pct,
                sl_pct=sl_pct,
                time_limit=time_limit,
            )
        )

    results_df = pd.DataFrame(results)
    ranked_df = _rank_results(results_df)
    best_row = ranked_df.iloc[0].to_dict()
    non_trivial_configs = int(ranked_df["non_trivial"].sum())
    summary = {
        "symbol_days": int(len(overlap_keys)),
        "windows": _window_strings(overlap_keys),
        "bars_loaded": int(len(scored_bars)),
        "l2_loaded": int(l2_rows),
        "model_path": DEFAULT_CONFIG["signals"]["ml"]["model_path"],
        "config_count": int(len(results_df)),
        "non_trivial_configs": non_trivial_configs,
        "acceptance_status": "pass" if non_trivial_configs > 0 else "fail",
        "best_config": best_row,
        "next_step": (
            "Proceed to Phase 4 multi-window validation with the best live config."
            if non_trivial_configs > 0
            else "No viable live config produced trades; revisit overlap windows or signal logic."
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    results_df.to_csv(output_dir / "matrix_results.csv", index=False)
    ranked_df.to_csv(output_dir / "matrix_ranked.csv", index=False)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    report_path = _write_report(output_dir, summary, ranked_df)
    logger.info("Phase 3 report written to %s", report_path)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ML Phase 3 threshold calibration")
    parser.add_argument(
        "--overlap-path",
        type=Path,
        default=Path("output/ml_phase1_diagnostics_2026-03-12/overlap_symbol_days.csv"),
        help="Verified overlap symbol-day CSV",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/ml_phase3_matrix_2026-03-12"),
        help="Directory for Phase 3 artifacts",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_phase3_matrix(args.overlap_path, args.output_dir)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
