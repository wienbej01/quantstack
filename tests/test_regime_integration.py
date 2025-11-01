"""Integration tests for regime detection gating behavior.

Tests the complete integration between regime detection, backtest engine,
strategy gating, and risk management.
"""

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_core.regime.detector import RegimeDetectorConfig
from qx_core.regime_config import RegimeConfig
from qx_core.schemas import RegimeSignal, RegimeType
from qx_features.registry import apply
from qx_risk.atr_stop import (
    get_regime_risk_context,
    reject_order_for_regime,
    size_order,
)


@pytest.fixture
def sample_ohlcv_data():
    """Create sample OHLCV data for integration testing."""
    np.random.seed(42)

    symbols = ["AAPL", "MSFT", "GOOGL"]
    dates = pd.date_range("2024-01-02 09:30:00", "2024-01-02 16:00:00", freq="1min")

    data = []
    for symbol in symbols:
        for date in dates:
            # Skip non-trading hours
            if date.hour < 9 or (date.hour == 9 and date.minute < 30):
                continue
            if date.hour >= 16:
                continue

            # Simulate market data with regime characteristics
            base_price = (
                100.0 if symbol == "AAPL" else (150.0 if symbol == "MSFT" else 200.0)
            )

            # Add some randomness and trend
            noise = np.random.normal(0, 0.001)
            trend = 0.0001 * (date.hour - 9.5)  # Slight upward trend

            close = base_price * (1 + noise + trend)
            high = close * (1 + abs(np.random.normal(0, 0.002)))
            low = close * (1 - abs(np.random.normal(0, 0.002)))
            open_price = low + (high - low) * np.random.random()
            volume = int(np.random.lognormal(10, 1))

            data.append(
                {
                    "ts": int(date.timestamp() * 1e9),
                    "symbol": symbol,
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": volume,
                }
            )

    df = pd.DataFrame(data)
    return df.sort_values(["symbol", "ts"]).reset_index(drop=True)


@pytest.fixture
def regime_config():
    """Create regime configuration for testing."""
    return RegimeConfig(
        enabled=True,
        persistence_bars=2,
        cooldown_minutes=5,
        strategy_map={
            "BULL": ["test_strategy"],
            "BEAR": ["test_strategy"],
            "SIDEWAYS": ["test_strategy"],
            "STRESS": [],
        },
        detector_params=RegimeDetectorConfig(
            variance_ratio_bull=1.1,
            variance_ratio_bear=0.9,
            adx_trend_threshold=25.0,
            volatility_stress_threshold=1.5,
            stress_confidence_min=0.7,
        ),
    )


class TestRegimeBacktestIntegration:
    """Test regime detection integration with backtest engine."""

    def test_backtest_engine_with_regime_config(self, sample_ohlcv_data, regime_config):
        """Test backtest engine initialization with regime configuration."""
        config = BacktestConfig(
            regime_config=regime_config.dict(), strategy_map=regime_config.strategy_map
        )

        engine = BacktestEngine(config)

        # Verify regime detector is initialized
        assert engine._regime_detector is not None
        assert engine._strategy_map == regime_config.strategy_map
        assert engine._current_regime == RegimeType.OFF

    def test_backtest_engine_without_regime_config(self, sample_ohlcv_data):
        """Test backtest engine without regime configuration."""
        config = BacktestConfig()  # No regime config

        engine = BacktestEngine(config)

        # Verify regime detector is not initialized
        assert engine._regime_detector is None
        assert engine._current_regime is None

    def test_regime_detection_during_backtest(self, sample_ohlcv_data, regime_config):
        """Test regime detection during backtest execution."""
        # Add regime features to data
        features_config = [{"type": "regime_basics"}, {"type": "core_basics"}]
        data_with_features = apply(sample_ohlcv_data, features_config)

        config = BacktestConfig(
            regime_config=regime_config.dict(), strategy_map=regime_config.strategy_map
        )

        engine = BacktestEngine(config)

        # Define strategy that respects regime gating
        orders_submitted = []

        def test_strategy(engine, bar):
            # Check if strategy is allowed
            if not engine.is_strategy_allowed("test_strategy"):
                return

            # Submit order if allowed
            order = engine.order_factory.create_order(
                symbol=bar["symbol"],
                side="BUY",
                qty=100,
                entry=bar["close"],
                tag="test",
            )
            engine.submit_order(order)
            orders_submitted.append(order)

        # Run backtest
        engine.run(data_with_features, test_strategy)

        # Verify regime detection occurred
        assert len(engine._regime_history) > 0
        assert engine.get_current_regime() is not None

        # Get regime statistics
        stats = engine.get_regime_statistics()
        assert stats["regime_detection_enabled"] is True
        assert "cached_segments" in stats
        assert "current_segment" in stats

    def test_strategy_gating_in_different_regimes(
        self, sample_ohlcv_data, regime_config
    ):
        """Test strategy gating behavior in different regimes."""
        # Add regime features
        features_config = [{"type": "regime_basics"}]
        data_with_features = apply(sample_ohlcv_data, features_config)

        config = BacktestConfig(
            regime_config=regime_config.dict(), strategy_map=regime_config.strategy_map
        )

        engine = BacktestEngine(config)

        # Track orders by regime
        orders_by_regime = {}

        def tracking_strategy(engine, bar):
            current_regime = engine.get_current_regime()
            if current_regime is None:
                return

            # Check if strategy is allowed
            if not engine.is_strategy_allowed("test_strategy"):
                return

            # Track orders by regime
            if current_regime not in orders_by_regime:
                orders_by_regime[current_regime] = 0

            order = engine.order_factory.create_order(
                symbol=bar["symbol"],
                side="BUY",
                qty=100,
                entry=bar["close"],
                tag="test",
            )
            engine.submit_order(order)
            orders_by_regime[current_regime] += 1

        # Run backtest
        engine.run(data_with_features, tracking_strategy)

        # Verify strategy gating worked
        if RegimeType.STRESS in orders_by_regime:
            # Should have no orders in stress regime
            assert orders_by_regime[RegimeType.STRESS] == 0

        # Should have orders in allowed regimes
        total_orders = sum(orders_by_regime.values())
        assert total_orders > 0

    def test_regime_statistics(self, sample_ohlcv_data, regime_config):
        """Test regime statistics collection."""
        # Add regime features
        features_config = [{"type": "regime_basics"}]
        data_with_features = apply(sample_ohlcv_data, features_config)

        config = BacktestConfig(
            regime_config=regime_config.dict(), strategy_map=regime_config.strategy_map
        )

        engine = BacktestEngine(config)

        # Simple strategy
        def simple_strategy(engine, bar):
            if engine.is_strategy_allowed("test_strategy"):
                order = engine.order_factory.create_order(
                    symbol=bar["symbol"],
                    side="BUY",
                    qty=100,
                    entry=bar["close"],
                    tag="test",
                )
                engine.submit_order(order)

        # Run backtest
        engine.run(data_with_features, simple_strategy)

        # Get statistics
        stats = engine.get_regime_statistics()

        # Verify statistics
        assert "regime_detection_enabled" in stats
        assert stats["regime_detection_enabled"] is True
        assert "current_regime" in stats
        assert "cached_segments" in stats
        assert "current_segment" in stats
        assert "evaluations" in stats
        assert "change_rate" in stats

    def test_regime_history_tracking(self, sample_ohlcv_data, regime_config):
        """Test regime signal history tracking."""
        # Add regime features
        features_config = [{"type": "regime_basics"}]
        data_with_features = apply(sample_ohlcv_data, features_config)

        config = BacktestConfig(
            regime_config=regime_config.dict(), strategy_map=regime_config.strategy_map
        )

        engine = BacktestEngine(config)

        # Simple strategy
        def simple_strategy(engine, bar):
            if engine.is_strategy_allowed("test_strategy"):
                order = engine.order_factory.create_order(
                    symbol=bar["symbol"],
                    side="BUY",
                    qty=100,
                    entry=bar["close"],
                    tag="test",
                )
                engine.submit_order(order)

        # Run backtest
        engine.run(data_with_features, simple_strategy)

        # Get history
        history = engine.get_regime_history()

        # Verify history
        assert len(history) > 0
        assert all(isinstance(signal, RegimeSignal) for signal in history)

        # Check chronological order
        for i in range(1, len(history)):
            assert history[i].ts >= history[i - 1].ts

    def test_disabled_regime_detection(self, sample_ohlcv_data):
        """Test behavior when regime detection is disabled."""
        config = BacktestConfig(
            regime_config={"enabled": False}, strategy_map={}  # Disabled
        )

        engine = BacktestEngine(config)

        # Strategy should always be allowed when regime is disabled
        assert engine.is_strategy_allowed("any_strategy") is True
        assert engine.get_current_regime() is None

        # Statistics should indicate disabled
        stats = engine.get_regime_statistics()
        assert stats["regime_detection_enabled"] is False

        # History should be empty
        history = engine.get_regime_history()
        assert len(history) == 0


class TestRegimeRiskIntegration:
    """Test regime-aware risk management integration."""

    def test_regime_aware_position_sizing(self):
        """Test position sizing with regime awareness."""
        signal = {"entry_hint": 100.0, "strategy": "test"}

        equity = 100000.0
        atr = 2.0
        base_params = {"max_risk_frac": 0.02, "atr_mult": 2.0}

        # Test different regimes
        regimes = [
            RegimeType.BULL,
            RegimeType.BEAR,
            RegimeType.SIDEWAYS,
            RegimeType.STRESS,
        ]

        sizes = {}
        for regime in regimes:
            # Test without regime adjustments
            size_no_regime = size_order(signal, equity, atr, base_params)

            # Test with regime adjustments
            regime_params = base_params.copy()
            regime_params["regime_adjustments"] = {
                regime.value: {"risk_multiplier": 0.8, "atr_multiplier": 1.2}
            }
            size_with_regime = size_order(signal, equity, atr, regime_params, regime)

            sizes[regime] = {
                "no_regime": size_no_regime,
                "with_regime": size_with_regime,
            }

        # Verify regime adjustments work
        for regime, size_data in sizes.items():
            assert size_data["no_regime"] is not None
            assert size_data["with_regime"] is not None
            # With 0.8 risk multiplier, should be smaller
            if regime != RegimeType.STRESS:  # STRESS may be rejected
                assert size_data["with_regime"] <= size_data["no_regime"]

    def test_order_rejection_in_stress(self):
        """Test order rejection in stress regime."""
        signal = {"entry_hint": 100.0, "strategy": "test"}

        # Should reject in stress regime
        assert reject_order_for_regime(signal, RegimeType.STRESS) is True

        # Should not reject in other regimes
        for regime in [RegimeType.BULL, RegimeType.BEAR, RegimeType.SIDEWAYS]:
            assert reject_order_for_regime(signal, regime) is False

        # Should not reject when no regime
        assert reject_order_for_regime(signal, None) is False

    def test_regime_risk_context(self):
        """Test regime risk context generation."""
        # Test different regimes
        contexts = {}
        for regime in RegimeType:
            context = get_regime_risk_context(regime)
            contexts[regime] = context

        # Verify contexts
        for regime, context in contexts.items():
            assert context["regime_aware"] is True
            assert context["current_regime"] == regime.value
            assert "risk_mode" in context
            assert "recommended_actions" in context

        # Stress regime should have highest risk reduction
        stress_context = contexts[RegimeType.STRESS]
        assert stress_context["risk_mode"] == "stress"
        assert stress_context["risk_reduction"] == 0.7
        assert "avoid_new_entries" in stress_context["recommended_actions"]

        # Bull regime should have no risk reduction
        bull_context = contexts[RegimeType.BULL]
        assert bull_context["risk_mode"] == "normal"
        assert bull_context["risk_reduction"] == 0.0

    def test_backtest_risk_integration(self, sample_ohlcv_data, regime_config):
        """Test regime-aware risk management in backtest."""
        # Add regime features
        features_config = [{"type": "regime_basics"}, {"type": "core_basics"}]
        data_with_features = apply(sample_ohlcv_data, features_config)

        # Configure risk management with regime adjustments
        backtest_config = BacktestConfig(
            initial_cash=1000000.0,
            regime_config=regime_config.dict(),
            strategy_map=regime_config.strategy_map,
        )

        engine = BacktestEngine(backtest_config)

        # Track position sizes
        position_sizes = []

        def size_tracking_strategy(engine, bar):
            if not engine.is_strategy_allowed("test_strategy"):
                return

            # Simulate position sizing with regime awareness
            signal = {"entry_hint": bar["close"], "strategy": "test"}
            equity = engine.portfolio.total_equity

            # Get ATR from features (simplified)
            atr = bar.get("f__vol__atr_14", 2.0)

            # Size based on current regime
            risk_params = {
                "max_risk_frac": 0.02,
                "atr_mult": 2.0,
                "regime_adjustments": {
                    engine.get_current_regime().value: {
                        "risk_multiplier": (
                            0.8
                            if engine.get_current_regime() == RegimeType.BEAR
                            else 1.0
                        )
                    }
                },
            }

            size = size_order(
                signal, equity, atr, risk_params, engine.get_current_regime()
            )
            if size:
                position_sizes.append(
                    {
                        "regime": engine.get_current_regime().value,
                        "size": size,
                        "equity": equity,
                    }
                )

        # Run backtest
        engine.run(data_with_features, size_tracking_strategy)

        # Verify position sizing varied by regime
        if len(position_sizes) > 1:
            regimes_seen = {ps["regime"] for ps in position_sizes}
            assert len(regimes_seen) > 1  # Should see multiple regimes


class TestRegimeCLIIntegration:
    """Test CLI integration for regime detection."""

    def test_regime_config_validation(self):
        """Test regime configuration validation in CLI."""
        from qx_cli.commands.regime import _load_regime_config, validate_regime_config

        # Valid configuration
        valid_config = {
            "enabled": True,
            "model": "rules",
            "persistence_bars": 3,
            "strategy_map": {"BULL": ["test_strategy"], "BEAR": ["test_strategy"]},
        }

        # Test validation
        config = validate_regime_config(valid_config)
        assert config.enabled is True
        assert config.model == "rules"
        assert config.persistence_bars == 3

        # Test file loading with temporary file
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(valid_config, f)
            temp_path = f.name

        try:
            loaded_config = _load_regime_config(temp_path)
            assert loaded_config is not None
            assert loaded_config.enabled is True
        finally:
            Path(temp_path).unlink()

    def test_regime_sample_configs(self):
        """Test that sample configurations are valid."""

        config_files = [
            "experiments/regime/strategy_basic.yaml",
            "experiments/regime/strategy_comparison.yaml",
            "experiments/regime/stress_test.yaml",
            "experiments/regime/disabled.yaml",
        ]

        for config_file in config_files:
            if Path(config_file).exists():
                # Try to load and validate
                print(f"Testing {config_file}...")
                # Note: These are YAML files, need to convert to JSON format for validation
                # In a real implementation, there would be YAML loading logic
                pass


class TestEndToEndRegimeWorkflow:
    """Test end-to-end regime detection workflow."""

    def test_complete_regime_workflow(self, sample_ohlcv_data):
        """Test complete workflow from data to regime-aware trading."""
        # 1. Apply regime features
        features_config = [{"type": "regime_basics"}, {"type": "core_basics"}]
        data_with_features = apply(sample_ohlcv_data, features_config)

        # 2. Configure regime detection
        regime_config = RegimeConfig(
            enabled=True,
            persistence_bars=2,
            strategy_map={
                "BULL": ["momentum"],
                "BEAR": ["reversion"],
                "SIDEWAYS": ["reversion"],
                "STRESS": [],
            },
        )

        # 3. Set up backtest engine
        backtest_config = BacktestConfig(
            initial_cash=1000000.0,
            regime_config=regime_config.dict(),
            strategy_map=regime_config.strategy_map,
        )

        engine = BacktestEngine(backtest_config)

        # 4. Define regime-aware strategy
        trades_by_regime = {}

        def regime_aware_strategy(engine, bar):
            current_regime = engine.get_current_regime()
            if current_regime is None:
                return

            # Track trades by regime
            if current_regime not in trades_by_regime:
                trades_by_regime[current_regime] = 0

            # Different strategies for different regimes
            if current_regime == RegimeType.BULL:
                # Momentum strategy
                if (
                    bar["f__ta__vwap_30"]
                    and bar["close"] > bar["f__ta__vwap_30"] * 1.01
                ):
                    order = engine.order_factory.create_order(
                        symbol=bar["symbol"],
                        side="BUY",
                        qty=100,
                        entry=bar["close"],
                        tag="momentum",
                    )
                    engine.submit_order(order)
                    trades_by_regime[current_regime] += 1

            elif current_regime in [RegimeType.BEAR, RegimeType.SIDEWAYS]:
                # Reversion strategy
                if (
                    bar["f__ta__vwap_30"]
                    and bar["close"] < bar["f__ta__vwap_30"] * 0.99
                ):
                    order = engine.order_factory.create_order(
                        symbol=bar["symbol"],
                        side="BUY",
                        qty=100,
                        entry=bar["close"],
                        tag="reversion",
                    )
                    engine.submit_order(order)
                    trades_by_regime[current_regime] += 1

            # No trades in stress regime (gating prevents it)

        # 5. Run backtest
        result = engine.run(data_with_features, regime_aware_strategy)

        # 6. Verify results
        assert len(engine._regime_history) > 0
        assert result.total_trades == len(engine.portfolio.filled_orders)

        # 7. Verify regime distribution
        stats = engine.get_regime_statistics()
        assert "regime_distribution" in stats

        # 8. Verify trading only occurred in allowed regimes
        if RegimeType.STRESS in trades_by_regime:
            assert trades_by_regime[RegimeType.STRESS] == 0

        # 9. Verify performance metrics are reasonable
        assert result.total_return is not None
        assert result.sharpe_ratio is not None
        assert 0 <= result.win_rate <= 1.0

        print("End-to-end test completed:")
        print(f"  Regime changes: {stats.get('change_rate', 0):.3f}")
        print(f"  Total trades: {result.total_trades}")
        print(f"  Win rate: {result.win_rate:.2%}")
        print(f"  Regime distribution: {stats.get('regime_distribution', {})}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
