#!/usr/bin/env python3
"""
Tests for Sprint E backtest adapter extensions.
"""

from unittest.mock import Mock, patch

import pandas as pd
import pytest

from extensions.intraday_ml.backtest import intraday_ml_run_backtest


@pytest.fixture
def sample_bars():
    """Returns a sample DataFrame of bars."""
    data = {
        "ts": pd.to_datetime(["2025-11-03 10:00:00", "2025-11-03 10:01:00", "2025-11-03 10:02:00"]),
        "symbol": ["TEST", "TEST", "TEST"],
        "open": [100, 101, 102],
        "high": [101, 102, 103],
        "low": [99, 100, 101],
        "close": [100.5, 101.5, 102.5],
        "volume": [1000, 1100, 1200],
    }
    return pd.DataFrame(data)


@pytest.fixture
def sample_orders():
    """Returns a sample DataFrame of orders with SL/TP."""
    data = {
        "ts": pd.to_datetime(["2025-11-03 10:00:00"]),
        "symbol": ["TEST"],
        "side": ["long"],
        "qty": [1],
        "stop_loss_pct": [0.01],
        "take_profit_pct": [0.015],
    }
    return pd.DataFrame(data)


@patch("qx_backtest.engine.BacktestEngine")
def test_sl_tp_and_single_position_guard(mock_engine_class, sample_bars, sample_orders):
    """Tests that SL/TP are calculated correctly and the single position guard works."""
    # Mock the engine instance and its methods
    mock_engine = Mock()
    mock_engine_class.return_value = mock_engine
    
    # Side effect for get_position to simulate position changes
    positions = {}
    def get_position_side_effect(symbol):
        return positions.get(symbol)

    def submit_order_side_effect(order):
        positions[order.symbol] = {"symbol": order.symbol, "qty": order.quantity}

    mock_engine.get_position.side_effect = get_position_side_effect
    mock_engine.submit_order.side_effect = submit_order_side_effect

    # Mock the run result
    mock_result = Mock()
    mock_result.metrics = {}
    mock_result.equity_curve = pd.DataFrame({'timestamp': [], 'equity': []})
    mock_result.positions_history = []
    mock_result.trades_history = []
    mock_result.orders_history = []
    mock_result.fills_history = []

    def simulate_run(bars, strategy):
        for _, bar in bars.iterrows():
            bar_dict = bar.to_dict()
            strategy(mock_engine, bar_dict)
        return mock_result

    mock_engine.run.side_effect = simulate_run

    # Add a second order that should be blocked by the guard
    second_order = sample_orders.copy()
    second_order["ts"] = pd.to_datetime(["2025-11-03 10:01:00"])
    orders = pd.concat([sample_orders, second_order], ignore_index=True)

    # Run the backtest
    intraday_ml_run_backtest(sample_bars, orders, cfg={})

    # Check that submit_order was called only once
    assert mock_engine.submit_order.call_count == 1

    # Check the submitted order
    submitted_order = mock_engine.submit_order.call_args[0][0]
    assert submitted_order.symbol == "TEST"
    assert submitted_order.quantity == 1
    
    # The order is at 10:00:00, but next_bar_execution shifts it to 10:01:00.
    # The strategy wrapper will be called with the 10:01:00 bar.
    # The close of that bar is 101.5.
    
    expected_sl = 101.5 * (1 - 0.01)
    expected_tp = 101.5 * (1 + 0.015)

    assert submitted_order.stop_loss == pytest.approx(expected_sl)
    assert submitted_order.take_profit == pytest.approx(expected_tp)
