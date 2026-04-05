"""Tests for hypothesis runner configuration behavior."""

from copy import deepcopy
import json
from unittest.mock import MagicMock

import pandas as pd

from src.backtest.engine import BacktestResult
from scripts.run_hypothesis_test import (
    DEFAULT_CONFIG,
    _build_run_context,
    _contiguous_date_windows,
    _run_ml_windowed_backtest,
    _format_single_run_report,
    resolve_max_symbols,
)


def test_ml_defaults_to_unlimited_symbols():
    config = deepcopy(DEFAULT_CONFIG)
    config["max_symbols"] = 10
    config["ml"].pop("max_symbols", None)

    assert resolve_max_symbols("ml", config) == 0


def test_ml_honors_explicit_ml_symbol_cap():
    config = deepcopy(DEFAULT_CONFIG)
    config["max_symbols"] = 10
    config["ml"]["max_symbols"] = 7

    assert resolve_max_symbols("ml", config) == 7


def test_non_ml_uses_top_level_symbol_cap():
    config = deepcopy(DEFAULT_CONFIG)
    config["max_symbols"] = 12
    config["ml"]["max_symbols"] = 0

    assert resolve_max_symbols("order_flow", config) == 12


def test_default_bar_source_is_gold():
    config = deepcopy(DEFAULT_CONFIG)
    assert config["data"]["bar_source"] == "gold"


def test_bar_source_can_switch_to_polygon():
    config = deepcopy(DEFAULT_CONFIG)
    config["data"]["bar_source"] = "polygon"
    assert config["data"]["bar_source"] == "polygon"


def test_build_run_context_captures_ml_runtime_details():
    config = deepcopy(DEFAULT_CONFIG)
    result = BacktestResult(
        signals_generated=7,
        entries_executed=5,
        exits_executed=4,
        symbols_tested=["DOMO", "CPB"],
    )
    context = _build_run_context(
        hypothesis="ml",
        start_date="2026-03-10",
        end_date="2026-03-11",
        config=config,
        result=result,
        symbols=["CPB", "DOMO", "USO"],
        max_symbols=0,
        bar_source="polygon",
        total_bars_loaded=1172,
        l2_snapshots_loaded=356929,
    )

    assert context["bar_source"] == "polygon"
    assert context["signals_generated"] == 7
    assert context["entries_executed"] == 5
    assert context["exits_executed"] == 4
    assert context["symbols_tested_count"] == 2
    assert context["ml_signal"]["model_path"] == config["signals"]["ml"]["model_path"]


def test_format_single_run_report_includes_runtime_context():
    config = deepcopy(DEFAULT_CONFIG)
    result = BacktestResult(
        signals_generated=3,
        entries_executed=2,
        exits_executed=2,
        symbols_tested=["DOMO"],
    )
    context = _build_run_context(
        hypothesis="ml",
        start_date="2026-03-11",
        end_date="2026-03-11",
        config=config,
        result=result,
        symbols=["DOMO"],
        max_symbols=0,
        bar_source="polygon",
        total_bars_loaded=390,
        l2_snapshots_loaded=118998,
    )
    report = _format_single_run_report(
        {
            "num_trades": 2,
            "total_return_pct": 0.1,
            "final_equity": 100100.0,
            "sharpe_ratio": 1.2,
            "expectancy": 5.0,
            "win_rate": 60.0,
            "profit_factor": 1.5,
            "max_drawdown_pct": 0.2,
            "t_stat": 2.3,
            "avg_win": 10.0,
            "avg_loss": -5.0,
            "avg_hold_minutes": 8.0,
            "best_trade_pnl": 12.0,
            "worst_trade_pnl": -4.0,
            "total_pnl": 100.0,
            "initial_capital": 100000.0,
        },
        {
            "sharpe_pass": True,
            "win_rate_pass": True,
            "profit_factor_pass": True,
            "t_stat_pass": True,
            "min_trades_pass": False,
            "all_pass": False,
        },
        context,
    )

    assert "RUN CONTEXT" in report
    assert "Bar Source:       polygon" in report
    assert "Signals Generated: 3" in report
    assert "Entries Executed:  2" in report
    assert "Model Path:" in report


def test_contiguous_date_windows_splits_gaps():
    windows = _contiguous_date_windows(
        ["2026-03-06", "2026-03-07", "2026-03-10", "2026-03-11", "2026-03-13"]
    )

    assert windows == [
        ["2026-03-06", "2026-03-07"],
        ["2026-03-10", "2026-03-11"],
        ["2026-03-13"],
    ]


def test_run_ml_windowed_backtest_uses_fresh_engine_per_day(monkeypatch):
    bars_df = pd.DataFrame(
        [
            {
                "ts": pd.Timestamp("2026-03-06 09:30:00"),
                "symbol": "DOMO",
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
            },
            {
                "ts": pd.Timestamp("2026-03-07 09:30:00"),
                "symbol": "DOMO",
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
            },
            {
                "ts": pd.Timestamp("2026-03-10 09:30:00"),
                "symbol": "DOMO",
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
            },
        ]
    )
    l2_df = pd.DataFrame(
        [
            {"ts_utc": pd.Timestamp("2026-03-06 14:29:45+00:00"), "symbol": "DOMO"},
            {"ts_utc": pd.Timestamp("2026-03-07 14:29:45+00:00"), "symbol": "DOMO"},
            {"ts_utc": pd.Timestamp("2026-03-10 14:29:45+00:00"), "symbol": "DOMO"},
        ]
    )
    run_calls = []
    signal_ids = []

    class DummyEngine:
        def __init__(self, config):
            self.config = config

        def run(self, window_bars, l2_df=None, signals=None):
            run_calls.append(
                sorted(
                    pd.to_datetime(window_bars["ts"]).dt.strftime("%Y-%m-%d").unique()
                )
            )
            signal_ids.append(id(signals[0]))
            result = BacktestResult()
            result.signals_generated = 1
            result.entries_executed = 1
            result.exits_executed = 1
            result.symbols_tested = ["DOMO"]
            result.equity_curve = pd.Series(
                [100000.0, 100010.0],
                index=[window_bars["ts"].iloc[0], window_bars["ts"].iloc[-1]],
            )
            return result

    monkeypatch.setattr("scripts.run_hypothesis_test.AlphaBacktestEngine", DummyEngine)
    signal = MagicMock()
    signal._model = object()
    signal._feature_cols = ["f1"]
    signal._calibrator = None
    signal._recommended_threshold = 0.35
    monkeypatch.setattr(
        "scripts.run_hypothesis_test.MLSignal",
        lambda config, model_artifact=None: MagicMock(
            signal_name="MLSignal",
            _model=model_artifact["model"],
            _feature_cols=model_artifact["feature_columns"],
            _calibrator=model_artifact["calibrator"],
            _recommended_threshold=model_artifact["recommended_threshold"],
        ),
    )
    result = _run_ml_windowed_backtest(
        bars_df=bars_df,
        l2_df=l2_df,
        signal=signal,
        config=deepcopy(DEFAULT_CONFIG),
    )

    assert run_calls == [["2026-03-06"], ["2026-03-07"], ["2026-03-10"]]
    assert len(set(signal_ids)) == 3
    assert result.signals_generated == 3
    assert result.entries_executed == 3
    assert result.exits_executed == 3


def test_main_ml_overrides_update_config(monkeypatch, tmp_path):
    captured = {}

    def fake_run_single_hypothesis(hypothesis, start_date, end_date, config):
        captured["config"] = config
        result = BacktestResult()
        result.symbols_tested = []
        payload = {
            "hypothesis": hypothesis,
            "metrics": {
                "num_trades": 0,
                "total_return_pct": 0.0,
                "final_equity": 100000.0,
                "sharpe_ratio": 0.0,
                "expectancy": 0.0,
                "win_rate": 0.0,
                "profit_factor": 0.0,
                "max_drawdown_pct": 0.0,
                "t_stat": 0.0,
                "avg_win": 0.0,
                "avg_loss": 0.0,
                "avg_hold_minutes": 0.0,
                "best_trade_pnl": 0.0,
                "worst_trade_pnl": 0.0,
                "total_pnl": 0.0,
                "initial_capital": 100000.0,
            },
            "threshold_check": {
                "sharpe_pass": False,
                "win_rate_pass": False,
                "profit_factor_pass": False,
                "t_stat_pass": False,
                "min_trades_pass": False,
                "all_pass": False,
            },
            "run_context": {
                "hypothesis": hypothesis,
                "start_date": start_date,
                "end_date": end_date,
                "bar_source": "polygon",
                "max_symbols": 0,
                "symbols_considered": [],
                "symbols_tested": [],
                "symbols_tested_count": 0,
                "total_bars_loaded": 0,
                "l2_snapshots_loaded": 0,
                "signals_generated": 0,
                "entries_executed": 0,
                "exits_executed": 0,
                "num_trades": 0,
                "validation_thresholds": deepcopy(
                    DEFAULT_CONFIG["validation"]["thresholds"]
                ),
                "ml_signal": {},
            },
        }
        return payload

    monkeypatch.setattr(
        "scripts.run_hypothesis_test.run_single_hypothesis", fake_run_single_hypothesis
    )
    monkeypatch.setattr(
        "scripts.run_hypothesis_test.save_report", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        "sys.exit", lambda code: (_ for _ in ()).throw(SystemExit(code))
    )

    from scripts.run_hypothesis_test import main
    import sys

    argv = [
        "run_hypothesis_test.py",
        "--hypothesis",
        "ml",
        "--start",
        "2026-03-06",
        "--end",
        "2026-03-11",
        "--bar-source",
        "polygon",
        "--ml-model-path",
        "models/test.pkl",
        "--ml-threshold",
        "0.40",
        "--ml-long-threshold",
        "0.45",
        "--ml-short-threshold",
        "0.35",
        "--ml-time-limit-minutes",
        "5",
        "--ml-exit-mode",
        "time_only",
    ]
    monkeypatch.setattr(sys, "argv", argv)

    try:
        main()
    except SystemExit:
        pass

    ml_cfg = captured["config"]["signals"]["ml"]
    assert captured["config"]["data"]["bar_source"] == "polygon"
    assert ml_cfg["model_path"] == "models/test.pkl"
    assert ml_cfg["confidence_threshold"] == 0.40
    assert ml_cfg["long_confidence_threshold"] == 0.45
    assert ml_cfg["short_confidence_threshold"] == 0.35
    assert ml_cfg["time_limit_minutes"] == 5
    assert ml_cfg["exit_mode"] == "time_only"
