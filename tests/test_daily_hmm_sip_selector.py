# tests/test_daily_hmm_sip_selector.py
from datetime import datetime

import pandas as pd
from qx_screener.daily_hmm_sip import DailyHMMSIPSelector


def test_daily_universe_selection() -> None:
    # Mock data with multiple dates (using integer nanosecond timestamps)
    ts1 = int(datetime(2024, 1, 3, 9, 30).timestamp() * 1e9)
    ts2 = int(datetime(2024, 1, 3, 10, 0).timestamp() * 1e9)
    ts3 = int(datetime(2024, 1, 4, 9, 30).timestamp() * 1e9)
    ts4 = int(datetime(2024, 1, 4, 10, 0).timestamp() * 1e9)

    EXPECTED_DAYS = 2
    TOP_K = 2

    bars = pd.DataFrame(
        {
            "ts": [ts1, ts2, ts3, ts4],
            "symbol": ["AAPL", "MSFT", "GOOGL", "AMZN"],
            "open": [149.5, 249.0, 119.0, 129.0],
            "high": [150.5, 251.0, 121.0, 131.0],
            "low": [149.0, 248.0, 118.0, 128.0],
            "close": [150.0, 250.0, 120.0, 130.0],
            "volume": [1000000, 800000, 1500000, 600000],
        }
    )

    selector = DailyHMMSIPSelector(score_floor=0.01, top_k=TOP_K)
    universe_map = selector.select_daily_universes(bars)

    # Should have universe for each trading day
    assert len(universe_map) == EXPECTED_DAYS
    # Each day should have top_k symbols
    for _, symbols in universe_map.items():
        assert len(symbols) <= TOP_K


def test_universe_broadcast_to_intraday() -> None:
    # Test that daily universe is broadcast to all intraday timestamps
    ts1 = int(datetime(2024, 1, 3, 9, 31).timestamp() * 1e9)
    ts2 = int(datetime(2024, 1, 3, 14, 30).timestamp() * 1e9)
    ts3 = int(datetime(2024, 1, 3, 15, 59).timestamp() * 1e9)

    bars = pd.DataFrame(
        {
            "ts": [ts1, ts2, ts3],
            "symbol": ["AAPL", "AAPL", "AAPL"],
            "open": [150.0, 151.0, 152.0],
            "high": [150.5, 151.5, 152.5],
            "low": [149.5, 150.5, 151.5],
            "close": [150.0, 151.0, 152.0],
            "volume": [100000, 120000, 90000],
        }
    )

    selector = DailyHMMSIPSelector(score_floor=0.01, top_k=1)
    # Mock daily universe selection
    selector._daily_universes = {datetime(2024, 1, 3).date(): {"AAPL"}}

    # All intraday bars should be eligible if symbol is in daily universe
    for _, row in bars.iterrows():
        ts_datetime = datetime.fromtimestamp(row["ts"] / 1e9)
        assert selector.is_symbol_eligible(row["symbol"], ts_datetime)


def test_get_universe_for_timestamp() -> None:
    """Test getting universe for specific timestamp"""
    selector = DailyHMMSIPSelector(score_floor=0.01, top_k=2)

    # Mock daily universe
    test_date = datetime(2024, 1, 3).date()
    selector._daily_universes = {test_date: {"AAPL", "MSFT"}}

    # Test timestamp within the day
    timestamp = datetime(2024, 1, 3, 10, 30)
    universe = selector.get_universe_for_timestamp(timestamp)
    assert universe == {"AAPL", "MSFT"}

    # Test timestamp for different day (should return empty set)
    different_day = datetime(2024, 1, 4, 10, 30)
    universe = selector.get_universe_for_timestamp(different_day)
    assert universe == set()
