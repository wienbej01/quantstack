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
        "risk": {
            "atr_feature": "atr",
            "stop_atr_multiple": 0.5,
            "tp_r_multiple": 1.5,
            "min_stop_pct": 0.0005,
            "max_stop_pct": 0.05,
            "min_expected_r": 1.5,
        },
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
        "prob_neutral": [0.1, 0.1, 0.1, 0.05, 0.03],
        "close": [100.0, 100.0, 100.0, 100.0, 100.0],
        "low": [99.9, 99.9, 99.9, 99.9, 99.9],
        "high": [100.1, 100.1, 100.1, 100.1, 100.1],
        "atr": [0.2, 0.2, 0.2, 0.2, 0.2],
    }
    return pd.DataFrame(data)


def _tz_timestamp(time_str: str) -> pd.Timestamp:
    return (
        pd.Timestamp(f"2025-11-03 {time_str}", tz="America/New_York")
        .tz_convert("UTC")
    )


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
    assert first_order_time == pd.Timestamp("2025-11-03 10:00:00", tz="America/New_York")
    assert second_order_time == pd.Timestamp("2025-11-03 11:00:00", tz="America/New_York")


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
    assert pytest.approx(order["stop_loss_pct"], rel=1e-6) == 0.001
    assert pytest.approx(order["take_profit_pct"], rel=1e-6) == 0.0015
    assert order["side"] == "long"
    assert pytest.approx(order["risk_r_multiple"], rel=1e-6) == 1.5
    assert pytest.approx(order["expected_r"], rel=1e-6) == 1.5


def test_expected_r_gate_blocks_low_payoff(sample_policy_config, sample_signals):
    """Ensure entries fail when expected R falls below the configured floor."""
    config = sample_policy_config.copy()
    config["risk"] = dict(config["risk"])
    config["risk"]["min_expected_r"] = 2.0
    policy = IntradayMLDecisionPolicy(config)

    signals = sample_signals.copy().head(1)
    signals["ts"] = [pd.Timestamp("2025-11-03 10:00:00", tz="America/New_York").tz_convert("UTC")]
    signals["prob_long"] = 0.95

    orders, rejections = policy.process_signals(signals)
    assert orders.empty
    assert "expected_r_low" in rejections["reason"].tolist()


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
    config["risk"] = {
        "atr_feature": "atr",
        "support_feature_long": "low",
        "resistance_feature_short": "high",
        "max_atr_multiple": 1.0,
        "support_buffer_atr": 0.0,
        "target_r_multiple": 1.5,
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
            "low": [100.3],
            "high": [100.7],
            "atr": [0.25],
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
    config["risk"] = {
        "atr_feature": "atr",
        "support_feature_long": "low",
        "resistance_feature_short": "high",
        "max_atr_multiple": 1.0,
        "support_buffer_atr": 0.0,
        "target_r_multiple": 1.5,
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
            "low": [97.8],
            "high": [98.2],
            "atr": [0.2],
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

    entry_ts = pd.Timestamp("2025-11-03 10:00:00", tz="America/New_York").tz_convert("UTC")
    exit_ts = pd.Timestamp("2025-11-03 16:00:00", tz="America/New_York").tz_convert("UTC")

    signals = pd.DataFrame(
        {
            "ts": [entry_ts, exit_ts],
            "symbol": ["TEST", "TEST"],
            "prob_long": [0.85, 0.4],
            "prob_short": [0.1, 0.2],
            "prob_neutral": [0.05, 0.4],
            "close": [100.0, 100.2],
            "low": [99.9, 100.0],
            "high": [100.1, 100.3],
            "atr": [0.2, 0.2],
        }
    )

    orders, rejections = policy.process_signals(signals)
    assert len(orders) == 2
    assert orders.iloc[0]["side"] == "long"
    assert orders.iloc[1]["reason"] == "force_flat"
    assert rejections.empty


def test_process_signals_accumulates_entries(sample_policy_config):
    """Every decision bar contributes its accepted entries before advancing."""
    config = dict(sample_policy_config)
    config.update(
        {
            "cooldown_minutes": 0,
            "min_time": "09:30:00",
            "max_time": "16:00:00",
            "session_timezone": "America/New_York",
            "max_entries_per_day": 5,
            "max_open_positions_global": 5,
            "max_trades_per_symbol_per_day": 5,
            "max_trades_per_bar_global": 5,
            "risk": {
                "atr_feature": "atr",
                "stop_atr_multiple": 1.0,
                "tp_r_multiple": 2.0,
                "min_stop_pct": 0.001,
                "max_stop_pct": 0.05,
                "min_expected_r": 1.2,
            },
        }
    )
    policy = IntradayMLDecisionPolicy(config)
    base = {"low": 99.5, "high": 100.5, "atr": 0.5, "prob_short": 0.05, "prob_neutral": 0.05}
    signals = pd.DataFrame(
        [
            {"symbol": "AAA", "ts": _tz_timestamp("10:00:00"), "prob_long": 0.9, "close": 100.0, **base},
            {"symbol": "BBB", "ts": _tz_timestamp("10:10:00"), "prob_long": 0.9, "close": 100.0, **base},
            {"symbol": "CCC", "ts": _tz_timestamp("10:20:00"), "prob_long": 0.9, "close": 100.0, **base},
        ]
    )

    orders, rejections = policy.process_signals(signals)

    assert len(orders) == 3
    assert rejections.empty
    assert set(orders["symbol"]) == {"AAA", "BBB", "CCC"}


def test_required_feature_columns_exposed():
    """Required feature columns are exposed for upstream orchestration."""

    policy = IntradayMLDecisionPolicy({"enabled_strategies": ["momentum", "value_rotation"]})
    columns = policy.get_required_feature_columns()

    assert "f__anchor__session_avwap" in columns
    assert "f__profile__poc" in columns
    assert "close" in columns
    assert "f__vol__atr_6" in columns
    assert "low" in columns
    assert "high" in columns
