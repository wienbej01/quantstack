"""Focused tests for ML research helper scripts."""

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.run_ml_long_side_regime_report import (
    _parse_windows as parse_regime_windows,
)
from scripts.run_ml_long_side_regime_report import _source_type_from_features
from scripts.run_ml_action_ranker_budget_backtest import RankedAction
from scripts.run_ml_action_ranker_budget_backtest import WeakContextGate
from scripts.run_ml_action_ranker_budget_backtest import (
    _is_rejected_by_weak_context_gate,
)
from scripts.run_ml_action_ranker_budget_backtest import (
    _load_existing_results as load_action_results,
)
from scripts.run_ml_action_ranker_budget_backtest import _load_or_build_ranked_actions
from scripts.run_ml_action_ranker_budget_backtest import _quality_feature_frame
from scripts.run_ml_action_ranker_budget_backtest import (
    _ranked_cache_path as ranked_cache_path,
)
from scripts.run_ml_action_ranker_budget_backtest import (
    _select_topk as select_action_topk,
)
from scripts.run_ml_action_ranker_budget_backtest import (
    _symbol_ranked_cache_path as symbol_ranked_cache_path,
)
from scripts.run_ml_action_ranker_budget_backtest import (
    _to_signal_event as to_action_signal_event,
)
from scripts.run_ml_action_ranker_budget_backtest import (
    _write_outputs as write_action_outputs,
)
from scripts.run_ml_action_ranker_forensic_report import _compare_cohorts
from scripts.run_ml_action_ranker_forensic_report import _explicit_or_matrix_config
from scripts.run_ml_action_ranker_forensic_report import _load_best_config
from scripts.run_ml_action_ranker_forensic_report import _matrix_or_explicit_gate
from scripts.run_ml_action_ranker_forensic_report import _match_action_to_trade
from scripts.run_ml_action_ranker_gate_sensitivity import _load_gate_result
from scripts.run_ml_action_ranker_gate_sensitivity import _parse_gate_specs
from scripts.train_ml_action_quality_model import (
    _build_quality_training_rows_from_forensic,
)
from scripts.train_ml_action_quality_model import _quality_temporal_split
from scripts.run_ml_topk_budget_backtest import CandidateEntry
from scripts.run_ml_topk_budget_backtest import _parse_int_list
from scripts.run_ml_topk_budget_backtest import _select_daily_topk
from scripts.run_ml_side_threshold_matrix import _parse_float_list
from scripts.run_ml_side_threshold_matrix import _parse_windows as parse_matrix_windows
from src.signals.base import SignalSide


def test_side_threshold_matrix_parses_threshold_lists():
    assert _parse_float_list("0.40,0.45, 0.50") == [0.40, 0.45, 0.50]


def test_topk_budget_matrix_parses_int_lists():
    assert _parse_int_list("3,4, 5") == [3, 4, 5]


def test_research_scripts_parse_windows_consistently():
    expected = [("w1", "2026-03-06", "2026-03-11"), ("w2", "2026-03-12", "2026-03-13")]
    matrix = parse_matrix_windows("w1:2026-03-06:2026-03-11,w2:2026-03-12:2026-03-13")
    regime = parse_regime_windows("w1:2026-03-06:2026-03-11,w2:2026-03-12:2026-03-13")
    assert [(row.label, row.start, row.end) for row in matrix] == expected
    assert [(row.label, row.start, row.end) for row in regime] == expected


def test_regime_report_decodes_numeric_source_flags():
    assert _source_type_from_features({"source_is_features": 1.0}) == "features"
    assert _source_type_from_features({"source_is_raw": 1.0}) == "raw"
    assert _source_type_from_features({"source_is_unknown": 1.0}) == "unknown"


def test_topk_budget_selection_respects_long_cap():
    candidates = [
        CandidateEntry(
            date="2026-03-12",
            symbol="AAA",
            timestamp=pd.Timestamp("2026-03-12 09:31:00"),
            side=SignalSide.LONG,
            confidence=0.90,
            probability_gap=0.10,
            p_up=0.90,
            p_down=0.05,
            p_flat=0.05,
            rank_score=0.90,
        ),
        CandidateEntry(
            date="2026-03-12",
            symbol="BBB",
            timestamp=pd.Timestamp("2026-03-12 09:32:00"),
            side=SignalSide.LONG,
            confidence=0.80,
            probability_gap=0.08,
            p_up=0.80,
            p_down=0.10,
            p_flat=0.10,
            rank_score=0.80,
        ),
        CandidateEntry(
            date="2026-03-12",
            symbol="CCC",
            timestamp=pd.Timestamp("2026-03-12 09:33:00"),
            side=SignalSide.SHORT,
            confidence=0.70,
            probability_gap=0.07,
            p_up=0.10,
            p_down=0.70,
            p_flat=0.20,
            rank_score=0.70,
        ),
    ]

    selected = _select_daily_topk(candidates, top_k=2, max_longs_per_day=1)

    assert len(selected) == 2
    assert sum(1 for row in selected if row.side == SignalSide.LONG) == 1
    assert sum(1 for row in selected if row.side == SignalSide.SHORT) == 1


def test_action_ranker_signal_event_bounds_confidence_but_keeps_rank_score():
    event = to_action_signal_event(
        RankedAction(
            date="2026-03-12",
            symbol="AAA",
            timestamp=pd.Timestamp("2026-03-12 09:31:00"),
            side=SignalSide.LONG,
            hold_minutes=5,
            score=7.25,
            context=None,
        )
    )
    assert event.confidence == 1.0
    assert event.features["rank_score"] == 7.25
    assert event.features["hold_minutes"] == 5


def test_action_ranker_outputs_roundtrip_existing_results(tmp_path: Path):
    output_dir = tmp_path / "matrix"
    output_dir.mkdir()
    results = [
        {
            "top_k": 4,
            "max_longs_per_day": 1,
            "min_score": 0.0,
            "combined_trades": 18,
            "combined_total_pnl": -25.0,
            "combined_gross_profit": 80.0,
            "combined_gross_loss": 105.0,
            "active_days": 6,
            "w1_trades": 9,
            "w1_pnl": -10.0,
            "w1_profit_factor": 0.8,
            "w2_trades": 9,
            "w2_pnl": -15.0,
            "w2_profit_factor": 0.7,
            "combined_total_return_pct": -0.025,
            "combined_profit_factor": 80.0 / 105.0,
            "combined_trades_per_day": 3.0,
            "trade_budget_pass": True,
        },
        {
            "top_k": 3,
            "max_longs_per_day": 1,
            "min_score": 0.0,
            "combined_trades": 17,
            "combined_total_pnl": -90.0,
            "combined_gross_profit": 70.0,
            "combined_gross_loss": 160.0,
            "active_days": 6,
            "w1_trades": 8,
            "w1_pnl": -30.0,
            "w1_profit_factor": 0.6,
            "w2_trades": 9,
            "w2_pnl": -60.0,
            "w2_profit_factor": 0.4,
            "combined_total_return_pct": -0.09,
            "combined_profit_factor": 70.0 / 160.0,
            "combined_trades_per_day": 17 / 6,
            "trade_budget_pass": False,
        },
    ]

    summary = write_action_outputs(
        results=results,
        artifact_path="models/action_edge_ranker_ridge_2026-03-18.pkl",
        min_score=0.0,
        daily_top_ks=[3, 4],
        max_longs_per_day_values=[1],
        output_dir=output_dir,
    )

    loaded = load_action_results(output_dir)

    assert summary["best_config"]["top_k"] == 4
    assert len(loaded) == 2
    assert loaded[0]["top_k"] == 4
    summary_json = json.loads((output_dir / "summary.json").read_text())
    assert summary_json["configs_tested"] == 2
    assert summary_json["quality_artifact_path"] is None


def test_action_ranker_weak_context_gate_rejects_only_when_all_conditions_match():
    gate = WeakContextGate(max_pressure_k=0.0, max_spread=0.03, max_depth_imb_k=-0.02)
    rejected = RankedAction(
        date="2026-03-12",
        symbol="AAA",
        timestamp=pd.Timestamp("2026-03-12 09:31:00"),
        side=SignalSide.SHORT,
        hold_minutes=5,
        score=0.9,
        context={"pressure_k": 0.0, "spread": 0.02, "depth_imb_k": -0.10},
    )
    allowed = RankedAction(
        date="2026-03-12",
        symbol="BBB",
        timestamp=pd.Timestamp("2026-03-12 09:32:00"),
        side=SignalSide.SHORT,
        hold_minutes=5,
        score=0.8,
        context={"pressure_k": 0.0, "spread": 0.08, "depth_imb_k": -0.10},
    )

    assert _is_rejected_by_weak_context_gate(rejected, gate) is True
    assert _is_rejected_by_weak_context_gate(allowed, gate) is False


def test_action_ranker_selection_applies_weak_context_gate_before_topk():
    gate = WeakContextGate(max_pressure_k=0.0, max_spread=0.03, max_depth_imb_k=-0.02)
    selected = select_action_topk(
        [
            RankedAction(
                date="2026-03-12",
                symbol="AAA",
                timestamp=pd.Timestamp("2026-03-12 09:31:00"),
                side=SignalSide.SHORT,
                hold_minutes=5,
                score=0.95,
                context={"pressure_k": 0.0, "spread": 0.02, "depth_imb_k": -0.10},
            ),
            RankedAction(
                date="2026-03-12",
                symbol="BBB",
                timestamp=pd.Timestamp("2026-03-12 09:32:00"),
                side=SignalSide.SHORT,
                hold_minutes=5,
                score=0.90,
                context={"pressure_k": 0.0, "spread": 0.08, "depth_imb_k": -0.10},
            ),
        ],
        top_k=1,
        max_longs_per_day=1,
        min_score=0.5,
        weak_context_gate=gate,
    )

    assert [row.symbol for row in selected] == ["BBB"]


def test_action_ranker_selection_applies_quality_filter_before_topk():
    selected = select_action_topk(
        [
            RankedAction(
                date="2026-03-12",
                symbol="AAA",
                timestamp=pd.Timestamp("2026-03-12 09:31:00"),
                side=SignalSide.SHORT,
                hold_minutes=5,
                score=0.95,
                quality_score=0.35,
            ),
            RankedAction(
                date="2026-03-12",
                symbol="BBB",
                timestamp=pd.Timestamp("2026-03-12 09:32:00"),
                side=SignalSide.SHORT,
                hold_minutes=5,
                score=0.90,
                quality_score=0.72,
            ),
        ],
        top_k=1,
        max_longs_per_day=1,
        min_score=0.5,
        quality_min_score=0.5,
    )

    assert [row.symbol for row in selected] == ["BBB"]


def test_action_ranker_quality_feature_frame_keeps_causal_price_context():
    frame, cols = _quality_feature_frame(
        [
            RankedAction(
                date="2026-03-12",
                symbol="AAA",
                timestamp=pd.Timestamp("2026-03-12 09:31:00"),
                side=SignalSide.LONG,
                hold_minutes=5,
                score=0.95,
                context={
                    "pressure_k": 10.0,
                    "spread": 0.02,
                    "depth_imb_k": 0.1,
                    "session_bucket": 1.0,
                    "dist_vwap_bps": 14.0,
                    "volume_rel_20": 1.3,
                    "rsi": 58.0,
                    "ret_3": 0.001,
                    "ret_10": 0.002,
                },
            )
        ],
        hold_minutes=[5],
    )

    assert "dist_vwap_bps" in cols
    assert "volume_rel_20" in cols
    assert "rsi" in cols
    assert float(frame.loc[0, "dist_vwap_bps"]) == 14.0
    assert float(frame.loc[0, "ret_10"]) == pytest.approx(0.002)


def test_action_ranker_ranked_cache_path_is_stable(tmp_path: Path):
    path = ranked_cache_path(tmp_path, "w1", "2026-03-13")
    assert path == tmp_path / "scored_action_cache" / "w1_2026-03-13.joblib"


def test_action_ranker_symbol_ranked_cache_path_is_stable(tmp_path: Path):
    path = symbol_ranked_cache_path(tmp_path, "w1", "2026-03-13", "HIMS")
    assert (
        path == tmp_path / "scored_action_cache" / "w1" / "2026-03-13" / "HIMS.joblib"
    )


def test_action_ranker_symbol_cache_reuses_completed_symbols(
    tmp_path: Path, monkeypatch
):
    calls = []

    def fake_score_symbol(*, date, symbol, bars_df, l2_df, config, artifact):
        del bars_df, l2_df, config, artifact
        calls.append((date, symbol))
        return [
            RankedAction(
                date=date,
                symbol=symbol,
                timestamp=pd.Timestamp(f"{date} 09:31:00"),
                side=SignalSide.LONG,
                hold_minutes=5,
                score=1.23,
            )
        ]

    monkeypatch.setattr(
        "scripts.run_ml_action_ranker_budget_backtest._score_symbol",
        fake_score_symbol,
    )

    payload = {
        "date": "2026-03-13",
        "bars": pd.DataFrame(
            {
                "ts": [
                    pd.Timestamp("2026-03-13 09:31:00"),
                    pd.Timestamp("2026-03-13 09:32:00"),
                    pd.Timestamp("2026-03-13 09:31:00"),
                    pd.Timestamp("2026-03-13 09:32:00"),
                ],
                "symbol": ["AAA", "AAA", "BBB", "BBB"],
            }
        ),
        "l2": None,
    }

    first = _load_or_build_ranked_actions(
        payload=payload,
        window_label="w1",
        config={},
        artifact={},
        output_dir=tmp_path,
        score_cache=True,
    )
    second = _load_or_build_ranked_actions(
        payload=payload,
        window_label="w1",
        config={},
        artifact={},
        output_dir=tmp_path,
        score_cache=True,
    )

    assert len(calls) == 2
    assert [row.symbol for row in first] == ["AAA", "BBB"]
    assert [row.symbol for row in second] == ["AAA", "BBB"]


def test_action_quality_training_rows_can_be_built_from_forensic_exports(
    tmp_path: Path,
):
    context_path = tmp_path / "entry_contexts.csv"
    selected_path = tmp_path / "selected_actions.csv"
    context_path.write_text(
        "\n".join(
            [
                "date,symbol,side,entry_time,pnl,pnl_pct,hold_minutes,session_bucket,pressure_k,spread,"
                "depth_imb_k,micro_off,spread_std_30s,spread_std_60s,micro_off_std_30s,"
                "micro_off_std_60s,depth_imb_k_mean_10s,depth_imb_k_mean_60s,dist_vwap_bps,"
                "hl_range_pct,oc_change_pct,volume_rel_20,atr_pct,position_in_range,rsi,bb_position,"
                "ret_3,ret_10",
                "2026-03-10,AAA,long,2026-03-10 09:31:00,5.0,0.1,6,1.0,10.0,0.02,0.1,0.0,0.01,0.02,0.01,0.02,"
                "0.1,0.2,12.5,0.02,0.01,1.4,0.03,0.75,61.0,0.65,0.001,0.002",
                "2026-03-10,BBB,short,2026-03-10 09:45:00,-3.0,-0.1,4,2.0,-5.0,0.03,-0.2,0.0,0.01,0.02,0.01,0.02,"
                "-0.1,-0.2,-8.0,0.03,-0.02,0.8,0.04,0.25,39.0,0.35,-0.001,-0.003",
            ]
        )
        + "\n"
    )
    selected_path.write_text(
        "\n".join(
            [
                "date,symbol,timestamp,side,hold_minutes,score",
                "2026-03-10,AAA,2026-03-10 09:30:00,long,5,0.75",
                "2026-03-10,BBB,2026-03-10 09:44:00,short,3,0.65",
            ]
        )
        + "\n"
    )

    dataset, stats = _build_quality_training_rows_from_forensic(
        context_path=context_path,
        selected_actions_path=selected_path,
        label_min_pnl=0.0,
    )

    assert stats["matched_rows"] == 2
    assert list(dataset["rank_score"]) == [0.75, 0.65]
    assert list(dataset["hold_minutes"]) == [5, 3]
    assert list(dataset["quality_target"]) == [1, 0]
    assert list(dataset["dist_vwap_bps"]) == [12.5, -8.0]
    assert list(dataset["ret_10"]) == [0.002, -0.003]


def test_quality_temporal_split_falls_back_for_two_date_dataset():
    dataset = pd.DataFrame(
        {
            "date": [
                "2026-03-12",
                "2026-03-12",
                "2026-03-12",
                "2026-03-13",
                "2026-03-13",
                "2026-03-13",
            ],
            "timestamp": pd.to_datetime(
                [
                    "2026-03-12 09:31:00",
                    "2026-03-12 09:35:00",
                    "2026-03-12 09:39:00",
                    "2026-03-13 09:31:00",
                    "2026-03-13 09:35:00",
                    "2026-03-13 09:39:00",
                ]
            ),
            "symbol": ["AAA", "BBB", "CCC", "AAA", "BBB", "CCC"],
            "quality_target": [1, 0, 1, 0, 1, 0],
            "pnl": [5.0, -2.0, 3.0, -1.0, 4.0, -3.0],
        }
    )

    train_df, val_df, test_df, split_info, split_mode = _quality_temporal_split(dataset)

    assert split_mode == "row_temporal"
    assert len(train_df) == 3
    assert len(val_df) == 1
    assert len(test_df) == 2
    assert split_info.holdout_symbols == []


def test_action_ranker_forensic_loads_best_config(tmp_path: Path):
    matrix_dir = tmp_path / "matrix"
    matrix_dir.mkdir()
    (matrix_dir / "summary.json").write_text(
        json.dumps(
            {
                "artifact_path": "models/action_ranker_xgb_2026-03-19.pkl",
                "min_score": 0.5,
                "best_config": {"top_k": 5, "max_longs_per_day": 1},
            }
        )
    )

    artifact_path, min_score, top_k, max_longs = _load_best_config(matrix_dir)

    assert artifact_path.endswith("action_ranker_xgb_2026-03-19.pkl")
    assert min_score == 0.5
    assert top_k == 5
    assert max_longs == 1


def test_action_ranker_forensic_uses_explicit_config_override(tmp_path: Path):
    matrix_dir = tmp_path / "matrix"
    matrix_dir.mkdir()
    (matrix_dir / "summary.json").write_text(
        json.dumps(
            {
                "artifact_path": "models/action_ranker_xgb_2026-03-19.pkl",
                "min_score": 0.5,
                "best_config": {"top_k": 5, "max_longs_per_day": 1},
            }
        )
    )

    loaded = _explicit_or_matrix_config(
        matrix_dir=matrix_dir,
        artifact_path="models/manual.pkl",
        min_score=0.4,
        top_k=4,
        max_longs_per_day=2,
    )

    assert loaded == ("models/manual.pkl", 0.4, 4, 2)


def test_action_ranker_forensic_loads_gate_from_matrix_summary(tmp_path: Path):
    matrix_dir = tmp_path / "matrix"
    matrix_dir.mkdir()
    (matrix_dir / "summary.json").write_text(
        json.dumps(
            {
                "artifact_path": "models/action_ranker_xgb_2026-03-19.pkl",
                "min_score": 0.5,
                "best_config": {"top_k": 5, "max_longs_per_day": 1},
                "weak_context_gate": {
                    "max_pressure_k": 0.0,
                    "max_spread": 0.03,
                    "max_depth_imb_k": -0.02,
                },
            }
        )
    )

    gate = _matrix_or_explicit_gate(
        matrix_dir=matrix_dir,
        max_pressure_k=None,
        max_spread=None,
        max_depth_imb_k=None,
    )

    assert gate is not None
    assert gate.max_pressure_k == 0.0
    assert gate.max_spread == 0.03
    assert gate.max_depth_imb_k == -0.02


def test_action_ranker_forensic_matches_trade_to_selected_action():
    selected = [
        RankedAction(
            date="2026-03-12",
            symbol="AAA",
            timestamp=pd.Timestamp("2026-03-12 09:31:00"),
            side=SignalSide.LONG,
            hold_minutes=5,
            score=0.77,
        )
    ]
    trade = type(
        "TradeStub",
        (),
        {
            "symbol": "AAA",
            "entry_time": pd.Timestamp("2026-03-12 09:31:00"),
        },
    )()

    matched = _match_action_to_trade(trade, selected)

    assert matched["rank_score"] == 0.77
    assert matched["scheduled_hold_minutes"] == 5


def test_action_ranker_forensic_compares_w1_losers_to_w2_winners():
    context_df = pd.DataFrame(
        {
            "cohort": ["w1_losers", "w1_losers", "w2_winners", "w2_winners"],
            "spread": [0.03, 0.04, 0.01, 0.02],
            "spread_std_30s": [0.01, 0.02, 0.01, 0.01],
            "spread_std_60s": [0.02, 0.03, 0.01, 0.01],
            "micro_off": [-0.2, -0.1, 0.1, 0.2],
            "micro_off_std_30s": [0.3, 0.3, 0.1, 0.1],
            "micro_off_std_60s": [0.4, 0.4, 0.1, 0.1],
            "depth_imb_k": [-0.1, -0.2, 0.3, 0.4],
            "depth_imb_k_mean_10s": [-0.2, -0.1, 0.2, 0.3],
            "depth_imb_k_mean_60s": [-0.3, -0.2, 0.4, 0.5],
            "pressure_k": [-0.1, -0.1, 0.2, 0.2],
            "session_bucket": [0.0, 0.0, 2.0, 2.0],
        }
    )

    comparison = _compare_cohorts(context_df, "w1_losers", "w2_winners")

    assert not comparison.empty
    assert comparison.iloc[0]["feature"] in {
        "depth_imb_k_mean_60s",
        "session_bucket",
        "micro_off_std_60s",
    }


def test_action_ranker_gate_sensitivity_parses_gate_specs():
    gates = _parse_gate_specs("anchor:0.0:0.03:-0.02,strict:-100.0:0.02:-0.10")

    assert [label for label, _ in gates] == ["anchor", "strict"]
    assert gates[0][1].max_pressure_k == 0.0
    assert gates[0][1].max_spread == 0.03
    assert gates[1][1].max_depth_imb_k == -0.10


def test_action_ranker_gate_sensitivity_loads_existing_gate_result(tmp_path: Path):
    gate_dir = tmp_path / "anchor"
    gate_dir.mkdir()
    payload = {"best_config": {"combined_total_pnl": 12.34}}
    (gate_dir / "summary.json").write_text(json.dumps(payload))

    assert _load_gate_result(gate_dir) == payload
