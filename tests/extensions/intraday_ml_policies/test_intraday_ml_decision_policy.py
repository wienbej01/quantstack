#!/usr/bin/env python3
"""
Tests for the IntradayMLDecisionPolicy.
"""

import pandas as pd
import pytest

from extensions.intraday_ml_policies.intraday_ml_decision_policy import IntradayMLDecisionPolicy


@pytest.fixture
def sample_policy_config():
    """Returns a sample policy configuration."""
    return {
        "prob_threshold_long": 0.6,
        "prob_threshold_short": 0.6,
        "cooldown_minutes": 30,
        "min_time": "09:45:00",
        "max_time": "15:45:00",
        "stop_loss_pct": 0.01,
        "take_profit_pct": 0.015,
        "order_qty": 1,
    }


@pytest.fixture
def sample_signals():
    """Returns a sample DataFrame of signals."""
    data = {
        "timestamp": pd.to_datetime([
            "2025-11-03 09:30:00",
            "2025-11-03 09:50:00",
            "2025-11-03 10:00:00",
            "2025-11-03 10:15:00",
            "2025-11-03 16:00:00",
        ]),
        "symbol": ["TEST", "TEST", "TEST", "TEST", "TEST"],
        "prob_long": [0.7, 0.5, 0.8, 0.9, 0.95],
        "prob_short": [0.2, 0.4, 0.1, 0.05, 0.02],
    }
    return pd.DataFrame(data)


def test_policy_initialization(sample_policy_config):
    """Tests that the policy initializes correctly."""
    policy = IntradayMLDecisionPolicy(sample_policy_config)
    assert policy.prob_threshold_long == 0.6
    assert policy.cooldown_minutes == 30


def test_time_filter(sample_policy_config, sample_signals):
    """Tests the time filter logic."""
    policy = IntradayMLDecisionPolicy(sample_policy_config)
    orders, rejections = policy.process_signals(sample_signals)
    assert len(orders) == 1
    assert len(rejections) == 4
    assert rejections["reason"].tolist() == ["time_filter", "below_threshold", "cooldown", "time_filter"]


def test_probability_threshold(sample_policy_config, sample_signals):
    """Tests the probability threshold logic."""
    config = sample_policy_config.copy()
    config["prob_threshold_long"] = 0.75
    policy = IntradayMLDecisionPolicy(config)
    
    # Adjust signal timestamps to be within the time filter
    signals = sample_signals.copy()
    signals["timestamp"] = pd.to_datetime([
        "2025-11-03 10:00:00",
        "2025-11-03 10:10:00",
        "2025-11-03 10:20:00",
        "2025-11-03 10:30:00",
        "2025-11-03 10:40:00",
    ])
    signals["prob_long"] = [0.7, 0.5, 0.8, 0.9, 0.95]


    orders, rejections = policy.process_signals(signals)
    assert len(orders) == 1
    assert len(rejections) == 4
    assert rejections["reason"].tolist() == ["below_threshold", "below_threshold", "cooldown", "cooldown"]

def test_cooldown_logic(sample_policy_config, sample_signals):
    """Tests the cooldown logic."""
    policy = IntradayMLDecisionPolicy(sample_policy_config)
    
    signals = sample_signals.copy()
    signals["timestamp"] = pd.to_datetime([
        "2025-11-03 10:00:00", # First trade
        "2025-11-03 10:10:00", # Cooldown
        "2025-11-03 10:20:00", # Cooldown
        "2025-11-03 10:31:00", # Second trade
        "2025-11-03 11:00:00", # Cooldown
    ])
    signals["prob_long"] = 0.9 # Make all signals strong

    orders, rejections = policy.process_signals(signals)
    assert len(orders) == 2
    assert len(rejections) == 3
    assert rejections["reason"].tolist() == ["cooldown", "cooldown", "cooldown"]
    assert orders["timestamp"].iloc[0] == pd.to_datetime("2025-11-03 10:00:00")
    assert orders["timestamp"].iloc[1] == pd.to_datetime("2025-11-03 10:31:00")

def test_order_structure(sample_policy_config, sample_signals):
    """Tests that the generated orders have the correct structure."""
    policy = IntradayMLDecisionPolicy(sample_policy_config)
    orders, _ = policy.process_signals(sample_signals)
    
    expected_columns = ['timestamp', 'symbol', 'side', 'qty', 'stop_loss_pct', 'take_profit_pct', 'reason']
    assert all(col in orders.columns for col in expected_columns)
    
    order = orders.iloc[0]
    assert order["qty"] == 1
    assert order["stop_loss_pct"] == 0.01
    assert order["take_profit_pct"] == 0.015
    assert order["side"] == "long"
