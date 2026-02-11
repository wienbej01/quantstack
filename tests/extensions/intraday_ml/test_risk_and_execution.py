import pandas as pd
import pytest

from extensions.intraday_ml.backtest import _shift_to_next_bar
from extensions.intraday_ml.risk_levels import compute_risk_levels
from extensions.intraday_ml_policies.intraday_ml_decision_policy import (
    IntradayMLDecisionPolicy,
)


def _ts(time_str: str) -> pd.Timestamp:
    return pd.Timestamp(f"2025-11-03 {time_str}", tz="America/New_York").tz_convert(
        "UTC"
    )


def _base_policy_config() -> dict:
    return {
        "prob_threshold_long": 0.55,
        "prob_threshold_short": 0.55,
        "cooldown_minutes": 0,
        "min_time": "09:30:00",
        "max_time": "16:00:00",
        "order_qty": 1,
        "session_timezone": "America/New_York",
        "risk": {
            "atr_feature": "atr",
            "stop_atr_multiple": 0.5,
            "tp_r_multiple": 1.5,
            "min_stop_pct": 0.0005,
            "max_stop_pct": 0.05,
            "min_expected_r": 1.2,
        },
    }


def test_atr_based_stop_and_target_scaling():
    row = pd.Series({"close": 100.0, "atr": 0.5})
    cfg = {
        "price_column": "close",
        "atr_feature": "atr",
        "stop_atr_multiple": 2.0,
        "tp_r_multiple": 2.5,
        "min_stop_pct": 0.001,
        "max_stop_pct": 0.05,
    }
    levels = compute_risk_levels(row=row, side="long", config=cfg)
    assert levels is not None
    assert levels.stop_pct == pytest.approx((2.0 * 0.5) / 100.0, rel=1e-6)
    assert levels.take_profit_pct == pytest.approx(levels.stop_pct * 2.5, rel=1e-6)
    assert levels.expected_r == pytest.approx(2.5, rel=1e-6)


def test_early_loss_cut_exit_triggers():
    config = _base_policy_config()
    config.update(
        {
            "lifecycle": {
                "early_loss_cut_r": 0.5,
                "early_loss_cut_minutes": 30,
                "max_hold_minutes_flat_or_loser": 60,
                "max_hold_minutes_in_the_money": 180,
            }
        }
    )
    policy = IntradayMLDecisionPolicy(config)
    base = {"symbol": "AAA", "low": 99.0, "high": 101.0, "atr": 1.0}
    signals = pd.DataFrame(
        [
            {
                **base,
                "ts": _ts("10:00:00"),
                "prob_long": 0.9,
                "prob_short": 0.05,
                "prob_neutral": 0.05,
                "close": 100.0,
            },
            {
                **base,
                "ts": _ts("10:10:00"),
                "prob_long": 0.2,
                "prob_short": 0.6,
                "prob_neutral": 0.2,
                "close": 99.4,
            },
        ]
    )
    orders, _ = policy.process_signals(signals)
    assert len(orders) == 2
    assert "early_loss_cut" in orders.iloc[1]["reason"]


def test_dead_trade_exit_fires_with_flat_pnl():
    config = _base_policy_config()
    config.update(
        {
            "lifecycle": {
                "dead_trade_exit_minutes": 30,
                "dead_trade_pnl_band_r": 0.2,
                "max_hold_minutes_flat_or_loser": 60,
                "max_hold_minutes_in_the_money": 120,
            }
        }
    )
    policy = IntradayMLDecisionPolicy(config)
    base = {"symbol": "BBB", "low": 99.5, "high": 100.5, "atr": 1.0}
    signals = pd.DataFrame(
        [
            {
                **base,
                "ts": _ts("09:45:00"),
                "prob_long": 0.85,
                "prob_short": 0.05,
                "prob_neutral": 0.10,
                "close": 100.0,
            },
            {
                **base,
                "ts": _ts("10:30:00"),
                "prob_long": 0.4,
                "prob_short": 0.3,
                "prob_neutral": 0.30,
                "close": 100.05,
            },
        ]
    )
    orders, _ = policy.process_signals(signals)
    assert len(orders) == 2
    assert orders.iloc[1]["reason"] == "dead_trade_exit"


def test_profitable_trade_is_allowed_to_run_past_flat_hold_limit():
    config = _base_policy_config()
    config.update(
        {
            "lifecycle": {
                "max_hold_minutes_flat_or_loser": 60,
                "max_hold_minutes_in_the_money": 180,
            }
        }
    )
    policy = IntradayMLDecisionPolicy(config)
    base = {"symbol": "RUN", "low": 99.5, "high": 101.0, "atr": 1.0}
    signals = pd.DataFrame(
        [
            {
                **base,
                "ts": _ts("09:40:00"),
                "prob_long": 0.9,
                "prob_short": 0.05,
                "prob_neutral": 0.05,
                "close": 100.0,
            },
            {
                **base,
                "ts": _ts("10:30:00"),
                "prob_long": 0.8,
                "prob_short": 0.05,
                "prob_neutral": 0.15,
                "close": 100.7,
            },
            {
                **base,
                "ts": _ts("11:20:00"),
                "prob_long": 0.75,
                "prob_short": 0.05,
                "prob_neutral": 0.2,
                "close": 100.8,
            },
        ]
    )
    orders, rejections = policy.process_signals(signals)
    assert len(orders) == 1
    assert not rejections.empty
    assert "holding_long" in set(rejections["reason"])
    assert any(key[0] == "RUN" for key in policy.position_state)


def test_time_stop_triggers_for_losing_trade_at_flat_hold_limit():
    config = _base_policy_config()
    config.update(
        {
            "lifecycle": {
                "max_hold_minutes_flat_or_loser": 30,
                "max_hold_minutes_in_the_money": 90,
            }
        }
    )
    policy = IntradayMLDecisionPolicy(config)
    base = {"symbol": "LOS", "low": 98.5, "high": 101.0, "atr": 1.0}
    signals = pd.DataFrame(
        [
            {
                **base,
                "ts": _ts("09:40:00"),
                "prob_long": 0.85,
                "prob_short": 0.05,
                "prob_neutral": 0.10,
                "close": 100.0,
            },
            {
                **base,
                "ts": _ts("10:05:00"),
                "prob_long": 0.6,
                "prob_short": 0.1,
                "prob_neutral": 0.3,
                "close": 99.7,
            },
            {
                **base,
                "ts": _ts("10:15:00"),
                "prob_long": 0.55,
                "prob_short": 0.2,
                "prob_neutral": 0.25,
                "close": 99.6,
            },
        ]
    )
    orders, _ = policy.process_signals(signals)
    assert len(orders) == 2
    assert orders.iloc[1]["reason"] == "time_stop"


def test_daily_risk_budget_blocks_new_entries():
    config = _base_policy_config()
    config.update(
        {
            "max_daily_loss_R": -1.0,
            "lifecycle": {
                "max_hold_minutes_flat_or_loser": 30,
                "max_hold_minutes_in_the_money": 120,
            },
        }
    )
    policy = IntradayMLDecisionPolicy(config)
    base = {"symbol": "CCC", "low": 99.0, "high": 101.0, "atr": 1.0}
    signals = pd.DataFrame(
        [
            {
                **base,
                "ts": _ts("10:00:00"),
                "prob_long": 0.9,
                "prob_short": 0.05,
                "prob_neutral": 0.05,
                "close": 100.0,
            },
            {
                **base,
                "ts": _ts("10:10:00"),
                "prob_long": 0.1,
                "prob_short": 0.8,
                "prob_neutral": 0.1,
                "close": 99.0,
            },
            {
                **base,
                "symbol": "DDD",
                "ts": _ts("11:00:00"),
                "prob_long": 0.9,
                "prob_short": 0.05,
                "prob_neutral": 0.05,
                "close": 100.0,
            },
        ]
    )
    orders, rejections = policy.process_signals(signals)
    assert len(orders) == 2
    assert "risk_budget_exhausted" in set(rejections["reason"])


def test_daily_risk_budget_blocks_after_hits():
    config = _base_policy_config()
    config.update(
        {
            "max_daily_loss_R": -0.6,
            "trade_risk_R": 0.3,
            "lifecycle": {
                "early_loss_cut_r": 0.4,
                "early_loss_cut_minutes": 30,
                "max_hold_minutes_flat_or_loser": 60,
                "max_hold_minutes_in_the_money": 180,
            },
        }
    )
    policy = IntradayMLDecisionPolicy(config)
    base = {"low": 99.0, "high": 101.0, "atr": 1.0, "prob_neutral": 0.05}

    # Seed state to the current trading day and simulate a realized drawdown.
    policy.process_signals(
        pd.DataFrame(
            [
                {
                    **base,
                    "symbol": "AAA",
                    "ts": _ts("09:40:00"),
                    "prob_long": 0.9,
                    "prob_short": 0.05,
                    "close": 100.0,
                }
            ]
        )
    )
    policy.position_state.clear()
    policy.daily_realized_r = -0.7

    signals = pd.DataFrame(
        [
            {
                **base,
                "symbol": "DDD",
                "ts": _ts("11:00:00"),
                "prob_long": 0.9,
                "prob_short": 0.05,
                "close": 100.0,
            },
            {
                **base,
                "symbol": "EEE",
                "ts": _ts("10:00:00") + pd.Timedelta(days=1),
                "prob_long": 0.9,
                "prob_short": 0.05,
                "close": 100.0,
            },
        ]
    )

    orders, rejections = policy.process_signals(signals)

    assert len(orders) == 1
    assert orders.iloc[0]["symbol"] == "EEE"
    assert "risk_budget_exhausted" in set(rejections["reason"])


def test_shift_to_next_bar_applies_slippage():
    bars = pd.DataFrame(
        [
            {"symbol": "AAA", "ts": _ts("09:30:00"), "open": 100.0},
            {"symbol": "AAA", "ts": _ts("09:31:00"), "open": 101.0},
            {"symbol": "AAA", "ts": _ts("09:32:00"), "open": 102.0},
        ]
    )
    orders = pd.DataFrame(
        [
            {"symbol": "AAA", "ts": _ts("09:30:00"), "side": "long"},
            {"symbol": "AAA", "ts": _ts("09:31:00"), "side": "short"},
        ]
    )
    shifted = _shift_to_next_bar(orders, bars, slippage_bps=5)
    assert len(shifted) == 2
    long_fill = shifted.iloc[0]["fill_price"]
    short_fill = shifted.iloc[1]["fill_price"]
    assert long_fill == pytest.approx(101.0 * (1 + 0.0005), rel=1e-9)
    assert short_fill == pytest.approx(102.0 * (1 - 0.0005), rel=1e-9)
