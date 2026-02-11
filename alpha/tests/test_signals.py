"""Tests for trading signals.

Tests verify signal entry/exit logic with valid and invalid conditions.
Uses synthetic data for signals since we need specific feature values.
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from src.signals.base import Position, SignalSide
from src.signals.liquidity_fade import LiquidityFadeSignal
from src.signals.order_flow import OrderFlowSignal
from src.signals.whale_detect import WhaleDetectSignal

# Default configuration
DEFAULT_CONFIG = {
    "signals": {
        "order_flow": {
            "book_imbalance_threshold": 0.35,
            "trade_imbalance_threshold": 0.25,
            "max_spread_pct": 0.05,
            "target_pct": 0.4,
            "stop_pct": 0.25,
            "time_limit_minutes": 10,
        },
        "whale_detect": {
            "large_order_mult": 5.0,
            "min_rvol": 1.5,
            "min_flow_imb": 0.1,
            "target_pct": 0.8,
            "stop_pct": 0.4,
            "time_limit_minutes": 30,
        },
        "liquidity_fade": {
            "depth_drop_threshold": 0.5,
            "price_spike_pct": 0.2,
            "target_pct": 0.3,
            "stop_pct": 0.3,
            "time_limit_minutes": 5,
        },
    },
}


@pytest.fixture
def sample_bar():
    """Create sample bar data."""
    return pd.Series(
        {
            "ts": pd.Timestamp("2024-01-02 10:00:00"),
            "symbol": "AAPL",
            "open": 150.0,
            "high": 150.5,
            "low": 149.5,
            "close": 150.25,
            "volume": 10000,
        }
    )


class TestOrderFlowSignal:
    """Tests for H1: Order Flow Imbalance Signal."""

    def test_entry_long_valid_conditions(self, sample_bar):
        """Entry fires on valid LONG conditions."""
        signal = OrderFlowSignal(DEFAULT_CONFIG)

        # Valid LONG conditions
        features = {
            "book_imbalance_5": 0.5,  # > 0.35 threshold
            "trade_imbalance_5": 0.4,  # > 0.25 threshold
            "spread": 0.05,  # Tight spread
        }

        result = signal.check_entry(
            features,
            sample_bar,
            sample_bar["ts"],
        )

        assert result is not None
        assert result.side == SignalSide.LONG
        assert result.confidence > 0

    def test_entry_short_valid_conditions(self, sample_bar):
        """Entry fires on valid SHORT conditions."""
        signal = OrderFlowSignal(DEFAULT_CONFIG)

        # Valid SHORT conditions
        features = {
            "book_imbalance_5": -0.5,  # < -0.35 threshold
            "trade_imbalance_5": -0.4,  # < -0.25 threshold
            "spread": 0.05,  # Tight spread
        }

        result = signal.check_entry(
            features,
            sample_bar,
            sample_bar["ts"],
        )

        assert result is not None
        assert result.side == SignalSide.SHORT
        assert result.confidence > 0

    def test_no_entry_weak_imbalance(self, sample_bar):
        """No entry on weak imbalance (below threshold)."""
        signal = OrderFlowSignal(DEFAULT_CONFIG)

        # Weak conditions (below threshold)
        features = {
            "book_imbalance_5": 0.3,  # < 0.35 threshold
            "trade_imbalance_5": 0.4,
            "spread": 0.05,
        }

        result = signal.check_entry(
            features,
            sample_bar,
            sample_bar["ts"],
        )

        assert result is None

    def test_no_entry_wide_spread(self, sample_bar):
        """No entry when spread is too wide."""
        signal = OrderFlowSignal(DEFAULT_CONFIG)

        # Wide spread
        features = {
            "book_imbalance_5": 0.5,
            "trade_imbalance_5": 0.4,
            "spread": 0.20,  # 0.13% spread > 0.05% threshold
        }

        result = signal.check_entry(
            features,
            sample_bar,
            sample_bar["ts"],
        )

        assert result is None

    def test_exit_target_hit(self, sample_bar):
        """Exit on target hit."""
        signal = OrderFlowSignal(DEFAULT_CONFIG)

        # Create a LONG position
        position = Position(
            symbol="AAPL",
            side=SignalSide.LONG,
            entry_price=150.0,
            entry_time=sample_bar["ts"] - timedelta(minutes=5),
            quantity=100,
            target_price=150.6,  # 0.4% above
            stop_price=149.625,  # 0.25% below
            time_limit_minutes=10,
            signal_name="OrderFlowSignal",
        )

        # Bar that hits target
        bar = sample_bar.copy()
        bar["high"] = 150.7  # Above target
        bar["low"] = 149.8

        result = signal.check_exit(
            position,
            {},
            bar,
            bar["ts"],
        )

        assert result is not None
        assert result.reason == "target"

    def test_exit_stop_hit(self, sample_bar):
        """Exit on stop loss hit."""
        signal = OrderFlowSignal(DEFAULT_CONFIG)

        # Create a LONG position
        position = Position(
            symbol="AAPL",
            side=SignalSide.LONG,
            entry_price=150.0,
            entry_time=sample_bar["ts"] - timedelta(minutes=5),
            quantity=100,
            target_price=150.6,
            stop_price=149.625,
            time_limit_minutes=10,
            signal_name="OrderFlowSignal",
        )

        # Bar that hits stop
        bar = sample_bar.copy()
        bar["high"] = 150.1
        bar["low"] = 149.5  # Below stop

        result = signal.check_exit(
            position,
            {},
            bar,
            bar["ts"],
        )

        assert result is not None
        assert result.reason == "stop"

    def test_exit_time_limit(self, sample_bar):
        """Exit on time limit."""
        signal = OrderFlowSignal(DEFAULT_CONFIG)

        # Create a LONG position
        entry_time = sample_bar["ts"] - timedelta(minutes=11)  # Over limit
        position = Position(
            symbol="AAPL",
            side=SignalSide.LONG,
            entry_price=150.0,
            entry_time=entry_time,
            quantity=100,
            target_price=150.6,
            stop_price=149.625,
            time_limit_minutes=10,
            signal_name="OrderFlowSignal",
        )

        # Create a bar that doesn't hit target or stop
        bar = sample_bar.copy()
        bar["high"] = 150.3  # Below target (150.6)
        bar["low"] = 149.7  # Above stop (149.625)

        result = signal.check_exit(
            position,
            {},
            bar,
            bar["ts"],
        )

        assert result is not None
        assert result.reason == "time_limit"

    def test_create_position(self, sample_bar):
        """Position creation from signal."""
        signal = OrderFlowSignal(DEFAULT_CONFIG)

        # Create a mock signal event
        from src.signals.base import SignalEvent

        signal_event = SignalEvent(
            symbol="AAPL",
            timestamp=sample_bar["ts"],
            side=SignalSide.LONG,
            confidence=0.8,
            features={},
            signal_name="OrderFlowSignal",
        )

        position = signal.create_position(
            signal_event,
            entry_price=150.0,
            entry_time=sample_bar["ts"],
            quantity=100,
        )

        assert position.symbol == "AAPL"
        assert position.side == SignalSide.LONG
        assert position.entry_price == 150.0
        assert position.quantity == 100
        assert position.target_price == 150.0 * (1 + 0.004)  # 0.4%
        assert position.stop_price == 150.0 * (1 - 0.0025)  # 0.25%


class TestWhaleDetectSignal:
    """Tests for H2: Whale Detection Signal."""

    def test_entry_long_valid_conditions(self, sample_bar):
        """Entry fires on valid LONG conditions."""
        signal = WhaleDetectSignal(DEFAULT_CONFIG)

        # Valid LONG conditions
        features = {
            "has_large_bid": True,
            "trade_imbalance_5": 0.3,  # > 0.1 min
            "rvol": 2.0,  # > 1.5 min
            "large_bid_count": 2,
        }

        result = signal.check_entry(
            features,
            sample_bar,
            sample_bar["ts"],
        )

        assert result is not None
        assert result.side == SignalSide.LONG

    def test_no_entry_low_volume(self, sample_bar):
        """No entry when RVOL too low."""
        signal = WhaleDetectSignal(DEFAULT_CONFIG)

        features = {
            "has_large_bid": True,
            "trade_imbalance_5": 0.3,
            "rvol": 1.2,  # Below 1.5 threshold
        }

        result = signal.check_entry(
            features,
            sample_bar,
            sample_bar["ts"],
        )

        assert result is None

    def test_no_entry_no_large_order(self, sample_bar):
        """No entry when no large order detected."""
        signal = WhaleDetectSignal(DEFAULT_CONFIG)

        features = {
            "has_large_bid": False,
            "trade_imbalance_5": 0.3,
            "rvol": 2.0,
        }

        result = signal.check_entry(
            features,
            sample_bar,
            sample_bar["ts"],
        )

        assert result is None


class TestLiquidityFadeSignal:
    """Tests for H3: Liquidity Fade Signal."""

    def test_entry_long_valid_conditions(self, sample_bar):
        """Entry fires on valid LONG conditions (fade panic sell)."""
        signal = LiquidityFadeSignal(DEFAULT_CONFIG)

        # Valid LONG conditions (bid depth dropped, price fell)
        features = {
            "depth_drop_detected": True,
            "bid_drop_pct": 0.6,  # > 50% threshold
            "ask_drop_pct": 0.3,
            "ret_5": -0.003,  # -0.3% (panic sell)
        }

        result = signal.check_entry(
            features,
            sample_bar,
            sample_bar["ts"],
        )

        assert result is not None
        assert result.side == SignalSide.LONG

    def test_entry_short_valid_conditions(self, sample_bar):
        """Entry fires on valid SHORT conditions (fade panic buy)."""
        signal = LiquidityFadeSignal(DEFAULT_CONFIG)

        # Valid SHORT conditions (ask depth dropped, price rose)
        features = {
            "depth_drop_detected": True,
            "bid_drop_pct": 0.3,
            "ask_drop_pct": 0.6,  # > 50% threshold
            "ret_5": 0.003,  # +0.3% (panic buy)
        }

        result = signal.check_entry(
            features,
            sample_bar,
            sample_bar["ts"],
        )

        assert result is not None
        assert result.side == SignalSide.SHORT

    def test_no_entry_no_price_spike(self, sample_bar):
        """No entry when price hasn't moved enough."""
        signal = LiquidityFadeSignal(DEFAULT_CONFIG)

        features = {
            "depth_drop_detected": True,
            "bid_drop_pct": 0.6,
            "ask_drop_pct": 0.3,
            "ret_5": -0.001,  # Only -0.1%, below 0.2% threshold
        }

        result = signal.check_entry(
            features,
            sample_bar,
            sample_bar["ts"],
        )

        assert result is None

    def test_no_entry_no_depth_drop(self, sample_bar):
        """No entry when depth drop not detected."""
        signal = LiquidityFadeSignal(DEFAULT_CONFIG)

        features = {
            "depth_drop_detected": False,
            "bid_drop_pct": 0.1,
            "ask_drop_pct": 0.1,
            "ret_5": -0.003,
        }

        result = signal.check_entry(
            features,
            sample_bar,
            sample_bar["ts"],
        )

        assert result is None


class TestSignalEdgeCases:
    """Tests for signal edge cases."""

    def test_missing_features(self, sample_bar):
        """Signals handle missing features gracefully."""
        signal = OrderFlowSignal(DEFAULT_CONFIG)

        # Missing features
        features = {}

        result = signal.check_entry(
            features,
            sample_bar,
            sample_bar["ts"],
        )

        assert result is None

    def test_confidence_clamping(self, sample_bar):
        """Confidence is clamped to [0, 1]."""
        signal = OrderFlowSignal(DEFAULT_CONFIG)

        # Very strong signal
        features = {
            "book_imbalance_5": 2.0,  # Very high
            "trade_imbalance_5": 2.0,
            "spread": 0.01,
        }

        result = signal.check_entry(
            features,
            sample_bar,
            sample_bar["ts"],
        )

        assert result is not None
        assert 0 <= result.confidence <= 1

    def test_position_age_calculation(self, sample_bar):
        """Position age calculated correctly."""
        entry_time = pd.Timestamp("2024-01-02 09:55:00")
        current_time = pd.Timestamp("2024-01-02 10:05:00")

        position = Position(
            symbol="AAPL",
            side=SignalSide.LONG,
            entry_price=150.0,
            entry_time=entry_time,
            quantity=100,
            target_price=151.0,
            stop_price=149.0,
            time_limit_minutes=10,
            signal_name="TestSignal",
        )

        age = position.age_minutes(current_time)
        assert age == 10.0
