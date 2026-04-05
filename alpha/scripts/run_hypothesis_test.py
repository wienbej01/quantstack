#!/usr/bin/env python3
"""Run single hypothesis test.

Tests one hypothesis (H1, H2, or H3) with walk-forward validation.
Generates report with performance metrics and pass/fail recommendation.

Usage:
    python scripts/run_hypothesis_test.py --hypothesis order_flow --start 2024-01-01 --end 2024-12-31
    python scripts/run_hypothesis_test.py --hypothesis whale_detect --start 2024-01-01 --end 2024-12-31
    python scripts/run_hypothesis_test.py --hypothesis liquidity_fade --start 2024-01-01 --end 2024-12-31
"""

import argparse
import copy
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd  # ADD THIS LINE - Required for pd.concat()

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest import AlphaBacktestEngine
from src.backtest.engine import BacktestResult
from src.backtest.regime_split import RegimeStratifier
from src.backtest.walk_forward import WalkForwardValidator
from src.data import GoldLoader, L2Loader, SipLoader
from src.metrics import (
    check_minimum_thresholds,
    compute_all_metrics,
    format_metrics_report,
)
from src.metrics.diagnostics import (
    analyze_attribution,
    generate_trade_attribution,
    save_report,
)
from src.signals import (
    LiquidityFadeSignal,
    MLSignal,
    OrderFlowSignal,
    WhaleDetectSignal,
)
from research.l2_impact.pipeline import fetch_polygon_ohlcv

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# Default configuration
DEFAULT_CONFIG = {
    "initial_capital": 100000,
    "max_symbols": 10,  # ADD THIS LINE - 0 for unlimited
    "data": {
        "bar_source": "gold",
        "polygon_cache_dir": "output/polygon_ohlcv_cache",
        "session_start": "09:30",
        "session_end": "16:00",
        "polygon": {
            "adjusted": True,
            "limit": 50000,
        },
    },
    "execution": {
        "latency_ms": 75,
        "slippage_bps": 5,
        "commission_per_share": 0.005,
    },
    "risk": {
        "max_position_pct": 0.02,
        "max_positions": 5,
        "max_daily_loss_pct": 0.03,
    },
    "validation": {
        "walk_forward": {
            "train_months": 3,
            "val_months": 1,
            "min_profitable_periods": 0.7,
        },
        "regime": {
            "spy_sma_period": 20,
            "vix_threshold": 20,
            "min_regimes_profitable": 2,
        },
        "thresholds": {
            "min_sharpe": 0.75,
            "min_win_rate": 52.0,
            "min_profit_factor": 1.2,
            "min_t_stat": 2.0,
            "min_trades": 500,
        },
    },
    "signals": {
        "order_flow": {
            "book_imbalance_threshold": 0.35,
            "trade_imbalance_threshold": 0.25,
            "max_spread_pct": 0.05,
            "target_pct": 0.4,
            "stop_pct": 0.25,
            "time_limit_minutes": 10,
        },
        "whale_detect": {
            "large_order_mult": 5.0,
            "min_rvol": 1.5,
            "min_flow_imb": 0.1,
            "target_pct": 0.8,
            "stop_pct": 0.4,
            "time_limit_minutes": 30,
        },
        "liquidity_fade": {
            "depth_drop_threshold": 0.5,
            "price_spike_pct": 0.2,
            "target_pct": 0.3,
            "stop_pct": 0.3,
            "time_limit_minutes": 5,
        },
        "ml": {
            "model_path": "models/xgb_h60_grid_fixedlabels_2026-03-12.pkl",
            "confidence_threshold": 0.45,
            "long_confidence_threshold": 0.45,
            "short_confidence_threshold": 0.45,
            "min_probability_gap": 0.00,
            "max_flat_probability": 1.00,
            "target_pct": 0.00,
            "stop_pct": 0.00,
            "time_limit_minutes": 8,
            "cooldown_seconds": 60,
            "exit_mode": "time_only",
        },
    },
    "ml": {
        "max_symbols": 0,
        "backtest_lookback_seconds": 300,
        "backtest_snapshot_staleness_seconds": 60,
    },
}


def _sanitize_for_json(value):
    """Convert nested result payloads into JSON-serializable Python types."""
    if isinstance(value, dict):
        return {key: _sanitize_for_json(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_for_json(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    return value


def _build_run_context(
    *,
    hypothesis: str,
    start_date: str,
    end_date: str,
    config: dict,
    result,
    symbols: list[str],
    max_symbols: int,
    bar_source: str,
    total_bars_loaded: int,
    l2_snapshots_loaded: int,
) -> dict:
    """Build a compact, auditable summary of the executed run context."""
    context = {
        "hypothesis": hypothesis,
        "start_date": start_date,
        "end_date": end_date,
        "bar_source": bar_source,
        "max_symbols": max_symbols,
        "symbols_considered": symbols,
        "symbols_tested": result.symbols_tested,
        "symbols_tested_count": len(result.symbols_tested),
        "total_bars_loaded": total_bars_loaded,
        "l2_snapshots_loaded": l2_snapshots_loaded,
        "signals_generated": result.signals_generated,
        "entries_executed": result.entries_executed,
        "exits_executed": result.exits_executed,
        "num_trades": result.num_trades,
        "validation_thresholds": config.get("validation", {}).get("thresholds", {}),
    }

    if hypothesis == "ml":
        ml_cfg = config.get("signals", {}).get("ml", {})
        context["ml_signal"] = {
            "model_path": ml_cfg.get("model_path"),
            "confidence_threshold": ml_cfg.get("confidence_threshold"),
            "long_confidence_threshold": ml_cfg.get(
                "long_confidence_threshold",
                ml_cfg.get("confidence_threshold"),
            ),
            "short_confidence_threshold": ml_cfg.get(
                "short_confidence_threshold",
                ml_cfg.get("confidence_threshold"),
            ),
            "min_probability_gap": ml_cfg.get("min_probability_gap"),
            "max_flat_probability": ml_cfg.get("max_flat_probability"),
            "time_limit_minutes": ml_cfg.get("time_limit_minutes"),
            "cooldown_seconds": ml_cfg.get("cooldown_seconds"),
            "exit_mode": ml_cfg.get("exit_mode"),
        }

    return context


def _format_threshold_check_section(
    thresholds: dict, threshold_check: dict
) -> list[str]:
    """Render threshold checks in the same format used in the console output."""
    return [
        "THRESHOLD CHECKS",
        "-" * 40,
        (
            f"Sharpe > {thresholds['min_sharpe']}:        "
            f"{'PASS' if threshold_check['sharpe_pass'] else 'FAIL'}"
        ),
        (
            f"Win Rate > {thresholds['min_win_rate']}%:       "
            f"{'PASS' if threshold_check['win_rate_pass'] else 'FAIL'}"
        ),
        (
            f"Profit Factor > {thresholds['min_profit_factor']}:  "
            f"{'PASS' if threshold_check['profit_factor_pass'] else 'FAIL'}"
        ),
        (
            f"T-Stat > {thresholds['min_t_stat']}:          "
            f"{'PASS' if threshold_check['t_stat_pass'] else 'FAIL'}"
        ),
        (
            f"Trades > {thresholds['min_trades']}:           "
            f"{'PASS' if threshold_check['min_trades_pass'] else 'FAIL'}"
        ),
        "-" * 40,
        (
            "Overall: "
            + (
                "ALL THRESHOLDS PASSED"
                if threshold_check["all_pass"]
                else "SOME THRESHOLDS FAILED"
            )
        ),
    ]


def _format_single_run_report(
    metrics: dict, threshold_check: dict, run_context: dict
) -> str:
    """Build a text report that includes both metrics and the executed run context."""
    lines = [format_metrics_report(metrics), ""]
    lines.extend(
        [
            "RUN CONTEXT",
            "-" * 40,
            f"Hypothesis:       {run_context['hypothesis']}",
            f"Date Range:       {run_context['start_date']} to {run_context['end_date']}",
            f"Bar Source:       {run_context['bar_source']}",
            f"Symbols Tested:   {run_context['symbols_tested_count']}",
            f"Bars Loaded:      {run_context['total_bars_loaded']}",
            f"L2 Snapshots:     {run_context['l2_snapshots_loaded']}",
            "",
            "ENGINE COUNTS",
            "-" * 40,
            f"Signals Generated: {run_context['signals_generated']}",
            f"Entries Executed:  {run_context['entries_executed']}",
            f"Exits Executed:    {run_context['exits_executed']}",
            f"Trades Recorded:   {run_context['num_trades']}",
        ]
    )

    ml_signal = run_context.get("ml_signal")
    if ml_signal:
        lines.extend(
            [
                "",
                "ML CONFIG",
                "-" * 40,
                f"Model Path:       {ml_signal['model_path']}",
                f"Threshold:        {ml_signal['confidence_threshold']}",
                f"Long Threshold:   {ml_signal['long_confidence_threshold']}",
                f"Short Threshold:  {ml_signal['short_confidence_threshold']}",
                f"Min Prob Gap:     {ml_signal['min_probability_gap']}",
                f"Max Flat Prob:    {ml_signal['max_flat_probability']}",
                f"Exit Mode:        {ml_signal['exit_mode']}",
                f"Time Limit Min:   {ml_signal['time_limit_minutes']}",
                f"Cooldown Sec:     {ml_signal['cooldown_seconds']}",
            ]
        )

    lines.extend(
        [
            "",
            *_format_threshold_check_section(
                run_context["validation_thresholds"], threshold_check
            ),
        ]
    )
    return "\n".join(lines)


def get_signal(hypothesis: str, config: dict):
    """Get signal instance for hypothesis."""
    if hypothesis == "order_flow":
        return OrderFlowSignal(config)
    elif hypothesis == "ml":
        return MLSignal(config)
    elif hypothesis == "whale_detect":
        return WhaleDetectSignal(config)
    elif hypothesis == "liquidity_fade":
        return LiquidityFadeSignal(config)
    else:
        raise ValueError(f"Unknown hypothesis: {hypothesis}")


def resolve_max_symbols(hypothesis: str, config: dict) -> int:
    """Resolve the symbol cap for a backtest run.

    ML validation should use the full L2-covered universe unless an explicit ML-specific
    cap is provided. Other hypotheses keep the historical top-level cap behavior.
    """
    if hypothesis == "ml":
        return int(config.get("ml", {}).get("max_symbols", 0))
    return int(config.get("max_symbols", 10))


def load_polygon_bars(
    symbol: str,
    start_date: str,
    end_date: str,
    config: dict,
) -> pd.DataFrame:
    """Load Polygon minute bars and normalize to the backtest schema."""
    data_cfg = config.get("data", {})
    cache_dir = Path(data_cfg.get("polygon_cache_dir", "output/polygon_ohlcv_cache"))
    tz = "America/New_York"
    all_frames: list[pd.DataFrame] = []
    for date in pd.date_range(start_date, end_date, freq="D"):
        date_str = date.strftime("%Y-%m-%d")
        try:
            frame = fetch_polygon_ohlcv(
                symbol=symbol,
                date=date_str,
                tz=tz,
                config=data_cfg,
                cache_dir=cache_dir,
            ).copy()
        except RuntimeError as exc:
            logger.debug("Skipping Polygon bars for %s %s: %s", symbol, date_str, exc)
            continue
        if frame.empty:
            continue
        frame = frame.rename(columns={"ts_minute": "ts"})
        frame["ts"] = pd.to_datetime(frame["ts"])
        frame["symbol"] = symbol
        all_frames.append(
            frame[["ts", "open", "high", "low", "close", "volume", "symbol"]]
        )

    if not all_frames:
        raise FileNotFoundError(
            f"No Polygon data found for {symbol} between {start_date} and {end_date}"
        )

    result = (
        pd.concat(all_frames, ignore_index=True)
        .sort_values("ts")
        .reset_index(drop=True)
    )
    logger.info(
        "Loaded %s Polygon bars for %s from %s to %s",
        len(result),
        symbol,
        start_date,
        end_date,
    )
    return result


def load_bars_with_fallback(
    *,
    symbol: str,
    start_date: str,
    end_date: str,
    config: dict,
    gold_loader: GoldLoader,
) -> tuple[pd.DataFrame, str]:
    """Load minute bars from the preferred source with an automatic fallback.

    The homeserver currently has complete cached Polygon bars for the active 2026
    alpha windows, while the historical Gold/SPY store is incomplete for those
    dates. To keep the same command line usable across machines, we try the
    configured source first and then fall back to the alternate source.
    """
    preferred = config.get("data", {}).get("bar_source", "gold")
    if preferred not in {"gold", "polygon"}:
        raise ValueError(f"Unsupported bar_source: {preferred}")

    source_loaders = {
        "gold": lambda: gold_loader.load_bars(symbol, start_date, end_date),
        "polygon": lambda: load_polygon_bars(symbol, start_date, end_date, config),
    }
    attempted_errors: list[str] = []
    for source_name in [preferred, "polygon" if preferred == "gold" else "gold"]:
        try:
            frame = source_loaders[source_name]()
            if frame.empty:
                attempted_errors.append(f"{source_name}: returned 0 rows")
                continue
            if source_name != preferred:
                logger.warning(
                    "Falling back to %s bars for %s (%s to %s); preferred source was %s",
                    source_name,
                    symbol,
                    start_date,
                    end_date,
                    preferred,
                )
            return frame, source_name
        except Exception as exc:
            attempted_errors.append(f"{source_name}: {exc}")

    raise FileNotFoundError(
        f"No bars available for {symbol} between {start_date} and {end_date}. "
        f"Attempts: {'; '.join(attempted_errors)}"
    )


def _contiguous_date_windows(dates: list[str]) -> list[list[str]]:
    """Split sorted YYYY-MM-DD dates into contiguous windows."""
    ordered = pd.to_datetime(sorted(set(dates)))
    if len(ordered) == 0:
        return []

    windows: list[list[str]] = []
    current_window = [ordered[0].strftime("%Y-%m-%d")]
    prev = ordered[0]
    for current in ordered[1:]:
        if (current - prev).days == 1:
            current_window.append(current.strftime("%Y-%m-%d"))
        else:
            windows.append(current_window)
            current_window = [current.strftime("%Y-%m-%d")]
        prev = current
    windows.append(current_window)
    return windows


def _daily_date_windows(dates: list[str]) -> list[list[str]]:
    """Split dates into one-day windows.

    ML signals are intraday-only, so fresh engine state per day is the safest
    production path and avoids cross-day contamination in the live feature path.
    """
    return [[date] for date in sorted(set(dates))]


def _run_ml_windowed_backtest(
    *,
    bars_df: pd.DataFrame,
    l2_df: pd.DataFrame | None,
    signal: MLSignal,
    config: dict,
) -> BacktestResult:
    """Run ML backtests with fresh engine state per contiguous date window."""
    bars = bars_df.copy()
    bars["date"] = pd.to_datetime(bars["ts"]).dt.strftime("%Y-%m-%d")
    l2 = None
    if l2_df is not None and not l2_df.empty:
        l2 = l2_df.copy()
        l2["date"] = (
            pd.to_datetime(l2["ts_utc"], utc=True)
            .dt.tz_convert("America/New_York")
            .dt.strftime("%Y-%m-%d")
        )

    stitched_trades = []
    stitched_equity_parts: list[pd.Series] = []
    running_capital = float(config["initial_capital"])
    combined = BacktestResult()
    model_artifact = {
        "model": signal._model,
        "model_family": getattr(signal, "_model_family", "xgb_multiclass"),
        "feature_columns": signal._feature_cols,
        "calibrator": getattr(signal, "_calibrator", None),
        "recommended_threshold": getattr(signal, "_recommended_threshold", None),
    }

    for window_dates in _daily_date_windows(bars["date"].unique().tolist()):
        window_bars = (
            bars[bars["date"].isin(window_dates)].drop(columns=["date"]).copy()
        )
        if window_bars.empty:
            continue

        window_l2 = None
        if l2 is not None:
            window_l2 = l2[l2["date"].isin(window_dates)].drop(columns=["date"]).copy()

        engine = AlphaBacktestEngine(config)
        window_signal = MLSignal(config, model_artifact=model_artifact)
        window_result = engine.run(
            window_bars, l2_df=window_l2, signals=[window_signal]
        )
        stitched_trades.extend(window_result.trades)
        combined.signals_generated += int(window_result.signals_generated)
        combined.entries_executed += int(window_result.entries_executed)
        combined.exits_executed += int(window_result.exits_executed)

        if len(window_result.equity_curve) > 0:
            adjusted = (
                window_result.equity_curve - config["initial_capital"]
            ) + running_capital
            stitched_equity_parts.append(adjusted)
            running_capital = float(adjusted.iloc[-1])

    combined.trades = stitched_trades
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
    return combined


def _run_ml_daily_backtest(
    *,
    daily_payloads: list[dict],
    signal: MLSignal,
    config: dict,
) -> tuple[BacktestResult, int, int]:
    """Run ML backtests one loaded day at a time and stitch the results.

    This avoids any hidden state or filtering issues from preloading a wider
    multi-day bar/L2 frame and then slicing it back down inside the engine.
    """
    stitched_trades = []
    stitched_equity_parts: list[pd.Series] = []
    running_capital = float(config["initial_capital"])
    combined = BacktestResult()
    total_bars_loaded = 0
    total_l2_loaded = 0
    model_artifact = {
        "model": signal._model,
        "model_family": getattr(signal, "_model_family", "xgb_multiclass"),
        "feature_columns": signal._feature_cols,
        "calibrator": getattr(signal, "_calibrator", None),
        "recommended_threshold": getattr(signal, "_recommended_threshold", None),
    }

    for payload in daily_payloads:
        bars_df = payload["bars"]
        l2_df = payload["l2"]
        total_bars_loaded += len(bars_df)
        total_l2_loaded += len(l2_df) if l2_df is not None else 0

        if bars_df.empty:
            continue

        engine = AlphaBacktestEngine(config)
        day_signal = MLSignal(config, model_artifact=model_artifact)
        day_result = engine.run(bars_df, l2_df=l2_df, signals=[day_signal])

        stitched_trades.extend(day_result.trades)
        combined.signals_generated += int(day_result.signals_generated)
        combined.entries_executed += int(day_result.entries_executed)
        combined.exits_executed += int(day_result.exits_executed)

        if len(day_result.equity_curve) > 0:
            adjusted = (
                day_result.equity_curve - config["initial_capital"]
            ) + running_capital
            stitched_equity_parts.append(adjusted)
            running_capital = float(adjusted.iloc[-1])

    combined.trades = stitched_trades
    if daily_payloads:
        combined.start_date = daily_payloads[0]["date"]
        combined.end_date = daily_payloads[-1]["date"]
    combined.symbols_tested = sorted(
        {
            symbol
            for payload in daily_payloads
            for symbol in payload["bars"]["symbol"].unique().tolist()
        }
    )
    if stitched_equity_parts:
        combined.equity_curve = pd.concat(stitched_equity_parts)
        combined.equity_curve = combined.equity_curve[
            ~combined.equity_curve.index.duplicated(keep="last")
        ]
    else:
        combined.equity_curve = pd.Series(dtype=float)

    return combined, total_bars_loaded, total_l2_loaded


def run_single_hypothesis(
    hypothesis: str,
    start_date: str,
    end_date: str,
    config: dict = None,
) -> dict:
    """Run backtest for a single hypothesis.

    Args:
        hypothesis: Hypothesis name (order_flow, whale_detect, liquidity_fade, ml)
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        config: Optional config dict

    Returns:
        Dict with results and metrics
    """
    if config is None:
        config = DEFAULT_CONFIG

    logger.info(f"Running hypothesis test: {hypothesis}")
    logger.info(f"Date range: {start_date} to {end_date}")

    # Initialize signal
    signal = get_signal(hypothesis, config)

    # Load data
    logger.info("Loading data...")
    gold_loader = GoldLoader()
    l2_loader = L2Loader()
    l2_data = None
    bar_source = config.get("data", {}).get("bar_source", "gold")

    if hypothesis == "ml":
        available_dates = [
            date
            for date in l2_loader.get_available_dates(source_type="any")
            if start_date <= date <= end_date
        ]
        if not available_dates:
            raise ValueError("No L2 dates available in the requested range")
        symbols_by_date = {
            date: sorted(l2_loader.get_available_symbols(date, source_type="any"))
            for date in available_dates
        }
        symbols = sorted(
            {symbol for values in symbols_by_date.values() for symbol in values}
        )
        logger.info(f"L2-covered symbols in range: {len(symbols)}")
    else:
        sip_loader = SipLoader()
        sip_universe_df = sip_loader.load_universe_range(start_date, end_date)
        symbols = sip_universe_df["symbol"].unique().tolist()
        logger.info(f"SIP universe: {len(symbols)} symbols")

    max_symbols = resolve_max_symbols(hypothesis, config)
    if max_symbols > 0:
        symbols = symbols[:max_symbols]
    logger.info(f"Testing {len(symbols)} symbols (max_symbols={max_symbols})")

    all_bars = []
    daily_payloads: list[dict] = []
    if hypothesis == "ml":
        for date in available_dates:
            day_symbols = symbols_by_date.get(date, [])
            if max_symbols > 0:
                day_symbols = day_symbols[:max_symbols]
            day_bar_frames = []
            day_l2_frames = []
            for symbol in day_symbols:
                try:
                    bars, resolved_source = load_bars_with_fallback(
                        symbol=symbol,
                        start_date=date,
                        end_date=date,
                        config=config,
                        gold_loader=gold_loader,
                    )
                    if not bars.empty:
                        bars["symbol"] = symbol
                        all_bars.append(bars)
                        day_bar_frames.append(bars)
                        logger.info(
                            "Loaded %s %s bars for %s on %s",
                            len(bars),
                            resolved_source,
                            symbol,
                            date,
                        )
                except Exception as e:
                    logger.warning(f"Failed to load {symbol} on {date}: {e}")
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
    else:
        for symbol in symbols:
            try:
                bars, resolved_source = load_bars_with_fallback(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    config=config,
                    gold_loader=gold_loader,
                )
                if not bars.empty:
                    bars["symbol"] = symbol
                    all_bars.append(bars)
                    logger.info(
                        "Loaded %s %s bars for %s",
                        len(bars),
                        resolved_source,
                        symbol,
                    )
            except Exception as e:
                logger.warning(f"Failed to load {symbol}: {e}")

    if not all_bars:
        raise ValueError("No data loaded")

    bars_df = pd.concat(all_bars, ignore_index=True)
    logger.info(f"Total bars: {len(bars_df)}")

    if hypothesis == "ml":
        l2_data = (
            pd.concat(
                [
                    payload["l2"]
                    for payload in daily_payloads
                    if payload["l2"] is not None
                ],
                ignore_index=True,
            )
            if daily_payloads
            else None
        )
        logger.info(f"Loaded {len(l2_data) if l2_data is not None else 0} L2 snapshots")

    # Run backtest
    logger.info("Running backtest...")
    if hypothesis == "ml":
        result, total_bars_loaded, total_l2_loaded = _run_ml_daily_backtest(
            daily_payloads=daily_payloads,
            signal=signal,
            config=config,
        )
    else:
        engine = AlphaBacktestEngine(config)
        result = engine.run(bars_df, l2_df=l2_data, signals=[signal])
        total_bars_loaded = len(bars_df)
        total_l2_loaded = len(l2_data) if l2_data is not None else 0

    # Compute metrics
    logger.info("Computing metrics...")
    metrics = compute_all_metrics(result, initial_capital=config["initial_capital"])

    # Check thresholds
    thresholds = config["validation"]["thresholds"]
    threshold_check = check_minimum_thresholds(metrics, **thresholds)

    # Print report
    print("\n" + format_metrics_report(metrics))

    # Print threshold results
    print("\nTHRESHOLD CHECKS")
    print("-" * 40)
    print(
        f"Sharpe > {thresholds['min_sharpe']}:        {'✅ PASS' if threshold_check['sharpe_pass'] else '❌ FAIL'}"
    )
    print(
        f"Win Rate > {thresholds['min_win_rate']}%:       {'✅ PASS' if threshold_check['win_rate_pass'] else '❌ FAIL'}"
    )
    print(
        f"Profit Factor > {thresholds['min_profit_factor']}:  {'✅ PASS' if threshold_check['profit_factor_pass'] else '❌ FAIL'}"
    )
    print(
        f"T-Stat > {thresholds['min_t_stat']}:          {'✅ PASS' if threshold_check['t_stat_pass'] else '❌ FAIL'}"
    )
    print(
        f"Trades > {thresholds['min_trades']}:           {'✅ PASS' if threshold_check['min_trades_pass'] else '❌ FAIL'}"
    )
    print("-" * 40)
    print(
        f"\nOverall: {'✅ ALL THRESHOLDS PASSED' if threshold_check['all_pass'] else '❌ SOME THRESHOLDS FAILED'}"
    )

    # Generate trade attribution
    attribution_df = generate_trade_attribution(result.trades)
    if not attribution_df.empty:
        logger.info("Trade attribution analysis...")
        analysis = analyze_attribution(attribution_df)

        print("\nTRADE ATTRIBUTION")
        print("-" * 40)
        if "win_rate_by_exit_reason" in analysis:
            print("Win Rate by Exit Reason:")
            for reason, wr in analysis["win_rate_by_exit_reason"].items():
                print(f"  {reason}: {wr:.1f}%")

        if "win_rate_by_signal" in analysis:
            print("\nWin Rate by Signal:")
            for signal, wr in analysis["win_rate_by_signal"].items():
                print(f"  {signal}: {wr:.1f}%")

    # Return results
    run_context = _build_run_context(
        hypothesis=hypothesis,
        start_date=start_date,
        end_date=end_date,
        config=config,
        result=result,
        symbols=symbols,
        max_symbols=max_symbols,
        bar_source=bar_source,
        total_bars_loaded=total_bars_loaded,
        l2_snapshots_loaded=total_l2_loaded,
    )
    return {
        "hypothesis": hypothesis,
        "metrics": metrics,
        "threshold_check": threshold_check,
        "result": result,
        "run_context": run_context,
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Run single hypothesis test")
    parser.add_argument(
        "--hypothesis",
        type=str,
        required=True,
        choices=["order_flow", "whale_detect", "liquidity_fade", "ml"],
        help="Hypothesis to test",
    )
    parser.add_argument(
        "--start",
        type=str,
        required=True,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        required=True,
        help="End date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--config",
        type=str,
        help="Path to config YAML file (optional)",
    )
    parser.add_argument(
        "--bar-source",
        type=str,
        choices=["gold", "polygon"],
        default=None,
        help="Minute-bar source for the backtest run",
    )
    parser.add_argument(
        "--ml-model-path", type=str, help="Override ML model artifact path"
    )
    parser.add_argument(
        "--ml-threshold", type=float, help="Override ML base confidence threshold"
    )
    parser.add_argument(
        "--ml-long-threshold", type=float, help="Override ML long threshold"
    )
    parser.add_argument(
        "--ml-short-threshold", type=float, help="Override ML short threshold"
    )
    parser.add_argument(
        "--ml-time-limit-minutes", type=int, help="Override ML hold duration"
    )
    parser.add_argument(
        "--ml-exit-mode",
        type=str,
        choices=["target_stop_time", "time_only", "target_only_time", "stop_only_time"],
        help="Override ML exit mode",
    )

    args = parser.parse_args()

    try:
        config = copy.deepcopy(DEFAULT_CONFIG)
        if args.bar_source is not None:
            config.setdefault("data", {})["bar_source"] = args.bar_source
        if args.hypothesis == "ml":
            ml_cfg = config.setdefault("signals", {}).setdefault("ml", {})
            if args.ml_model_path is not None:
                ml_cfg["model_path"] = args.ml_model_path
            if args.ml_threshold is not None:
                ml_cfg["confidence_threshold"] = args.ml_threshold
                ml_cfg["long_confidence_threshold"] = args.ml_threshold
                ml_cfg["short_confidence_threshold"] = args.ml_threshold
            if args.ml_long_threshold is not None:
                ml_cfg["long_confidence_threshold"] = args.ml_long_threshold
            if args.ml_short_threshold is not None:
                ml_cfg["short_confidence_threshold"] = args.ml_short_threshold
            if args.ml_time_limit_minutes is not None:
                ml_cfg["time_limit_minutes"] = args.ml_time_limit_minutes
            if args.ml_exit_mode is not None:
                ml_cfg["exit_mode"] = args.ml_exit_mode
        result = run_single_hypothesis(
            hypothesis=args.hypothesis,
            start_date=args.start,
            end_date=args.end,
            config=config,
        )

        # Save report
        output_dir = Path(__file__).parent.parent / "output"
        output_dir.mkdir(exist_ok=True)

        report_path = (
            output_dir / f"{args.hypothesis}_report_{args.start}_to_{args.end}.txt"
        )
        json_path = (
            output_dir / f"{args.hypothesis}_report_{args.start}_to_{args.end}.json"
        )
        save_report(
            _format_single_run_report(
                result["metrics"],
                result["threshold_check"],
                result["run_context"],
            ),
            report_path,
        )
        json_path.write_text(
            json.dumps(
                _sanitize_for_json(
                    {
                        "hypothesis": result["hypothesis"],
                        "metrics": result["metrics"],
                        "threshold_check": result["threshold_check"],
                        "run_context": result["run_context"],
                    }
                ),
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        print(f"\nReport saved to: {report_path}")
        print(f"Report JSON saved to: {json_path}")

        # Exit with appropriate code
        sys.exit(0 if result["threshold_check"]["all_pass"] else 1)

    except Exception as e:
        logger.error(f"Error running hypothesis test: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
