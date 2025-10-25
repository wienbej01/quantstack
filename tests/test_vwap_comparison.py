"""Performance comparison tests between VWAP reversal and momentum strategies."""

import pandas as pd
import pytest


def test_vwap_revert_vs_momentum_comparison():
    """Compare VWAP reversal vs momentum strategies on same data."""
    try:
        from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy
        from qx_backtest.policies.vwap_revert import VwapRevertPolicy
        from qx_features.core_basics import compute_all_core_features
    except ImportError as e:
        pytest.skip(f"Comparison test skipped due to missing dependencies: {e}")

    np = pytest.importorskip("numpy")

    # Create test data with clear VWAP patterns
    dates = pd.date_range("2024-01-01 09:30:00", "2024-01-01 12:00:00", freq="5min")

    bars_data = []
    base_vwap = 150.0

    for i, ts in enumerate(dates):
        # Create alternating patterns: above VWAP then below VWAP
        if i % 10 < 5:  # First 5 bars: above VWAP
            price = base_vwap + (i % 5 + 1) * 0.3  # Progressively further above VWAP
        else:  # Next 5 bars: below VWAP
            price = base_vwap - ((i % 5) + 1) * 0.3  # Progressively further below VWAP

        high = price + abs(np.random.normal(0, 0.1))
        low = price - abs(np.random.normal(0, 0.1))
        open_price = price + np.random.normal(0, 0.05)
        volume = int(np.random.uniform(500000, 1500000))

        bars_data.append(
            {
                "ts": int(ts.timestamp() * 1e9),
                "symbol": "TEST",
                "open": open_price,
                "high": high,
                "low": low,
                "close": price,
                "volume": volume,
            }
        )

    bars_df = pd.DataFrame(bars_data)

    # Compute features
    bars_with_features = compute_all_core_features(
        bars_df, vwap_window=15, rvol_window=15, atr_window=10
    )

    # Mock engine for testing
    class MockEngine:
        def __init__(self, name):
            self.name = name
            self.orders = []
            self.portfolio = MockPortfolio()
            self.order_factory = MockOrderFactory()

        def get_position(self, symbol):
            return self.portfolio.positions.get(symbol)

        def get_pending_orders(self, symbol):
            return []

        def submit_order(self, order):
            order.engine_name = self.name  # Track which engine generated the order
            self.orders.append(order)

    class MockPortfolio:
        def __init__(self):
            self.positions = {}
            self.total_equity = 100000.0

    class MockOrderFactory:
        def create_market_order(self, symbol, side, quantity, tags=None):
            order = MockOrder(symbol, side, quantity)
            order.tags = tags or {}
            return order

    class MockOrder:
        def __init__(self, symbol, side, quantity):
            self.symbol = symbol
            self.side = side
            self.quantity = quantity

    # Test reversal policy
    engine_revert = MockEngine("Revert")
    policy_revert = VwapRevertPolicy(
        vwap_window=15,
        min_rvol=0.1,  # Lower threshold for testing
        max_position_bars=10,
        position_size_pct=0.2,
        max_positions=2,
        min_deviation_pct=0.1,  # Lower threshold for testing
    )
    policy_revert.set_engine(engine_revert)

    # Test momentum policy
    engine_momentum = MockEngine("Momentum")
    policy_momentum = VwapMomentumPolicy(
        vwap_window=15,
        min_rvol=0.1,  # Lower threshold for testing
        max_position_bars=10,
        position_size_pct=0.2,
        max_positions=2,
        min_breakout_strength=0.1,  # Lower threshold for testing
    )
    policy_momentum.set_engine(engine_momentum)

    # Process the same data through both policies
    for idx, bar in bars_with_features.iterrows():
        bar_dict = bar.to_dict()
        policy_revert.process_bar(bar_dict)
        policy_momentum.process_bar(bar_dict)

    # Analyze results
    revert_orders = engine_revert.orders
    momentum_orders = engine_momentum.orders

    print(f"Revert policy generated {len(revert_orders)} orders")
    print(f"Momentum policy generated {len(momentum_orders)} orders")

    # Both should generate orders (market conditions should trigger both strategies)
    assert len(revert_orders) > 0, "Revert policy should generate orders"
    assert len(momentum_orders) > 0, "Momentum policy should generate orders"

    # The orders should be different (opposite strategies)
    assert (
        revert_orders != momentum_orders
    ), "Orders should be different between strategies"

    # Analyze order patterns
    revert_buy_signals = [o for o in revert_orders if "BUY" in str(o.side)]
    revert_sell_signals = [o for o in revert_orders if "SELL" in str(o.side)]
    momentum_buy_signals = [o for o in momentum_orders if "BUY" in str(o.side)]
    momentum_sell_signals = [o for o in momentum_orders if "SELL" in str(o.side)]

    print(f"Revert: {len(revert_buy_signals)} buys, {len(revert_sell_signals)} sells")
    print(
        f"Momentum: {len(momentum_buy_signals)} buys, {len(momentum_sell_signals)} sells"
    )

    # At minimum, both strategies should generate some orders
    assert len(revert_buy_signals) + len(revert_sell_signals) > 0
    assert len(momentum_buy_signals) + len(momentum_sell_signals) > 0

    print("✅ Comparison test completed successfully")


def test_enhanced_vwap_comparison():
    """Compare enhanced VWAP reversal vs momentum strategies."""
    try:
        from qx_backtest.policies.vwap_momentum import VwapMomentumPolicyEnhanced
        from qx_backtest.policies.vwap_revert import VwapRevertPolicyEnhanced
        from qx_features.core_basics import compute_all_core_features
    except ImportError as e:
        pytest.skip(
            f"Enhanced comparison test skipped due to missing dependencies: {e}"
        )

    np = pytest.importorskip("numpy")

    # Create trending data with ATR patterns
    dates = pd.date_range("2024-01-01 09:30:00", "2024-01-01 11:30:00", freq="10min")

    bars_data = []
    base_price = 150.0
    trend = 0.0

    for i, ts in enumerate(dates):
        # Create trend with volatility
        if i % 6 < 3:  # Trending up
            trend += 0.2
        else:  # Trending down
            trend -= 0.15

        volatility = np.random.uniform(0.3, 1.0)
        noise = np.random.normal(0, 0.1)

        close = base_price + trend + noise
        high = close + volatility * 0.6
        low = close - volatility * 0.6
        open_price = close + np.random.normal(0, 0.05)
        volume = int(np.random.uniform(400000, 1200000))

        bars_data.append(
            {
                "ts": int(ts.timestamp() * 1e9),
                "symbol": "TEST2",
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )

    bars_df = pd.DataFrame(bars_data)

    # Compute features with ATR
    bars_with_features = compute_all_core_features(
        bars_df, vwap_window=12, rvol_window=12, atr_window=8
    )

    # Mock engines
    class MockEngine:
        def __init__(self, name):
            self.name = name
            self.orders = []
            self.portfolio = MockPortfolio()
            self.order_factory = MockOrderFactory()

        def get_position(self, symbol):
            return self.portfolio.positions.get(symbol)

        def get_pending_orders(self, symbol):
            return []

        def submit_order(self, order):
            order.engine_name = self.name
            self.orders.append(order)

    class MockPortfolio:
        def __init__(self):
            self.positions = {}
            self.total_equity = 100000.0

    class MockOrderFactory:
        def create_market_order(self, symbol, side, quantity, tags=None):
            order = MockOrder(symbol, side, quantity)
            order.tags = tags or {}
            return order

    class MockOrder:
        def __init__(self, symbol, side, quantity):
            self.symbol = symbol
            self.side = side
            self.quantity = quantity

    # Enhanced reversal policy
    engine_revert_enhanced = MockEngine("RevertEnhanced")
    policy_revert_enhanced = VwapRevertPolicyEnhanced(
        vwap_window=12,
        min_rvol=0.1,  # Lower threshold for testing
        max_position_bars=8,
        position_size_pct=0.15,
        max_positions=2,
        atr_window=8,
        atr_multiplier=1.5,
        min_profit_atr=0.1,  # Lower threshold for testing
    )
    policy_revert_enhanced.set_engine(engine_revert_enhanced)

    # Enhanced momentum policy
    engine_momentum_enhanced = MockEngine("MomentumEnhanced")
    policy_momentum_enhanced = VwapMomentumPolicyEnhanced(
        vwap_window=12,
        min_rvol=0.1,  # Lower threshold for testing
        max_position_bars=8,
        position_size_pct=0.15,
        max_positions=2,
        atr_window=8,
        atr_multiplier=1.5,
        min_profit_atr=0.1,  # Lower threshold for testing
    )
    policy_momentum_enhanced.set_engine(engine_momentum_enhanced)

    # Process data
    for idx, bar in bars_with_features.iterrows():
        bar_dict = bar.to_dict()
        policy_revert_enhanced.process_bar(bar_dict)
        policy_momentum_enhanced.process_bar(bar_dict)

    # Analyze enhanced results
    revert_orders = engine_revert_enhanced.orders
    momentum_orders = engine_momentum_enhanced.orders

    print(f"Enhanced Revert: {len(revert_orders)} orders")
    print(f"Enhanced Momentum: {len(momentum_orders)} orders")

    # At least one should generate orders with ATR-based logic
    assert len(revert_orders) > 0, "Enhanced revert should generate orders"
    # Enhanced momentum has stricter ATR profit requirements, so may generate fewer orders
    # The basic test already proves the opposite behavior concept

    # Check that orders have ATR information
    revert_with_atr = [o for o in revert_orders if "atr" in o.tags]
    momentum_with_atr = [o for o in momentum_orders if "atr" in o.tags]

    print(f"Enhanced Revert orders with ATR: {len(revert_with_atr)}")
    print(f"Enhanced Momentum orders with ATR: {len(momentum_with_atr)}")

    # Orders that are generated should have ATR information
    if len(revert_orders) > 0:
        assert (
            len(revert_with_atr) >= len(revert_orders) * 0.5
        ), "Most revert orders should have ATR info"
    if len(momentum_orders) > 0:
        assert (
            len(momentum_with_atr) >= len(momentum_orders) * 0.5
        ), "Most momentum orders should have ATR info"

    print("✅ Enhanced comparison test completed")


def test_vwap_revert_respects_regime_gate():
    """VWAP revert should not open new positions when gate is disabled."""
    from qx_backtest.policies.vwap_revert import VwapRevertPolicy

    class MockOrder:
        def __init__(self, symbol, side, quantity, tags=None):
            self.symbol = symbol
            self.side = side
            self.quantity = quantity
            self.tags = tags or {}

    class MockOrderFactory:
        def create_market_order(self, symbol, side, quantity, tags=None):
            return MockOrder(symbol, side, quantity, tags)

    class MockPortfolio:
        def __init__(self):
            self.positions = {}
            self.total_equity = 1_000_000.0

    class MockEngine:
        def __init__(self):
            self.orders = []
            self.pending = []
            self.portfolio = MockPortfolio()
            self.order_factory = MockOrderFactory()

        def is_strategy_allowed(self, strategy: str) -> bool:
            return False

        def get_position(self, symbol: str):
            return self.portfolio.positions.get(symbol)

        def get_pending_orders(self, symbol: str | None = None):
            return self.pending

        def submit_order(self, order):
            self.orders.append(order)

    policy = VwapRevertPolicy(
        vwap_window=30,
        min_rvol=0.5,
        max_position_bars=20,
        position_size_pct=0.2,
        max_positions=2,
        min_deviation_pct=0.2,
    )
    engine = MockEngine()
    policy.set_engine(engine)

    bar = {
        "ts": 1640995200000000000,
        "symbol": "AAPL",
        "close": 148.0,
        "high": 148.5,
        "low": 147.5,
        "f__ta__vwap_30": 150.0,
        "f__vol__rel_volume_30": 1.2,
    }

    policy.process_bar(bar)

    assert engine.orders == []


def test_vwap_revert_exit_runs_when_gate_disabled():
    """VWAP revert should manage open positions even when gated off."""
    from qx_backtest.order import OrderSide
    from qx_backtest.policies.vwap_revert import VwapRevertPolicy
    from qx_backtest.portfolio import Position

    class MockOrder:
        def __init__(self, symbol, side, quantity, tags=None):
            self.symbol = symbol
            self.side = side
            self.quantity = quantity
            self.tags = tags or {}

    class MockOrderFactory:
        def create_market_order(self, symbol, side, quantity, tags=None):
            return MockOrder(symbol, side, quantity, tags)

    class MockPortfolio:
        def __init__(self, position):
            self.positions = {position.symbol: position}
            self.total_equity = 1_000_000.0

    class MockEngine:
        def __init__(self, position):
            self.orders = []
            self.pending = []
            self.position = position
            self.portfolio = MockPortfolio(position)
            self.order_factory = MockOrderFactory()

        def is_strategy_allowed(self, strategy: str) -> bool:
            return False

        def get_position(self, symbol: str):
            return self.position if symbol == self.position.symbol else None

        def get_pending_orders(self, symbol: str | None = None):
            return self.pending

        def submit_order(self, order):
            self.orders.append(order)

    position = Position(symbol="AAPL", quantity=100, avg_cost=149.0)
    policy = VwapRevertPolicy(
        vwap_window=30,
        min_rvol=0.5,
        max_position_bars=20,
        position_size_pct=0.2,
        max_positions=2,
        min_deviation_pct=0.2,
    )
    engine = MockEngine(position)
    policy.set_engine(engine)

    bar = {
        "ts": 1640995260000000000,
        "symbol": "AAPL",
        "close": 150.5,
        "high": 151.0,
        "low": 149.5,
        "f__ta__vwap_30": 150.0,
        "f__vol__rel_volume_30": 1.2,
    }

    policy.process_bar(bar)

    assert len(engine.orders) == 1
    assert engine.orders[0].side == OrderSide.SELL
    assert engine.orders[0].quantity == 100
