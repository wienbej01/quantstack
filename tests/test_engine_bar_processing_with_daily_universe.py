"""Tests for engine bar processing with daily universe filtering."""

from datetime import datetime
from typing import Any

from qx_backtest.engine import BacktestConfig, BacktestEngine

# Test constants
EXPECTED_BARS_IN_UNIVERSE = 1
EXPECTED_BARS_ALL_MODES = 2


def test_bar_processing_respects_daily_universe() -> None:
    """Test that engine only processes bars for symbols in daily universe."""
    # Create engine with daily HMM_SIP configuration
    sip_config: dict[str, Any] = {
        "sip_method": "hmm",
        "sip_config": {"mode": "daily", "top_k": 1},
    }

    engine = BacktestEngine(BacktestConfig(), sip_config)

    # Mock daily universe with only AAPL
    trading_date = datetime(2024, 1, 3).date()
    engine._last_processed_date = trading_date  # Set the date first
    engine._update_daily_universe(trading_date, {"AAPL"})

    # Process bars for AAPL (in universe) and MSFT (not in universe)
    bars = [
        {"ts": 1704291000, "symbol": "AAPL", "close": 150.0},  # Should be processed
        {"ts": 1704291000, "symbol": "MSFT", "close": 250.0},  # Should be skipped
    ]

    processed_bars = []
    for bar in bars:
        if engine._should_process_bar(bar):
            processed_bars.append(bar)

    assert len(processed_bars) == EXPECTED_BARS_IN_UNIVERSE
    assert processed_bars[0]["symbol"] == "AAPL"


def test_non_hmm_mode_processes_all_bars() -> None:
    """Test that non-HMM modes process all bars regardless of universe."""
    # Create engine without HMM configuration
    sip_config: dict[str, Any] = {}  # Empty config should default to processing all bars
    engine = BacktestEngine(BacktestConfig(), sip_config)

    # Mock daily universe (should be ignored in non-HMM mode)
    trading_date = datetime(2024, 1, 3).date()
    engine._last_processed_date = trading_date
    engine._update_daily_universe(trading_date, {"AAPL"})

    # Process bars for AAPL and MSFT
    bars = [
        {"ts": 1704291000, "symbol": "AAPL", "close": 150.0},
        {"ts": 1704291000, "symbol": "MSFT", "close": 250.0},
    ]

    processed_bars = []
    for bar in bars:
        if engine._should_process_bar(bar):
            processed_bars.append(bar)

    # Both bars should be processed in non-HMM mode
    assert len(processed_bars) == EXPECTED_BARS_ALL_MODES


def test_legacy_hmm_mode_processes_all_bars() -> None:
    """Test that legacy HMM mode processes all bars."""
    # Create engine with legacy HMM configuration
    sip_config: dict[str, Any] = {"sip_method": "hmm", "sip_config": {"mode": "legacy", "top_k": 1}}
    engine = BacktestEngine(BacktestConfig(), sip_config)

    # Mock daily universe (should be ignored in legacy mode)
    trading_date = datetime(2024, 1, 3).date()
    engine._last_processed_date = trading_date
    engine._update_daily_universe(trading_date, {"AAPL"})

    # Process bars for AAPL and MSFT
    bars = [
        {"ts": 1704291000, "symbol": "AAPL", "close": 150.0},
        {"ts": 1704291000, "symbol": "MSFT", "close": 250.0},
    ]

    processed_bars = []
    for bar in bars:
        if engine._should_process_bar(bar):
            processed_bars.append(bar)

    # Both bars should be processed in legacy mode
    assert len(processed_bars) == EXPECTED_BARS_ALL_MODES
