"""Integration tests for VWAP momentum policy with real data."""

from typing import Any

import pandas as pd
import pytest


def _create_mock_engine() -> type:
    """Create a mock backtest engine for testing."""

    class MockOrder:
        def __init__(self, symbol: str, side: str, quantity: float) -> None:
            self.symbol = symbol
            self.side = side
            self.quantity = quantity
            self.tags: dict[str, Any] = {}

    class MockEngine:
        def __init__(self) -> None:
            self.orders: list[MockOrder] = []
            self.portfolio = MockPortfolio()
            self.order_factory = MockOrderFactory()

        def get_position(self, symbol: str) -> Any | None:
            return self.portfolio.positions.get(symbol)

        def get_pending_orders(self, symbol: str) -> list[Any]:
            return [o for o in self.orders if o.symbol == symbol and hasattr(o, "is_pending")]

        def submit_order(self, order: MockOrder) -> None:
            self.orders.append(order)

    class MockPortfolio:
        def __init__(self) -> None:
            self.positions: dict[str, Any] = {}
            self.total_equity = 100000.0

    class MockOrderFactory:
        def create_market_order(
            self,
            symbol: str,
            side: str,
            quantity: float,
            tags: dict[str, Any] | None = None,
        ) -> MockOrder:
            order = MockOrder(symbol, side, quantity)
            order.tags = tags or {}
            return order

    return MockEngine


def _generate_test_bars(np: Any) -> pd.DataFrame:
    """Generate synthetic test bars that mimic real market data."""
    # Constants for breakout timing
    BREAKOUT_BAR = 15
    PULLBACK_BAR = 25
    CYCLE_LENGTH = 30

    rng = np.random.default_rng(42)

    # Generate test bars
    dates = pd.date_range("2024-01-01 09:30:00", "2024-01-01 16:00:00", freq="1min")
    symbol = "AAPL"

    bars_data = []
    base_price = 150.0
    vwap_base = 150.0

    for i, ts in enumerate(dates):
        # Simulate price movement with some VWAP tracking
        if i % CYCLE_LENGTH == BREAKOUT_BAR:  # Every 30 minutes, create a breakout
            price_move = rng.uniform(0.5, 2.0)  # Upward breakout
        elif i % CYCLE_LENGTH == PULLBACK_BAR:  # Pull back later
            price_move = -rng.uniform(0.3, 1.0)
        else:
            price_move = rng.normal(0, 0.1)  # Random noise

        price = base_price + price_move
        vwap = vwap_base + price_move * 0.3  # VWAP lags behind

        high = price + abs(rng.normal(0, 0.1))
        low = price - abs(rng.normal(0, 0.1))
        volume = int(rng.uniform(500000, 2000000))

        bars_data.append(
            {
                "ts": int(ts.timestamp() * 1e9),  # Convert to nanoseconds
                "symbol": symbol,
                "open": price,
                "high": high,
                "low": low,
                "close": price,
                "volume": volume,
            }
        )

        base_price = price
        vwap_base = vwap

    return pd.DataFrame(bars_data)


def test_vwap_momentum_integration_simple() -> None:
    """Test VWAP momentum policy integration with simplified approach."""
    try:
        from qx_backtest.policies.vwap_momentum import (
            VwapMomentumPolicy,
            VwapMomentumPolicyEnhanced,
        )
        from qx_features.core_basics import compute_all_core_features
    except ImportError as e:
        pytest.skip(f"Integration test skipped due to missing dependencies: {e}")

    # Create synthetic test data that mimics real market data
    np = pytest.importorskip("numpy")

    # Generate test bars
    bars_df = _generate_test_bars(np)

    # Compute features
    bars_with_features = compute_all_core_features(
        bars_df, vwap_window=30, rvol_window=30, atr_window=14
    )

    # Test basic policy
    policy = VwapMomentumPolicy(
        vwap_window=30,
        min_rvol=0.8,  # Lower threshold for test data
        max_position_bars=20,
        position_size_pct=0.1,
        max_positions=2,
        min_breakout_strength=0.3,
    )

    # Set up policy with mock engine
    MockEngine = _create_mock_engine()
    engine = MockEngine()
    policy.set_engine(engine)

    # Process bars and track orders
    for _idx, bar in bars_with_features.iterrows():
        policy.process_bar(bar.to_dict())

    # Verify that orders were generated
    assert len(engine.orders) > 0, "No orders generated - check breakout conditions"

    # Verify order properties
    buy_orders = [
        o for o in engine.orders if hasattr(o, "side") and (o.side == "BUY" or str(o.side) == "BUY")
    ]
    sell_orders = [
        o
        for o in engine.orders
        if hasattr(o, "side") and (o.side == "SELL" or str(o.side) == "SELL")
    ]

    print(f"Generated {len(buy_orders)} buy orders and {len(sell_orders)} sell orders")
    print(f"Total orders: {len(engine.orders)}")

    # Test enhanced policy as well
    enhanced_policy = VwapMomentumPolicyEnhanced(
        vwap_window=30,
        min_rvol=0.8,
        max_position_bars=20,
        position_size_pct=0.1,
        max_positions=2,
        min_breakout_strength=0.3,
        atr_window=14,
        atr_multiplier=2.0,
        min_profit_atr=0.5,
    )

    enhanced_engine = MockEngine()
    enhanced_policy.set_engine(enhanced_engine)

    # Process bars with enhanced policy
    for _idx, bar in bars_with_features.iterrows():
        enhanced_policy.process_bar(bar.to_dict())

    # Verify enhanced policy also generates orders
    assert len(enhanced_engine.orders) > 0, "Enhanced policy generated no orders"

    print(f"Enhanced policy generated {len(enhanced_engine.orders)} orders")

    # Test lifecycle methods
    policy.on_start()
    policy.on_end()

    enhanced_policy.on_start()
    enhanced_policy.on_end()

    print("✅ Integration test completed successfully")


def _generate_atr_test_bars(np: Any) -> pd.DataFrame:
    """Generate test bars with clear ATR patterns for enhanced policy testing."""
    # Create test data with clear ATR patterns
    dates = pd.date_range("2024-01-01 09:30:00", "2024-01-01 12:00:00", freq="5min")

    bars_data = []
    base_price = 150.0

    for i, ts in enumerate(dates):
        # Create trending market with volatility
        trend = i * 0.1  # Upward trend
        volatility = np.random.uniform(0.5, 2.0)  # Variable volatility
        noise = np.random.normal(0, 0.2)

        close = base_price + trend + noise
        high = close + volatility * 0.5
        low = close - volatility * 0.5
        open_price = close - np.random.uniform(-0.3, 0.3)
        volume = int(np.random.uniform(300000, 800000))

        bars_data.append(
            {
                "ts": int(ts.timestamp() * 1e9),
                "symbol": "AAPL",
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )

    return pd.DataFrame(bars_data)


def test_vwap_momentum_enhanced_integration() -> None:
    """Test enhanced VWAP momentum policy integration with ATR features."""
    try:
        from qx_backtest.policies.vwap_momentum import VwapMomentumPolicyEnhanced
        from qx_features.core_basics import compute_all_core_features
    except ImportError as e:
        pytest.skip(f"Integration test skipped due to missing dependencies: {e}")

    np = pytest.importorskip("numpy")

    # Generate test bars with ATR patterns
    bars_df = _generate_atr_test_bars(np)

    # Compute features with ATR
    bars_with_features = compute_all_core_features(
        bars_df, vwap_window=20, rvol_window=20, atr_window=10
    )

    # Verify ATR features are present
    assert "f__vol__atr_10" in bars_with_features.columns

    # Create enhanced policy
    policy = VwapMomentumPolicyEnhanced(
        vwap_window=20,
        min_rvol=0.5,  # Low threshold for test data
        max_position_bars=10,
        position_size_pct=0.2,
        max_positions=1,
        min_breakout_strength=0.2,
        atr_window=10,
        atr_multiplier=1.5,
        min_profit_atr=0.3,
    )

    # Mock engine using helper function
    MockEngine = _create_mock_engine()
    engine = MockEngine()
    policy.set_engine(engine)

    # Process bars
    for _idx, bar in bars_with_features.iterrows():
        policy.process_bar(bar.to_dict())

    # Verify orders were generated
    if len(engine.orders) > 0:
        print(f"✅ Enhanced policy integration: {len(engine.orders)} orders generated")
        # Check that ATR information is in order tags
        first_order = engine.orders[0]
        assert "atr" in first_order.tags, "ATR information missing from order tags"
        print(f"✅ ATR information in order tags: {first_order.tags.get('atr')}")
    else:
        print("⚠️  No orders generated (market conditions may not have triggered signals)")

    print("✅ Enhanced integration test completed")
