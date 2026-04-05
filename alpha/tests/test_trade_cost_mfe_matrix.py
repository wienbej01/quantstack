from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1] / "scripts" / "analyze_trade_cost_mfe.py"
)
SPEC = importlib.util.spec_from_file_location("analyze_trade_cost_mfe", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

AnalysisConfig = MODULE.AnalysisConfig
TradePath = MODULE.TradePath
build_path_matrix = MODULE.build_path_matrix
classify_path_outcome = MODULE.classify_path_outcome


def make_trade_path(
    trade_id: str,
    gross_bps_on_entry: float,
    elapsed_seconds: list[float],
    favorable_bps: list[float],
    adverse_bps: list[float],
) -> TradePath:
    return TradePath(
        trade_id=trade_id,
        system="l2-scalping",
        strategy="demo_strategy",
        substrategy="",
        symbol="TEST",
        session_date_et="2026-03-10",
        direction="long",
        entry_price=100.0,
        exit_price=100.0,
        exit_reason="",
        gross_pnl=gross_bps_on_entry,
        net_pnl=gross_bps_on_entry,
        gross_bps_on_entry=gross_bps_on_entry,
        net_bps_on_entry=gross_bps_on_entry,
        hold_seconds=float(max(elapsed_seconds)),
        exit_elapsed_seconds=float(max(elapsed_seconds)),
        raw_root_used="/tmp/raw",
        elapsed_seconds=np.array(elapsed_seconds, dtype=float),
        favorable_bps=np.array(favorable_bps, dtype=float),
        adverse_bps=np.array(adverse_bps, dtype=float),
    )


def test_classify_path_outcome_tp_before_sl() -> None:
    path = make_trade_path(
        trade_id="win-first",
        gross_bps_on_entry=-5.0,
        elapsed_seconds=[0.0, 5.0, 10.0, 15.0],
        favorable_bps=[0.0, 4.0, 12.0, 14.0],
        adverse_bps=[0.0, 2.0, 3.0, 11.0],
    )

    outcome = classify_path_outcome(
        path, horizon_seconds=15, stop_bps=10.0, tp_bps=10.0
    )

    assert outcome == "WIN"


def test_classify_path_outcome_sl_before_tp() -> None:
    path = make_trade_path(
        trade_id="loss-first",
        gross_bps_on_entry=-7.0,
        elapsed_seconds=[0.0, 5.0, 10.0],
        favorable_bps=[0.0, 4.0, 12.0],
        adverse_bps=[0.0, 11.0, 12.0],
    )

    outcome = classify_path_outcome(
        path, horizon_seconds=10, stop_bps=10.0, tp_bps=10.0
    )

    assert outcome == "LOSS"


def test_classify_path_outcome_neither() -> None:
    path = make_trade_path(
        trade_id="neither",
        gross_bps_on_entry=2.0,
        elapsed_seconds=[0.0, 5.0, 10.0],
        favorable_bps=[0.0, 3.0, 4.0],
        adverse_bps=[0.0, 2.0, 3.0],
    )

    outcome = classify_path_outcome(
        path, horizon_seconds=10, stop_bps=10.0, tp_bps=10.0
    )

    assert outcome == "NEITHER"


def test_build_path_matrix_regression_counts() -> None:
    trade_paths = [
        make_trade_path(
            trade_id="trade-a",
            gross_bps_on_entry=-5.0,
            elapsed_seconds=[0.0, 10.0, 20.0],
            favorable_bps=[0.0, 12.0, 20.0],
            adverse_bps=[0.0, 4.0, 6.0],
        ),
        make_trade_path(
            trade_id="trade-b",
            gross_bps_on_entry=-7.0,
            elapsed_seconds=[0.0, 10.0, 20.0],
            favorable_bps=[0.0, 5.0, 8.0],
            adverse_bps=[0.0, 12.0, 15.0],
        ),
    ]
    trades = pd.DataFrame(
        {
            "system": ["l2-scalping", "l2-scalping"],
            "strategy": ["demo_strategy", "demo_strategy"],
            "gross_bps_on_entry": [-5.0, -7.0],
        }
    )
    config = AnalysisConfig(
        start_date="2026-03-10",
        end_date="2026-03-10",
        output_dir=Path("/tmp"),
        max_horizon_seconds=30,
        horizons=(30,),
        path_horizons=(15, 30),
        path_stop_bps=(10.0,),
        path_r_multiples=(1.0, 1.5),
        path_system="l2-scalping",
        matrix_min_decided=1,
    )

    matrix = build_path_matrix(trade_paths, trades, config)

    row_15_r1 = matrix[
        (matrix["horizon_seconds"] == 15) & np.isclose(matrix["R_multiple"], 1.0)
    ].iloc[0]
    assert row_15_r1["wins"] == 1
    assert row_15_r1["losses"] == 1
    assert row_15_r1["neither"] == 0
    assert row_15_r1["rescued_losers"] == 1
    assert row_15_r1["path_wl_ratio_decided"] == 1.0

    row_15_r15 = matrix[
        (matrix["horizon_seconds"] == 15) & np.isclose(matrix["R_multiple"], 1.5)
    ].iloc[0]
    assert row_15_r15["wins"] == 0
    assert row_15_r15["losses"] == 1
    assert row_15_r15["neither"] == 1

    row_30_r15 = matrix[
        (matrix["horizon_seconds"] == 30) & np.isclose(matrix["R_multiple"], 1.5)
    ].iloc[0]
    assert row_30_r15["wins"] == 1
    assert row_30_r15["losses"] == 1
    assert row_30_r15["neither"] == 0
