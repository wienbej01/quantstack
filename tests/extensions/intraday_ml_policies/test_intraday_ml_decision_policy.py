#!/usr/bin/env python3
"""
Tests for the IntradayMLDecisionPolicy.
"""

import pandas as pd
import pytest

from extensions.intraday_ml_policies.intraday_ml_decision_policy import (
    IntradayMLDecisionPolicy,
)


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
        "enabled_strategies": [],
    }


@pytest.fixture
def sample_signals():
    """Returns a sample DataFrame of signals."""
    base_times = (
        pd.to_datetime(
            [
                "2025-11-03 09:30:00",
                "2025-11-03 09:50:00",
                "2025-11-03 10:00:00",
                "2025-11-03 10:15:00",
                "2025-11-03 15:50:00",
            ]
        )
        .tz_localize("America/New_York")
        .tz_convert("UTC")
    )

    data = {
        "ts": base_times,
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
    assert rejections["reason"].tolist() == [
        "time_filter",
        "below_threshold",
        "cooldown",
        "time_filter",
    ]


def test_probability_threshold(sample_policy_config, sample_signals):
    """Tests the probability threshold logic."""
    config = sample_policy_config.copy()
    config["prob_threshold_long"] = 0.75
    policy = IntradayMLDecisionPolicy(config)

    # Adjust signal timestamps to be within the time filter
    signals = sample_signals.copy()
    signals["ts"] = [
        pd.Timestamp("2025-11-03 10:00:00", tz="America/New_York").tz_convert("UTC"),
        pd.Timestamp("2025-11-03 10:10:00", tz="America/New_York").tz_convert("UTC"),
        pd.Timestamp("2025-11-03 10:20:00", tz="America/New_York").tz_convert("UTC"),
        pd.Timestamp("2025-11-03 10:30:00", tz="America/New_York").tz_convert("UTC"),
        pd.Timestamp("2025-11-03 10:40:00", tz="America/New_York").tz_convert("UTC"),
    ]
    signals["prob_long"] = [0.7, 0.5, 0.8, 0.9, 0.95]

    orders, rejections = policy.process_signals(signals)
    assert len(orders) == 1
    assert len(rejections) == 4
    assert rejections["reason"].tolist() == [
        "below_threshold",
        "below_threshold",
        "cooldown",
        "cooldown",
    ]


def test_cooldown_logic(sample_policy_config, sample_signals):
    """Tests the cooldown logic."""
    policy = IntradayMLDecisionPolicy(sample_policy_config)

    signals = sample_signals.copy()
    signals["ts"] = [
        pd.Timestamp("2025-11-03 10:00:00", tz="America/New_York").tz_convert("UTC"),
        pd.Timestamp("2025-11-03 10:10:00", tz="America/New_York").tz_convert("UTC"),
        pd.Timestamp("2025-11-03 10:20:00", tz="America/New_York").tz_convert("UTC"),
        pd.Timestamp("2025-11-03 10:31:00", tz="America/New_York").tz_convert("UTC"),
        pd.Timestamp("2025-11-03 11:00:00", tz="America/New_York").tz_convert("UTC"),
    ]
    signals["prob_long"] = 0.9  # Make all signals strong

    orders, rejections = policy.process_signals(signals)
    assert len(orders) == 2
    assert len(rejections) == 3
    assert rejections["reason"].tolist() == ["cooldown", "cooldown", "holding_long"]
    first_order_time = orders["timestamp"].iloc[0].tz_convert("America/New_York")
    second_order_time = orders["timestamp"].iloc[1].tz_convert("America/New_York")
    assert first_order_time == pd.Timestamp(
        "2025-11-03 10:00:00", tz="America/New_York"
    )
    assert second_order_time == pd.Timestamp(
        "2025-11-03 11:00:00", tz="America/New_York"
    )


def test_order_structure(sample_policy_config, sample_signals):
    """Tests that the generated orders have the correct structure."""
    policy = IntradayMLDecisionPolicy(sample_policy_config)
    orders, _ = policy.process_signals(sample_signals)

    expected_columns = [
        "ts",
        "timestamp",
        "symbol",
        "side",
        "qty",
        "stop_loss_pct",
        "take_profit_pct",
        "reason",
        "strategy",
        "strategy_detail",
    ]
    assert all(col in orders.columns for col in expected_columns)

    order = orders.iloc[0]
    assert order["qty"] == 1
    assert order["stop_loss_pct"] == 0.01
    assert order["take_profit_pct"] == 0.015
    assert order["side"] == "long"


def test_strategy_check_momentum_valid():
    """Ensure momentum strategy validation gates entries based on features."""
    config = {
        "prob_threshold_long": 0.55,
        "prob_threshold_short": 0.55,
        "cooldown_minutes": 0,
        "min_time": "09:45:00",
        "max_time": "15:45:00",
        "stop_loss_pct": 0.01,
        "take_profit_pct": 0.015,
        "order_qty": 1,
        "enabled_strategies": ["momentum"],
    }
    policy = IntradayMLDecisionPolicy(config)

    ts = pd.Timestamp("2025-11-03 10:00:00", tz="America/New_York").tz_convert("UTC")
    signals = pd.DataFrame(
        {
            "ts": [ts],
            "symbol": ["TEST"],
            "prob_long": [0.8],
            "prob_short": [0.1],
            "prob_neutral": [0.1],
            "close": [100.5],
            "f__anchor__session_avwap": [99.8],
            "f__regime__current": ["BULL"],
            "f__regime__var_ratio_10_60": [1.4],
            "f__regime__adx_proxy_14": [30.0],
        }
    )

    orders, rejections = policy.process_signals(signals)
    assert len(orders) == 1
    assert orders.iloc[0]["strategy"] == "momentum"
    assert rejections.empty


def test_strategy_check_failure_blocks_trade():
    """Strategy checks reject trades when feature conditions fail."""
    config = {
        "prob_threshold_long": 0.55,
        "prob_threshold_short": 0.55,
        "cooldown_minutes": 0,
        "min_time": "09:45:00",
        "max_time": "15:45:00",
        "stop_loss_pct": 0.01,
        "take_profit_pct": 0.015,
        "order_qty": 1,
        "enabled_strategies": ["momentum"],
    }
    policy = IntradayMLDecisionPolicy(config)

    ts = pd.Timestamp("2025-11-03 10:00:00", tz="America/New_York").tz_convert("UTC")
    signals = pd.DataFrame(
        {
            "ts": [ts],
            "symbol": ["TEST"],
            "prob_long": [0.85],
            "prob_short": [0.05],
            "prob_neutral": [0.1],
            "close": [98.0],  # Below AVWAP -> fails momentum criteria
            "f__anchor__session_avwap": [99.8],
            "f__regime__current": ["BULL"],
            "f__regime__var_ratio_10_60": [1.4],
            "f__regime__adx_proxy_14": [30.0],
        }
    )

    orders, rejections = policy.process_signals(signals)
    assert orders.empty
    assert len(rejections) == 1
    assert rejections.iloc[0]["reason"].startswith("strategy_check:")


def test_force_flat_generates_exit(sample_policy_config):
    """Positions are forced flat at the configured cutoff time."""
    config = sample_policy_config.copy()
    config.update(
        {
            "enabled_strategies": [],
            "max_time": "16:00:00",
            "force_flat_time": "15:59:59",
        }
    )
    policy = IntradayMLDecisionPolicy(config)

    entry_ts = pd.Timestamp("2025-11-03 10:00:00", tz="America/New_York").tz_convert(
        "UTC"
    )
    exit_ts = pd.Timestamp("2025-11-03 16:00:00", tz="America/New_York").tz_convert(
        "UTC"
    )

    signals = pd.DataFrame(
        {
            "ts": [entry_ts, exit_ts],
            "symbol": ["TEST", "TEST"],
            "prob_long": [0.85, 0.4],
            "prob_short": [0.1, 0.2],
            "prob_neutral": [0.05, 0.4],
        }
    )

    orders, rejections = policy.process_signals(signals)
    assert len(orders) == 2
    assert orders.iloc[0]["side"] == "long"
    assert orders.iloc[1]["reason"] == "force_flat"
    assert rejections.empty


def test_required_feature_columns_exposed():
    """Required feature columns are exposed for upstream orchestration."""

    policy = IntradayMLDecisionPolicy(
        {"enabled_strategies": ["momentum", "value_rotation"]}
    )
    columns = policy.get_required_feature_columns()

    assert "f__anchor__session_avwap" in columns
    assert "f__profile__poc" in columns
