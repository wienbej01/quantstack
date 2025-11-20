import pandas as pd
import pytest

from extensions.intraday_ml_policies.intraday_ml_decision_policy import IntradayMLDecisionPolicy


def _ts(time_str: str) -> pd.Timestamp:
    return (
        pd.Timestamp(f"2025-11-03 {time_str}", tz="America/New_York")
        .tz_convert("UTC")
    )


@pytest.fixture
def base_policy_config() -> dict:
    return {
        "prob_threshold_long": 0.6,
        "prob_threshold_short": 0.6,
        "cooldown_minutes": 0,
        "min_time": "09:30:00",
        "max_time": "16:00:00",
        "order_qty": 1,
        "session_timezone": "America/New_York",
        "risk": {
            "atr_feature": "atr",
            "support_feature_long": "low",
            "resistance_feature_short": "high",
            "max_atr_multiple": 1.0,
            "support_buffer_atr": 0.0,
            "target_r_multiple": 1.5,
            "min_stop_pct": 0.001,
            "max_stop_pct": 0.05,
            "min_expected_r": 1.0,
        },
    }


@pytest.fixture
def base_features() -> dict:
    return {
        "close": 100.0,
        "low": 99.5,
        "high": 100.5,
        "atr": 0.5,
    }


def _signal_row(symbol: str, timestamp: pd.Timestamp, probs: dict[str, float], base_features: dict) -> dict:
    row = {
        "symbol": symbol,
        "ts": timestamp,
        "prob_long": probs.get("prob_long", 0.0),
        "prob_short": probs.get("prob_short", 0.0),
        "prob_neutral": probs.get("prob_neutral", 0.0),
    }
    row.update(base_features)
    return row


def test_global_max_entries_is_enforced(base_policy_config, base_features):
    config = dict(base_policy_config)
    config.update(
        {
            "max_entries_per_day": 2,
            "max_open_positions_global": 5,
            "max_trades_per_symbol_per_day": 2,
            "max_trades_per_bar_global": 5,
        }
    )
    policy = IntradayMLDecisionPolicy(config)

    rows = [
        _signal_row(
            "AAA",
            _ts("10:00:00"),
            {"prob_long": 0.92, "prob_short": 0.03, "prob_neutral": 0.05},
            base_features,
        ),
        _signal_row(
            "BBB",
            _ts("10:10:00"),
            {"prob_long": 0.91, "prob_short": 0.04, "prob_neutral": 0.05},
            base_features,
        ),
        _signal_row(
            "CCC",
            _ts("10:20:00"),
            {"prob_long": 0.90, "prob_short": 0.05, "prob_neutral": 0.05},
            base_features,
        ),
    ]
    signals = pd.DataFrame(rows)

    orders, rejections = policy.process_signals(signals)

    assert len(orders) == 2
    assert set(orders["symbol"]) == {"AAA", "BBB"}
    assert "max_entries_reached_global" in set(rejections["reason"])


def test_process_signals_accumulates_entries_across_bars(base_policy_config, base_features):
    config = dict(base_policy_config)
    config.update(
        {
            "max_entries_per_day": 5,
            "max_open_positions_global": 5,
            "max_trades_per_symbol_per_day": 5,
            "max_trades_per_bar_global": 5,
        }
    )
    policy = IntradayMLDecisionPolicy(config)

    rows = [
        _signal_row(
            "AAA",
            _ts("10:00:00"),
            {"prob_long": 0.95, "prob_short": 0.02, "prob_neutral": 0.03},
            base_features,
        ),
        _signal_row(
            "BBB",
            _ts("10:10:00"),
            {"prob_long": 0.94, "prob_short": 0.03, "prob_neutral": 0.03},
            base_features,
        ),
        _signal_row(
            "CCC",
            _ts("10:20:00"),
            {"prob_long": 0.93, "prob_short": 0.04, "prob_neutral": 0.03},
            base_features,
        ),
    ]
    signals = pd.DataFrame(rows)

    orders, rejections = policy.process_signals(signals)

    assert len(orders) == 3
    assert rejections.empty
    assert set(orders["symbol"]) == {"AAA", "BBB", "CCC"}
    assert policy.global_entries_today == 3


def test_cross_sectional_ranking_and_bar_cap(base_policy_config, base_features):
    config = dict(base_policy_config)
    config.update(
        {
            "max_entries_per_day": 5,
            "max_open_positions_global": 1,
            "max_trades_per_symbol_per_day": 2,
            "max_trades_per_bar_global": 1,
        }
    )
    policy = IntradayMLDecisionPolicy(config)

    rows = [
        _signal_row(
            "AAA",
            _ts("11:00:00"),
            {"prob_long": 0.90, "prob_short": 0.04, "prob_neutral": 0.06},
            base_features,
        ),
        _signal_row(
            "BBB",
            _ts("11:00:00"),
            {"prob_long": 0.80, "prob_short": 0.10, "prob_neutral": 0.10},
            base_features,
        ),
        _signal_row(
            "CCC",
            _ts("11:00:00"),
            {"prob_long": 0.75, "prob_short": 0.15, "prob_neutral": 0.10},
            base_features,
        ),
    ]
    signals = pd.DataFrame(rows)

    orders, rejections = policy.process_signals(signals)

    assert len(orders) == 1
    assert orders.iloc[0]["symbol"] == "AAA"
    assert set(rejections["reason"]) == {"max_trades_per_bar_reached"}


def test_tod_profiles_gate_entries(base_policy_config, base_features):
    config = dict(base_policy_config)
    config.update(
        {
            "max_entries_per_day": 3,
            "max_open_positions_global": 2,
            "max_trades_per_symbol_per_day": 2,
            "tod_profiles": {
                "OPEN": {
                    "start_time": "09:30",
                    "end_time": "10:15",
                    "prob_threshold_long": 0.75,
                    "prob_threshold_short": 0.75,
                    "min_directional_gap_long": 0.08,
                    "min_directional_gap_short": 0.08,
                    "min_conviction_long": 0.02,
                    "min_conviction_short": 0.02,
                    "min_expected_r_long": 1.0,
                    "min_expected_r_short": 1.0,
                },
                "MID": {
                    "start_time": "10:15",
                    "end_time": "16:00",
                    "prob_threshold_long": 0.60,
                    "prob_threshold_short": 0.60,
                    "min_directional_gap_long": 0.05,
                    "min_directional_gap_short": 0.05,
                    "min_conviction_long": 0.0,
                    "min_conviction_short": 0.0,
                    "min_expected_r_long": 1.0,
                    "min_expected_r_short": 1.0,
                },
            },
        }
    )
    policy = IntradayMLDecisionPolicy(config)

    rows = [
        _signal_row(
            "XYZ",
            _ts("09:45:00"),
            {"prob_long": 0.68, "prob_short": 0.20, "prob_neutral": 0.12},
            base_features,
        ),
        _signal_row(
            "XYZ",
            _ts("10:30:00"),
            {"prob_long": 0.68, "prob_short": 0.20, "prob_neutral": 0.12},
            base_features,
        ),
    ]
    signals = pd.DataFrame(rows)

    orders, rejections = policy.process_signals(signals)

    assert len(orders) == 1
    assert orders.iloc[0]["timestamp"].tz_convert("America/New_York").hour == 10
    assert "below_threshold" in set(rejections["reason"])


def test_direction_specific_thresholds_hold(base_policy_config, base_features):
    config = dict(base_policy_config)
    config.update(
        {
            "max_entries_per_day": 3,
            "max_open_positions_global": 2,
            "max_trades_per_symbol_per_day": 2,
            "tod_profiles": {
                "FULL": {
                    "start_time": "09:30",
                    "end_time": "16:00",
                    "prob_threshold_long": 0.60,
                    "prob_threshold_short": 0.90,
                    "min_directional_gap_long": 0.05,
                    "min_directional_gap_short": 0.05,
                    "min_conviction_long": 0.0,
                    "min_conviction_short": 0.0,
                    "min_expected_r_long": 1.0,
                    "min_expected_r_short": 1.0,
                }
            },
        }
    )
    policy = IntradayMLDecisionPolicy(config)

    rows = [
        _signal_row(
            "LONG",
            _ts("12:00:00"),
            {"prob_long": 0.70, "prob_short": 0.20, "prob_neutral": 0.10},
            base_features,
        ),
        _signal_row(
            "SHORT",
            _ts("12:05:00"),
            {"prob_long": 0.05, "prob_short": 0.80, "prob_neutral": 0.15},
            base_features,
        ),
    ]
    signals = pd.DataFrame(rows)

    orders, rejections = policy.process_signals(signals)

    assert set(orders["symbol"]) == {"LONG"}
    assert "below_threshold" in set(rejections["reason"])


def _bigmove_signal(
    symbol: str,
    timestamp: pd.Timestamp,
    bigmove_prob: float,
    bigmove_long_prob: float,
    base_features: dict,
) -> dict:
    row = {
        "symbol": symbol,
        "ts": timestamp,
        "prob_bigmove": bigmove_prob,
        "prob_bigmove_long": bigmove_long_prob,
        "prob_bigmove_short": max(0.0, 1.0 - bigmove_long_prob),
        "expected_r_bigmove": 2.0,
    }
    row.update(base_features)
    return row


def test_bigmove_policy_blocks_low_probability_signals(base_policy_config, base_features):
    config = dict(base_policy_config)
    config.update(
        {
            "policy_mode": "bigmove",
            "bigmove_policy": {
                "probability_threshold": 0.55,
                "prob_column": "prob_bigmove",
                "long_prob_column": "prob_bigmove_long",
                "short_prob_column": "prob_bigmove_short",
                "expected_r_column": "expected_r_bigmove",
                "min_expected_r": 1.5,
            },
        }
    )
    policy = IntradayMLDecisionPolicy(config)
    signals = pd.DataFrame(
        [
            _bigmove_signal("AAA", _ts("10:00:00"), 0.5, 0.7, base_features),
        ]
    )

    orders, rejections = policy.process_signals(signals)

    assert orders.empty
    assert "bigmove_prob_below_threshold" in set(rejections["reason"])


def test_bigmove_policy_accepts_high_probability_signals(base_policy_config, base_features):
    config = dict(base_policy_config)
    config.update(
        {
            "policy_mode": "bigmove",
            "max_entries_per_day": 2,
            "max_open_positions_global": 2,
            "bigmove_policy": {
                "probability_threshold": 0.4,
                "prob_column": "prob_bigmove",
                "long_prob_column": "prob_bigmove_long",
                "short_prob_column": "prob_bigmove_short",
                "expected_r_column": "expected_r_bigmove",
                "min_expected_r": 1.5,
            },
        }
    )
    policy = IntradayMLDecisionPolicy(config)
    signals = pd.DataFrame(
        [
            _bigmove_signal("AAA", _ts("10:00:00"), 0.9, 0.8, base_features),
        ]
    )

    orders, rejections = policy.process_signals(signals)

    assert len(orders) == 1
    assert rejections.empty
