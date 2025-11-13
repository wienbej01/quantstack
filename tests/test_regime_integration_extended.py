"""Extended integration tests for regime detection gating behavior.

Tests stress overrides, day-level regime lock, midday pivots,
and complex multi-regime scenarios.
"""

import numpy as np
import pandas as pd
import pytest

from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_core.regime.detector import RegimeDetectorConfig, RegimeDetectorRules
from qx_core.regime_config import RegimeConfig
from qx_core.schemas import RegimeSignal, RegimeType
from qx_risk.atr_stop import (
    get_regime_risk_context,
    reject_order_for_regime,
    size_order,
)


class TestStressRegimeOverrides:
    """Test stress regime override behavior."""

    def test_stress_regime_blocks_all_trading(self):
        """Test that stress regime blocks all new trading activity."""
        config = BacktestConfig(
            regime_config=RegimeConfig(
                enabled=True,
                strategy_map={
                    "BULL": ["strategy1"],
                    "BEAR": ["strategy1"],
                    "SIDEWAYS": ["strategy1"],
                    "STRESS": [],  # No strategies in stress
                },
            ).dict(),
            strategy_map={
                "BULL": ["strategy1"],
                "BEAR": ["strategy1"],
                "SIDEWAYS": ["strategy1"],
                "STRESS": [],
            },
        )

        engine = BacktestEngine(config)

        # Simulate stress regime
        engine._current_regime = RegimeType.STRESS

        # Test strategy gating
        assert not engine.is_strategy_allowed("strategy1")
        assert not engine.is_strategy_allowed("any_strategy")

        # Test order rejection
        signal = {"entry_hint": 100.0, "strategy": "test"}
        assert reject_order_for_regime(signal, RegimeType.STRESS) is True

        # Test risk context
        risk_context = get_regime_risk_context(RegimeType.STRESS)
        assert risk_context["risk_mode"] == "stress"
        assert risk_context["risk_reduction"] == 0.7
        assert "avoid_new_entries" in risk_context["recommended_actions"]

    def test_stress_regime_reduces_position_sizing(self):
        """Test that stress regime significantly reduces position sizing."""
        signal = {"entry_hint": 100.0, "strategy": "test"}
        equity = 100000.0
        atr = 2.0

        base_params = {"max_risk_frac": 0.02, "atr_mult": 2.0}
        stress_params = base_params.copy()
        stress_params["regime_adjustments"] = {
            RegimeType.STRESS.value: {"risk_multiplier": 0.3, "atr_multiplier": 1.5}
        }

        # Normal sizing
        normal_size = size_order(signal, equity, atr, base_params)

        # Stress sizing
        stress_size = size_order(signal, equity, atr, stress_params, RegimeType.STRESS)

        # Stress regime should significantly reduce size
        assert stress_size is not None
        assert stress_size < normal_size * 0.5  # At least 50% reduction

    def test_stress_regime_with_allowed_strategies(self):
        """Test behavior when some strategies are allowed in stress regime."""
        config = BacktestConfig(
            regime_config=RegimeConfig(
                enabled=True,
                strategy_map={
                    "BULL": ["conservative"],
                    "BEAR": ["conservative"],
                    "SIDEWAYS": ["mean_reversion"],
                    "STRESS": ["ultra_conservative"],  # One strategy allowed in stress
                },
            ).dict()
        )

        engine = BacktestEngine(config)

        # Simulate stress regime
        engine._current_regime = RegimeType.STRESS

        # Conservative strategies should be blocked
        assert not engine.is_strategy_allowed("conservative")
        assert not engine.is_strategy_allowed("mean_reversion")

        # Ultra-conservative strategy should be allowed
        assert engine.is_strategy_allowed("ultra_conservative")

        # Other strategies should be blocked
        assert not engine.is_strategy_allowed("aggressive")

    def test_stress_to_normal_transition(self):
        """Test behavior when transitioning from stress to normal regime."""
        config = BacktestConfig(
            regime_config=RegimeConfig(
                enabled=True,
                persistence_bars=3,
                cooldown_minutes=15,
                strategy_map={"BULL": ["normal_strategy"], "STRESS": []},
            ).dict()
        )

        engine = BacktestConfig(config)
        engine = BacktestEngine(engine)

        # Start in stress regime
        engine._current_regime = RegimeType.STRESS

        # Add persistence
        for i in range(3):
            engine._persistence_counters["test"][RegimeType.STRESS] = i + 1

        # Switch to normal regime
        engine._current_regime = RegimeType.BULL
        engine._persistence_counters["test"][RegimeType.BULL] = 3

        # Should now allow trading
        assert engine.is_strategy_allowed("normal_strategy")

        # Risk context should update
        risk_context = get_regime_risk_context(RegimeType.BULL)
        assert risk_context["risk_mode"] == "normal"
        assert risk_context["risk_reduction"] == 0.0


class TestDayLevelRegimeLock:
    """Test day-level regime locking behavior."""

    def test_persistent_regime_through_day(self):
        """Test that regime persists throughout trading day once established."""
        config = RegimeDetectorConfig(persistence_bars=5)

        detector = RegimeDetectorRules(config)

        # Create time series that spans a trading day
        timestamps = pd.date_range("2024-01-02 09:30:00", "2024-01-02 16:00:00", freq="5min")
        features_data = []

        for i, ts in enumerate(timestamps):
            # Create features that suggest BULL regime
            features = {
                "ts": int(ts.timestamp() * 1e9),
                "symbol": "TEST",
                "f__regime__var_ratio_10_60": 1.3 + np.random.normal(0, 0.05),
                "f__regime__adx_proxy_14": 35.0 + np.random.normal(0, 2),
                "f__regime__band_pos_20_2.0": 0.7 + np.random.normal(0, 0.05),
                "f__regime__mod_vol_30": 1.2 + np.random.normal(0, 0.1),
                "f__regime__stress_10_10": 0.1,
                "f__regime__warmup_ok": i >= 4,  # Warmup after 4 bars
            }
            features_data.append(features)

        df = pd.DataFrame(features_data)

        # Process first timestamp to establish regime
        first_signal = detector.evaluate(df.iloc[0:1], df.iloc[0]["ts"])
        initial_regime = first_signal.regime

        # Process subsequent timestamps
        regime_changes = 0
        current_regime = initial_regime

        for i in range(1, len(df)):
            signal = detector.evaluate(df.iloc[i : i + 1], df.iloc[i]["ts"])
            if signal.regime != current_regime:
                regime_changes += 1
                current_regime = signal.regime

        # Should have minimal regime changes due to persistence
        assert regime_changes <= len(df) * 0.1  # Allow up to 10% changes

    def test_midday_regime_pivot_with_persistence(self):
        """Test midday regime pivot with proper persistence requirements."""
        config = RegimeDetectorConfig(persistence_bars=3, cooldown_minutes=30)

        detector = RegimeDetectorRules(config)

        # Create morning data (BULL regime)
        morning_timestamps = pd.date_range(
            "2024-01-02 09:30:00", "2024-01-02 12:00:00", freq="5min"
        )
        morning_data = []

        for ts in morning_timestamps:
            features = {
                "ts": int(ts.timestamp() * 1e9),
                "symbol": "TEST",
                "f__regime__var_ratio_10_60": 1.4,
                "f__regime__adx_proxy_14": 40.0,
                "f__regime__band_pos_20_2.0": 0.8,
                "f__regime__mod_vol_30": 1.1,
                "f__regime__stress_10_10": 0.1,
                "f__regime__warmup_ok": True,
            }
            morning_data.append(features)

        # Create afternoon data (BEAR regime)
        afternoon_timestamps = pd.date_range(
            "2024-01-02 13:00:00", "2024-01-02 16:00:00", freq="5min"
        )
        afternoon_data = []

        for ts in afternoon_timestamps:
            features = {
                "ts": int(ts.timestamp() * 1e9),
                "symbol": "TEST",
                "f__regime__var_ratio_10_60": 0.7,
                "f__regime__adx_proxy_14": 40.0,
                "f__regime__band_pos_20_2.0": 0.2,
                "f__regime__mod_vol_30": 1.1,
                "f__regime__stress_10_10": 0.1,
                "f__regime__warmup_ok": True,
            }
            afternoon_data.append(features)

        all_data = pd.DataFrame(morning_data + afternoon_data)

        # Process morning to establish BULL regime
        for i in range(len(morning_data)):
            signal = detector.evaluate(all_data.iloc[i : i + 1], all_data.iloc[i]["ts"])

        # Should be in BULL regime after morning
        bull_signal = detector.evaluate(
            all_data.iloc[len(morning_data) - 1 : len(morning_data)],
            all_data.iloc[len(morning_data) - 1]["ts"],
        )
        assert bull_signal.regime == RegimeType.BULL

        # Process afternoon - should eventually switch to BEAR with persistence
        regime_switched = False
        bear_regime_count = 0

        for i in range(len(morning_data), len(all_data)):
            signal = detector.evaluate(all_data.iloc[i : i + 1], all_data.iloc[i]["ts"])
            if signal.regime == RegimeType.BEAR:
                bear_regime_count += 1
                if bear_regime_count >= 3:  # Persistence requirement met
                    regime_switched = True
                    break

        # Should eventually switch to BEAR regime
        assert regime_switched, "Should have switched to BEAR regime by end of day"

    def test_cooldown_prevents_immediate_reversion(self):
        """Test that cooldown prevents immediate regime reversion."""
        config = RegimeDetectorConfig(persistence_bars=2, cooldown_minutes=60)

        detector = RegimeDetectorRules(config)

        # Create data that suggests regime change
        features = {
            "ts": 1000000000000,
            "symbol": "TEST",
            "f__regime__var_ratio_10_60": 1.3,
            "f__regime__adx_proxy_14": 35.0,
            "f__regime__band_pos_20_2_0": 0.8,
            "f__regime__mod_vol_30": 1.1,
            "f__regime__stress_10_10": 0.1,
            "f__regime__warmup_ok": True,
        }

        # First evaluation establishes BULL regime
        signal1 = detector.evaluate(pd.DataFrame([features]), features["ts"])
        assert signal1.regime == RegimeType.BULL

        # Update last change time
        detector._last_regime_change["TEST"] = features["ts"]

        # Create data that suggests BEAR regime but within cooldown
        bear_features = features.copy()
        bear_features.update({"f__regime__var_ratio_10_60": 0.7, "f__regime__band_pos_20_2.0": 0.2})

        # Try to switch to BEAR regime during cooldown (should be blocked)
        signal2 = detector.evaluate(pd.DataFrame([bear_features]), bear_features["ts"])
        assert signal2.regime == RegimeType.BULL, "Should remain in BULL regime during cooldown"

        # Test with different symbol
        signal3 = detector.evaluate_symbol("OTHER", bear_features, bear_features["ts"])
        assert signal3.regime == RegimeType.BULL, "Different symbol should also respect cooldown"


class TestComplexMultiRegimeScenarios:
    """Test complex multi-regime scenarios with strategy interactions."""

    def test_strategy_portfolio_different_regime_allocations(self):
        """Test that different strategies get allocated to different regimes."""
        strategies = {
            "momentum": ["BULL"],
            "reversion": ["BEAR", "SIDEWAYS"],
            "conservative": ["SIDEWAYS"],
            "aggressive": ["BULL"],
        }

        config = BacktestConfig(
            regime_config=RegimeConfig(enabled=True, strategy_map=strategies).dict()
        )

        engine = BacktestEngine(config)

        # Test strategy permissions in different regimes
        for regime, allowed_strategies in strategies.items():
            for strategy in allowed_strategies:
                assert engine.is_strategy_allowed(strategy), (
                    f"Strategy {strategy} should be allowed in {regime}"
                )
            # Test a strategy not allowed in this regime
            blocked_strategies = [
                s
                for s in ["momentum", "reversion", "conservative", "aggressive"]
                if s not in allowed_strategies
            ]
            for blocked in blocked_strategies:
                assert not engine.is_strategy_allowed(blocked), (
                    f"Strategy {blocked} should be blocked in {regime}"
                )

    def test_regime_aware_portfolio_allocation(self):
        """Test portfolio allocation changes based on regime."""
        config = BacktestConfig(
            regime_config=RegimeConfig(
                enabled=True,
                strategy_map={
                    "BULL": ["growth", "trend"],
                    "BEAR": ["defensive", "value"],
                    "SIDEWAYS": ["arbitrage", "market_neutral"],
                    "STRESS": ["cash", "defensive"],
                },
            ).dict()
        )

        engine = BacktestConfig(config)
        engine = BacktestEngine(engine)

        # Simulate regime changes and verify portfolio strategy allocation
        regime_strategies = {
            RegimeType.BULL: ["growth", "trend"],
            RegimeType.BEAR: ["defensive", "value"],
            RegimeType.SIDEWAYS: ["arbitrage", "market_neutral"],
            RegimeType.STRESS: ["cash", "defensive"],
        }

        for regime, strategies in regime_strategies.items():
            engine._current_regime = regime

            # Verify allowed strategies
            for strategy in strategies:
                assert engine.is_strategy_allowed(strategy), (
                    f"Strategy {strategy} should be allowed in {regime}"
                )

            # Verify blocked strategies
            all_strategies = [
                "growth",
                "trend",
                "defensive",
                "value",
                "arbitrage",
                "market_neutral",
                "cash",
            ]
            blocked_strategies = [s for s in all_strategies if s not in strategies]
            for blocked in blocked_strategies:
                assert not engine.is_strategy_allowed(blocked), (
                    f"Strategy {blocked} should be blocked in {regime}"
                )

    def test_multi_symbol_regime_diversification(self):
        """Test regime detection across multiple symbols with different characteristics."""
        symbols = ["AAPL", "MSFT", "GOOGL"]

        config = RegimeDetectorConfig()
        detector = RegimeDetectorRules(config)

        # Create different regime patterns for each symbol
        symbol_regimes = {}
        symbol_features = {}

        for symbol in symbols:
            regime_data = []

            if symbol == "AAPL":
                # Tech growth stock - primarily BULL with occasional stress
                for i in range(50):
                    regime = RegimeType.BULL if i % 10 != 0 else RegimeType.STRESS
                    features = self._create_features_for_regime(regime, i)
                    features["symbol"] = symbol
                    features["ts"] = i * 60 * 1e9
                    regime_data.append(features)

            elif symbol == "MSFT":
                # Established stock - mix of BULL and SIDEWAYS
                for i in range(50):
                    regime = RegimeType.BULL if i % 7 != 0 else RegimeType.SIDEWAYS
                    features = self._create_features_for_regime(regime, i)
                    features["symbol"] = symbol
                    features["ts"] = i * 60 * 1e9
                    regime_data.append(features)

            else:  # GOOGL
                # More volatile - mix of all regimes
                regimes = [
                    RegimeType.BULL,
                    RegimeType.BEAR,
                    RegimeType.SIDEWAYS,
                    RegimeType.STRESS,
                ]
                for i in range(50):
                    regime = regimes[i % len(regimes)]
                    features = self._create_features_for_regime(regime, i)
                    features["symbol"] = symbol
                    features["ts"] = i * 60 * 1e9
                    regime_data.append(features)

            symbol_features[symbol] = regime_data

        # Process data for each symbol
        symbol_regimes = {}
        for symbol, features in symbol_features.items():
            df = pd.DataFrame(features)
            signals = []

            for i, row in df.iterrows():
                signal = detector.evaluate_symbol(symbol, row.to_dict(), row["ts"])
                signals.append(signal)

            # Track dominant regime for each symbol
            regime_counts = {}
            for signal in signals:
                regime = signal.regime
                regime_counts[regime] = regime_counts.get(regime, 0) + 1

            if regime_counts:
                dominant_regime = max(regime_counts.items(), key=lambda x: x[1])[0]
                symbol_regimes[symbol] = dominant_regime

        # Verify regime diversity
        assert len(set(symbol_regimes.values())) > 1, "Should have different regimes across symbols"

        # AAPL should be mostly BULL
        assert symbol_regimes.get("AAPL") == RegimeType.BULL

        # At least one symbol should experience stress
        assert any(regime == RegimeType.STRESS for regime in symbol_regimes.values()), (
            "At least one symbol should experience stress"
        )

    def _create_features_for_regime(self, regime: RegimeType, timestamp: int) -> dict:
        """Create features for a specific regime."""
        base_features = {
            "f__regime__warmup_ok": True,
            "f__regime__mod_vol_30": 1.0,
            "f__regime__var_ratio_10_60": 1.0,
            "f__regime__adx_proxy_14": 25.0,
            "f__regime__band_pos_20_2.0": 0.5,
            "f__regime__stress_10_10": 0.1,
        }

        noise = np.random.normal(0, 0.05)

        if regime == RegimeType.BULL:
            return {
                **base_features,
                "f__regime__var_ratio_10_60": 1.3 + noise,
                "f__regime__adx_proxy_14": 40.0 + noise * 5,
                "f__regime__band_pos_20_2_0": 0.7 + noise * 0.1,
                "f__regime__mod_vol_30": 1.1 + noise * 0.1,
            }
        elif regime == RegimeType.BEAR:
            return {
                **base_features,
                "f__regime__var_ratio_10_60": 0.7 + noise,
                "f__regime__adx_proxy_14": 40.0 + noise * 5,
                "f__regime__band_pos_20_2_0": 0.3 + noise * 0.1,
                "f__regime__mod_vol_30": 1.2 + noise * 0.1,
            }
        elif regime == RegimeType.SIDEWAYS:
            return {
                **base_features,
                "f__regime__var_ratio_10_60": 1.0 + noise,
                "f__regime__adx_proxy_14": 15.0 + noise * 3,
                "f__regime__band_pos_20_2_0": 0.5 + noise * 0.1,
                "f__regime__mod_vol_30": 0.9 + noise * 0.05,
            }
        elif regime == RegimeType.STRESS:
            return {
                **base_features,
                "f__regime__var_ratio_10_60": 2.0 + noise * 0.2,
                "f__regime__adx_proxy_14": 60.0 + noise * 10,
                "f__regime__band_pos_20_2_0": 0.9 + noise * 0.1,
                "f__regime__mod_vol_30": 3.0 + noise * 0.3,
                "f__regime__stress_10_10": 2.5,
            }
        else:  # OFF
            return base_features


class TestRegimeDetectionPerformance:
    """Test performance characteristics of regime detection."""

    def test_regime_detection_latency(self):
        """Test that regime detection has acceptable latency."""
        config = RegimeDetectorConfig()
        detector = RegimeDetectorRules(config)

        # Create a single feature set
        features = {
            "ts": 1000000000000,
            "symbol": "TEST",
            "f__regime__var_ratio_10_60": 1.2,
            "f__regime__adx_proxy_14": 30.0,
            "f__regime__band_pos_20_2_0": 0.6,
            "f__regime__mod_vol_30": 1.1,
            "f__regime__stress_10_10": 0.1,
            "f__regime__warmup_ok": True,
        }

        df = pd.DataFrame([features])

        # Measure execution time
        import time

        start_time = time.time()
        signal = detector.evaluate(df, features["ts"])
        end_time = time.time()

        execution_time = end_time - start_time

        # Should complete quickly
        assert execution_time < 0.01, (
            f"Regime detection took {execution_time:.4f}s, should be < 0.01s"
        )

        # Should return valid signal
        assert isinstance(signal, RegimeSignal)
        assert signal.regime in RegimeType
        assert 0.0 <= signal.confidence <= 1.0

    def test_regime_detection_memory_usage(self):
        """Test that regime detection has reasonable memory usage."""
        config = RegimeDetectorConfig()
        detector = RegimeDetectorRules(config)

        # Create many data points
        features_list = []
        for i in range(1000):
            features = {
                "ts": i * 60 * 1e9,
                "symbol": "TEST",
                "f__regime__var_ratio_10_60": 1.0 + np.random.normal(0, 0.1),
                "f__regime__adx_proxy_14": 25.0 + np.random.normal(0, 5),
                "f__regime__band_pos_20_2_0": 0.5 + np.random.normal(0, 0.1),
                "f__regime__mod_vol_30": 1.0 + np.random.normal(0, 0.1),
                "f__regime__stress_10_10": 0.1,
                "f__regime__warmup_ok": True,
            }
            features_list.append(features)

        df = pd.DataFrame(features_list)

        # Process all data points
        for i, row in df.iterrows():
            signal = detector.evaluate(pd.DataFrame([row]), row["ts"])
            assert isinstance(signal, RegimeSignal)

        # Check statistics
        stats = detector.get_statistics()
        assert stats["evaluations"] == 1000
        assert stats["regime_changes"] >= 0

        # Memory usage should remain bounded (two segment histories)
        assert 0 < len(detector._regime_history) <= 4

    def test_regime_detection_statistics_tracking(self):
        """Test that regime detection properly tracks statistics."""
        config = RegimeDetectorConfig()
        detector = RegimeDetectorRules(config)

        # Process multiple evaluations
        features = {
            "ts": 1000000000000,
            "symbol": "TEST",
            "f__regime__var_ratio_10_60": 1.2,
            "f__regime__adx_proxy_14": 30.0,
            "f__regime__band_pos_20_2_0": 0.6,
            "f__regime__mod_vol_30": 1.1,
            "f__regime__stress_10_10": 0.1,
            "f__regime__warmup_ok": True,
        }

        df = pd.DataFrame([features])

        # Multiple evaluations
        for i in range(10):
            features["ts"] = (i + 1) * 60 * 1e9
            detector.evaluate(df, features["ts"])

        # Check statistics
        stats = detector.get_statistics()
        assert stats["evaluations"] == 10
        assert "change_rate" in stats
        assert "avg_persistence" in stats
        assert "symbols_tracked" in stats
        assert "cached_segments" in stats

        # Should track symbols even with single symbol
        assert stats["symbols_tracked"] >= 1

        # Reset and verify statistics reset
        detector.reset_state()
        reset_stats = detector.get_statistics()
        assert reset_stats["evaluations"] == 0
        assert reset_stats["regime_changes"] == 0
        assert reset_stats["symbols_tracked"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
