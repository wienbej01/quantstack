"""Test BacktestEngine daily universe update functionality."""

from datetime import date

import pytest
from qx_backtest.engine import BacktestConfig, BacktestEngine

EXPECTED_TRADING_DAYS = 2


def test_engine_daily_universe_updates() -> None:
    """Test that engine can detect and prepare daily universe updates."""
    # Create engine with daily HMM_SIP config (using dict config for now)
    config = BacktestConfig()
    engine = BacktestEngine(config)

    # Mock multi-day data as list of bars
    bars = [
        {"ts": 1704291000, "symbol": "AAPL", "close": 150.0},  # 2024-01-03 after open
        {"ts": 1704294600, "symbol": "MSFT", "close": 250.0},  # 2024-01-03 later
        {"ts": 1704377400, "symbol": "GOOGL", "close": 120.0},  # 2024-01-04 after open
    ]

    # This method should be implemented
    try:
        universe_updates = engine._get_daily_universe_updates(bars)
        assert (
            len(universe_updates) == EXPECTED_TRADING_DAYS
        )  # Should detect 2 trading days
        # The method should return empty sets that will be populated by SIP selector
        for universe in universe_updates.values():
            assert isinstance(universe, set)
    except AttributeError:
        pytest.fail(
            "_get_daily_universe_updates method not found - needs to be implemented"
        )


def test_engine_daily_universe_state_management() -> None:
    """Test that engine properly manages daily universe state."""
    config = BacktestConfig()
    engine = BacktestEngine(config)

    # Test _update_daily_universe method
    trading_date = date(2024, 1, 3)
    universe = {"AAPL", "MSFT"}

    try:
        engine._update_daily_universe(trading_date, universe)
        assert engine._daily_universes[trading_date] == universe
    except AttributeError:
        pytest.fail("_update_daily_universe method not found - needs to be implemented")


def test_engine_universe_update_check() -> None:
    """Test that engine can check if universe update is needed."""
    config = BacktestConfig()
    engine = BacktestEngine(config)

    # Set a processed date to test against
    engine._last_processed_date = date(2024, 1, 3)

    # Bar from same day - no update needed
    bar_same_day = {"ts": 1704291000, "symbol": "AAPL", "close": 150.0}  # 2024-01-03
    # Bar from next day - update needed
    bar_next_day = {"ts": 1704377400, "symbol": "GOOGL", "close": 120.0}  # 2024-01-04

    try:
        assert not engine._check_universe_update_needed(bar_same_day)
        assert engine._check_universe_update_needed(bar_next_day)
    except AttributeError:
        pytest.fail(
            "_check_universe_update_needed method not found - needs to be implemented"
        )


def test_engine_initializes_daily_universe_attributes() -> None:
    """Test that engine initializes daily universe tracking attributes."""
    config = BacktestConfig()
    engine = BacktestEngine(config)

    # After implementing, these attributes should exist
    required_attrs = ["_daily_universes", "_current_universe", "_last_processed_date"]

    for attr in required_attrs:
        if not hasattr(engine, attr):
            pytest.fail(
                f"Attribute {attr} not found - needs to be added to BacktestEngine.__init__"
            )
