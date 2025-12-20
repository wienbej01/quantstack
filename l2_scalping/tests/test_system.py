#!/usr/bin/env python3
"""
L2 Scalping System Test Suite

Tests all components with mock data before paper trading.
"""

import os
import sys
import time
import unittest
from pathlib import Path

import yaml

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from data.l2_feed import MockL2DataFeed
from risk.risk_manager import CircuitBreaker, RiskManager
from signals.l2_signals import (
    L2SignalGenerator,
    L2Snapshot,
    SignalType,
    SignalValidator,
)


class TestL2Signals(unittest.TestCase):
    """Test signal generation"""

    def setUp(self):
        self.config = {
            "obi_entry_threshold": 0.3,
            "obi_extreme_threshold": 0.6,
            "min_confidence": 0.3,
            "symbols": {"PFE": {"max_spread": 0.02}},
        }
        self.generator = L2SignalGenerator(self.config)
        self.validator = SignalValidator(self.config)

    def test_obi_momentum_signal(self):
        """Test OBI momentum signal generation"""
        # Strong buy signal
        snapshot = L2Snapshot(
            symbol="PFE",
            timestamp=time.time(),
            mid=25.50,
            spread=0.01,
            obi_1=0.7,  # Strong buy
            obi_5=0.5,
            depth_bid=5000,
            depth_ask=4000,
            pressure=1000,
        )

        signal = self.generator.generate_signal(snapshot)

        self.assertEqual(signal.signal_type, SignalType.LONG)
        self.assertGreater(signal.strength, 0.5)
        self.assertGreater(signal.confidence, 0.3)

    def test_hidden_liquidity_detection(self):
        """Test hidden liquidity detection"""
        # Hidden buy liquidity
        snapshot = L2Snapshot(
            symbol="PFE",
            timestamp=time.time(),
            mid=25.50,
            spread=0.01,
            obi_1=-0.4,  # Sellers at top
            obi_5=0.3,  # Buyers deeper
            depth_bid=5000,
            depth_ask=4000,
            pressure=1000,
        )

        signal = self.generator.generate_signal(snapshot)

        self.assertEqual(signal.hidden_liquidity.value, "hidden_buy")

    def test_signal_validation(self):
        """Test signal validation"""
        snapshot = L2Snapshot(
            symbol="PFE",
            timestamp=time.time(),
            mid=25.50,
            spread=0.05,  # Too wide
            obi_1=0.5,
            obi_5=0.3,
            depth_bid=5000,
            depth_ask=4000,
            pressure=1000,
        )

        signal = self.generator.generate_signal(snapshot)
        is_valid, reason = self.validator.is_valid_signal(signal, snapshot)

        self.assertFalse(is_valid)
        self.assertIn("Spread too wide", reason)


class TestRiskManager(unittest.TestCase):
    """Test risk management"""

    def setUp(self):
        self.config = {
            "max_daily_loss_bps": 100,
            "max_trade_loss_bps": 10,
            "max_position_pct": 0.01,
            "max_daily_trades": 100,
        }
        self.risk_manager = RiskManager(self.config)

    def test_position_sizing(self):
        """Test position size calculation"""
        size = self.risk_manager.calculate_position_size(
            symbol="PFE",
            signal_strength=0.8,
            confidence=0.7,
            account_value=100000,
            price=25.50,
        )

        self.assertGreater(size, 0)
        self.assertLess(size * 25.50, 1000)  # Less than 1% of account

    def test_pre_trade_risk_check(self):
        """Test pre-trade risk checks"""
        can_trade, reason = self.risk_manager.check_pre_trade_risk(
            symbol="PFE", quantity=100, price=25.50, account_value=100000
        )

        self.assertTrue(can_trade)
        self.assertEqual(reason, "Risk check passed")

    def test_daily_loss_limit(self):
        """Test daily loss limit"""
        # Simulate large loss
        self.risk_manager.daily_pnl = -1000  # $1000 loss

        can_trade, reason = self.risk_manager.check_pre_trade_risk(
            symbol="PFE", quantity=100, price=25.50, account_value=100000
        )

        self.assertFalse(can_trade)
        self.assertIn("Daily loss limit", reason)


class TestCircuitBreaker(unittest.TestCase):
    """Test circuit breaker"""

    def setUp(self):
        self.config = {
            "max_loss_rate_per_minute": 50,
            "max_consecutive_losses": 3,
            "min_time_between_trades_ms": 1000,
        }
        self.breaker = CircuitBreaker(self.config)

    def test_consecutive_losses(self):
        """Test consecutive loss detection"""
        # Simulate consecutive losses
        for i in range(3):
            triggered, reason = self.breaker.check_circuit_breaker(-10)
            if i < 2:
                self.assertFalse(triggered)
            else:
                self.assertTrue(triggered)
                self.assertIn("Consecutive losses", reason)


class TestMockDataFeed(unittest.TestCase):
    """Test mock data feed"""

    def setUp(self):
        self.config = {
            "symbols": ["PFE", "HAL"],
            "update_frequency_hz": 10,  # Fast for testing
        }
        self.feed = MockL2DataFeed(self.config)
        self.received_data = []

    def data_callback(self, snapshot):
        """Callback for data updates"""
        self.received_data.append(snapshot)

    def test_mock_data_generation(self):
        """Test mock data generation"""
        self.feed.add_data_callback(self.data_callback)
        self.feed.connect()

        # Wait for some data
        time.sleep(1)

        self.feed.disconnect()

        # Check we received data
        self.assertGreater(len(self.received_data), 5)

        # Check data quality
        snapshot = self.received_data[0]
        self.assertIsInstance(snapshot.symbol, str)
        self.assertGreater(snapshot.mid, 0)
        self.assertGreater(snapshot.spread, 0)
        self.assertGreaterEqual(snapshot.obi_1, -1)
        self.assertLessEqual(snapshot.obi_1, 1)


class TestSystemIntegration(unittest.TestCase):
    """Integration tests"""

    def setUp(self):
        # Load test configuration
        config_dir = Path(__file__).parent.parent / "config"

        with open(config_dir / "strategy.yaml") as f:
            self.strategy_config = yaml.safe_load(f)

        with open(config_dir / "risk.yaml") as f:
            self.risk_config = yaml.safe_load(f)

        # Enable mock data for testing
        self.strategy_config["mock_data"]["enabled"] = True

    def test_signal_to_risk_flow(self):
        """Test signal generation to risk check flow"""
        # Create components
        signal_gen = L2SignalGenerator(self.strategy_config)
        risk_mgr = RiskManager(self.risk_config)

        # Create test snapshot
        snapshot = L2Snapshot(
            symbol="PFE",
            timestamp=time.time(),
            mid=25.50,
            spread=0.01,
            obi_1=0.5,  # Buy signal
            obi_5=0.3,
            depth_bid=5000,
            depth_ask=4000,
            pressure=1000,
        )

        # Generate signal
        signal = signal_gen.generate_signal(snapshot)

        # Check risk
        quantity = risk_mgr.calculate_position_size(
            symbol=signal.symbol,
            signal_strength=signal.strength,
            confidence=signal.confidence,
            account_value=100000,
            price=snapshot.mid,
        )

        can_trade, reason = risk_mgr.check_pre_trade_risk(
            symbol=signal.symbol,
            quantity=quantity,
            price=snapshot.mid,
            account_value=100000,
        )

        # Should be able to trade
        self.assertTrue(can_trade)
        self.assertGreater(quantity, 0)


def run_tests():
    """Run all tests"""
    print("=" * 60)
    print("L2 SCALPING SYSTEM - TEST SUITE")
    print("=" * 60)

    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestL2Signals))
    suite.addTests(loader.loadTestsFromTestCase(TestRiskManager))
    suite.addTests(loader.loadTestsFromTestCase(TestCircuitBreaker))
    suite.addTests(loader.loadTestsFromTestCase(TestMockDataFeed))
    suite.addTests(loader.loadTestsFromTestCase(TestSystemIntegration))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print("ALL TESTS PASSED ✓")
        print("System ready for paper trading validation")
    else:
        print("TESTS FAILED ✗")
        print(f"Failures: {len(result.failures)}")
        print(f"Errors: {len(result.errors)}")
    print("=" * 60)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
