from __future__ import annotations

import json

import pandas as pd

from src.paper_trading.action_ranker_paper import (
    filter_l2_scalping_symbols,
    load_daily_sip_symbols,
    ranked_action_to_dict,
)
from scripts.run_ml_action_ranker_budget_backtest import RankedAction
from src.signals.base import SignalSide


def test_filter_l2_scalping_symbols_matches_scalping_cap_and_arca_skip():
    symbols = ["SPY", "F", "qqq", "ABCD", "", "VST"]

    assert filter_l2_scalping_symbols(symbols, max_symbols=3) == ["F", "ABCD", "VST"]


def test_load_daily_sip_symbols_accepts_official_dict_layout(tmp_path):
    sip_dir = tmp_path / "date=2026-04-06"
    sip_dir.mkdir()
    (sip_dir / "sip_universe.json").write_text(
        json.dumps({"date": "2026-04-06", "symbols": [" aapl ", "MSFT", ""]})
    )

    assert load_daily_sip_symbols("2026-04-06", tmp_path) == ["AAPL", "MSFT"]


def test_ranked_action_to_dict_marks_paper_only_and_stable_id():
    action = RankedAction(
        date="2026-03-16",
        symbol="ABOS",
        timestamp=pd.Timestamp("2026-03-16 09:45:00"),
        side=SignalSide.LONG,
        hold_minutes=5,
        score=0.72,
        context={"spread": 0.02},
    )

    payload = ranked_action_to_dict(action)

    assert payload["action_id"] == "2026-03-16|ABOS|2026-03-16T09:45:00|long|5"
    assert payload["paper_only"] is True
    assert payload["execution_assumption"] == "entry_next_bar_open_time_exit_at_selected_hold"
    assert payload["context"] == {"spread": 0.02}
