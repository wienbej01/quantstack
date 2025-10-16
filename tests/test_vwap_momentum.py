def test_vwap_momentum_policy_initialization() -> None:
    """Test that VwapMomentumPolicy initializes correctly."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    policy = VwapMomentumPolicy(
        vwap_window=20,
        min_rvol=1.2,
        max_position_bars=30,
        position_size_pct=0.15,
        max_positions=3,
        min_breakout_strength=0.8,
    )

    assert policy.name == "VwapMomentum"
    assert policy.vwap_window == 20  # noqa: PLR2004
    assert policy.min_rvol == 1.2  # noqa: PLR2004
    assert policy.max_position_bars == 30  # noqa: PLR2004
    assert policy.position_size_pct == 0.15  # noqa: PLR2004
    assert policy.max_positions == 3  # noqa: PLR2004
    assert policy.min_breakout_strength == 0.8  # noqa: PLR2004


def test_process_bar_feature_validation() -> None:
    """Test that process_bar handles missing features correctly."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    policy = VwapMomentumPolicy(vwap_window=30)

    # Bar without required features should be ignored
    bar_missing_features = {
        "ts": 1640995200000000000,  # 2022-01-01 09:00:00 UTC
        "symbol": "AAPL",
        "close": 150.0,
        "high": 152.0,
        "low": 148.0,
        "volume": 1000000,
    }

    # Should not raise exception, just return without action
    policy.process_bar(bar_missing_features)
    assert len(policy.position_entry_times) == 0

    # Bar with required features should proceed to check signals
    # but will fail when trying to call get_position since no engine is attached
    bar_with_features = {
        "ts": 1640995200000000000,
        "symbol": "AAPL",
        "close": 150.0,
        "high": 152.0,
        "low": 148.0,
        "volume": 1000000,
        "f__ta__vwap_30": 149.0,
        "f__vol__rel_volume_30": 1.2,
    }

    # This should fail when trying to get position since no engine is attached
    try:
        policy.process_bar(bar_with_features)
        raise AssertionError("Should have raised ValueError for missing engine")
    except ValueError as e:
        assert "Policy must be attached to an engine" in str(e)


def test_momentum_entry_signal_long() -> None:
    """Test long entry signal when price breaks out above VWAP."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    policy = VwapMomentumPolicy(vwap_window=30, min_breakout_strength=0.5)

    # Mock engine and portfolio for testing
    class MockEngine:
        def __init__(self) -> None:
            self.orders = []
            self.portfolio = MockPortfolio()
            self.order_factory = MockOrderFactory()

        def get_position(self, symbol: str):
            """Mock get_position method."""
            return None  # No position initially

        def get_pending_orders(self, symbol: str | None = None):
            """Mock get_pending_orders method."""
            return []

        def submit_order(self, order) -> None:
            """Mock submit_order method."""
            self.orders.append(order)

    class MockPortfolio:
        def __init__(self) -> None:
            self.positions = {}
            self.total_equity = 1000000.0

    class MockOrderFactory:
        def create_market_order(self, symbol: str, side: str, quantity: int, tags=None):
            order = MockOrder(symbol, side, quantity)
            order.tags = tags or {}
            return order

    class MockOrder:
        def __init__(self, symbol: str, side: str, quantity: int):
            self.symbol = symbol
            self.side = side  # This will be OrderSide enum
            self.quantity = quantity

    policy.engine = MockEngine()

    bar = {
        "ts": 1640995200000000000,
        "symbol": "AAPL",
        "close": 152.5,  # Above VWAP - breakout signal
        "high": 153.0,
        "low": 151.0,
        "f__ta__vwap_30": 150.0,  # VWAP at 150
        "f__vol__rel_volume_30": 1.5,  # Above minimum volume
    }

    policy.process_bar(bar)

    # Should have generated a buy order
    assert len(policy.engine.orders) == 1
    assert policy.engine.orders[0].side.value == "BUY"  # OrderSide.BUY
    assert policy.engine.orders[0].symbol == "AAPL"


def test_momentum_entry_signal_short() -> None:
    """Test short entry signal when price breaks down below VWAP."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    policy = VwapMomentumPolicy(vwap_window=30, min_breakout_strength=0.5)

    # Mock engine and portfolio for testing
    class MockEngine:
        def __init__(self) -> None:
            self.orders = []
            self.portfolio = MockPortfolio()
            self.order_factory = MockOrderFactory()

        def get_position(self, symbol: str):
            """Mock get_position method."""
            return None  # No position initially

        def get_pending_orders(self, symbol: str | None = None):
            """Mock get_pending_orders method."""
            return []

        def submit_order(self, order) -> None:
            """Mock submit_order method."""
            self.orders.append(order)

    class MockPortfolio:
        def __init__(self) -> None:
            self.positions = {}
            self.total_equity = 1000000.0

    class MockOrderFactory:
        def create_market_order(self, symbol: str, side: str, quantity: int, tags=None):
            order = MockOrder(symbol, side, quantity)
            order.tags = tags or {}
            return order

    class MockOrder:
        def __init__(self, symbol: str, side: str, quantity: int):
            self.symbol = symbol
            self.side = side  # This will be OrderSide enum
            self.quantity = quantity

    policy.engine = MockEngine()

    bar = {
        "ts": 1640995200000000000,
        "symbol": "AAPL",
        "close": 147.5,  # Below VWAP - breakdown signal
        "high": 148.0,
        "low": 147.0,
        "f__ta__vwap_30": 150.0,  # VWAP at 150
        "f__vol__rel_volume_30": 1.5,  # Above minimum volume
    }

    policy.process_bar(bar)

    # Should have generated a sell order
    assert len(policy.engine.orders) == 1
    assert policy.engine.orders[0].side.value == "SELL"  # OrderSide.SELL
    assert policy.engine.orders[0].symbol == "AAPL"


def test_momentum_entry_insufficient_breakout() -> None:
    """Test that entries are rejected when breakout strength is too low."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    policy = VwapMomentumPolicy(vwap_window=30, min_breakout_strength=1.0)

    # Mock engine and portfolio
    class MockEngine:
        def __init__(self) -> None:
            self.orders = []
            self.portfolio = MockPortfolio()
            self.order_factory = MockOrderFactory()

        def get_position(self, symbol: str):
            """Mock get_position method."""
            return None  # No position initially

        def get_pending_orders(self, symbol: str | None = None):
            """Mock get_pending_orders method."""
            return []

        def submit_order(self, order) -> None:
            """Mock submit_order method."""
            self.orders.append(order)

    class MockPortfolio:
        def __init__(self) -> None:
            self.positions = {}
            self.total_equity = 1000000.0

    class MockOrderFactory:
        def create_market_order(self, symbol: str, side: str, quantity: int, tags=None):
            order = MockOrder(symbol, side, quantity)
            order.tags = tags or {}
            return order

    class MockOrder:
        def __init__(self, symbol: str, side: str, quantity: int):
            self.symbol = symbol
            self.side = side  # This will be OrderSide enum
            self.quantity = quantity

    policy.engine = MockEngine()

    bar = {
        "ts": 1640995200000000000,
        "symbol": "AAPL",
        "close": 150.8,  # Only 0.53% above VWAP - below 1.0% threshold
        "high": 151.0,
        "low": 150.5,
        "f__ta__vwap_30": 150.0,
        "f__vol__rel_volume_30": 1.5,
    }

    policy.process_bar(bar)

    # Should not have generated any order
    assert len(policy.engine.orders) == 0


def test_momentum_exit_signal_long():
    """Test long exit signal when price falls back to VWAP."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy
    from qx_backtest.portfolio import Position

    policy = VwapMomentumPolicy(vwap_window=30)

    # Mock engine and portfolio for testing
    class MockEngine:
        def __init__(self):
            self.orders = []
            self.portfolio = MockPortfolio()
            self.order_factory = MockOrderFactory()

        def get_position(self, symbol: str):
            """Mock get_position method."""
            return self.portfolio.positions.get(symbol)

        def get_pending_orders(self, symbol: str | None = None):
            """Mock get_pending_orders method."""
            return []

        def submit_order(self, order) -> None:
            """Mock submit_order method."""
            self.orders.append(order)

    class MockPortfolio:
        def __init__(self):
            self.positions = {}
            self.total_equity = 1000000.0

    class MockOrderFactory:
        def create_market_order(self, symbol: str, side: str, quantity: int, tags=None):
            order = MockOrder(symbol, side, quantity)
            order.tags = tags or {}
            return order

    class MockOrder:
        def __init__(self, symbol: str, side: str, quantity: int):
            self.symbol = symbol
            self.side = side
            self.quantity = quantity

    policy.engine = MockEngine()

    # Simulate existing long position
    position = Position(symbol="AAPL", quantity=100, avg_cost=152.0)
    policy.engine.portfolio.positions["AAPL"] = position
    policy.position_entry_times["AAPL"] = 1640995200000000000

    bar = {
        "ts": 1640995260000000000,  # 1 minute later
        "symbol": "AAPL",
        "close": 150.0,  # Back to VWAP (exit signal)
        "high": 151.0,
        "low": 149.0,
        "f__ta__vwap_30": 150.0,
        "f__vol__rel_volume_30": 1.2,
    }

    policy.process_bar(bar)

    # Should have generated a sell order to exit long
    assert len(policy.engine.orders) == 1
    assert policy.engine.orders[0].side.value == "SELL"  # OrderSide.SELL
    assert "EXIT_LONG" in policy.engine.orders[0].tags["direction"]


def test_momentum_exit_signal_short():
    """Test short exit signal when price rises back to VWAP."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy
    from qx_backtest.portfolio import Position

    policy = VwapMomentumPolicy(vwap_window=30)

    # Mock engine and portfolio for testing
    class MockEngine:
        def __init__(self):
            self.orders = []
            self.portfolio = MockPortfolio()
            self.order_factory = MockOrderFactory()

        def get_position(self, symbol: str):
            """Mock get_position method."""
            return self.portfolio.positions.get(symbol)

        def get_pending_orders(self, symbol: str | None = None):
            """Mock get_pending_orders method."""
            return []

        def submit_order(self, order) -> None:
            """Mock submit_order method."""
            self.orders.append(order)

    class MockPortfolio:
        def __init__(self):
            self.positions = {}
            self.total_equity = 1000000.0

    class MockOrderFactory:
        def create_market_order(self, symbol: str, side: str, quantity: int, tags=None):
            order = MockOrder(symbol, side, quantity)
            order.tags = tags or {}
            return order

    class MockOrder:
        def __init__(self, symbol: str, side: str, quantity: int):
            self.symbol = symbol
            self.side = side
            self.quantity = quantity

    policy.engine = MockEngine()

    # Simulate existing short position
    position = Position(symbol="AAPL", quantity=-100, avg_cost=148.0)
    policy.engine.portfolio.positions["AAPL"] = position
    policy.position_entry_times["AAPL"] = 1640995200000000000

    bar = {
        "ts": 1640995260000000000,  # 1 minute later
        "symbol": "AAPL",
        "close": 150.0,  # Back to VWAP (exit signal for short)
        "high": 151.0,
        "low": 149.0,
        "f__ta__vwap_30": 150.0,
        "f__vol__rel_volume_30": 1.2,
    }

    policy.process_bar(bar)

    # Should have generated a buy order to exit short
    assert len(policy.engine.orders) == 1
    assert policy.engine.orders[0].side.value == "BUY"  # OrderSide.BUY
    assert "EXIT_SHORT" in policy.engine.orders[0].tags["direction"]


def test_momentum_exit_timeout():
    """Test exit when maximum bars are reached."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy
    from qx_backtest.portfolio import Position

    policy = VwapMomentumPolicy(vwap_window=30, max_position_bars=10)

    # Mock engine and portfolio
    class MockEngine:
        def __init__(self):
            self.orders = []
            self.portfolio = MockPortfolio()
            self.order_factory = MockOrderFactory()

        def get_position(self, symbol: str):
            """Mock get_position method."""
            return self.portfolio.positions.get(symbol)

        def get_pending_orders(self, symbol: str | None = None):
            """Mock get_pending_orders method."""
            return []

        def submit_order(self, order) -> None:
            """Mock submit_order method."""
            self.orders.append(order)

    class MockPortfolio:
        def __init__(self):
            self.positions = {}
            self.total_equity = 1000000.0

    class MockOrderFactory:
        def create_market_order(self, symbol: str, side: str, quantity: int, tags=None):
            order = MockOrder(symbol, side, quantity)
            order.tags = tags or {}
            return order

    class MockOrder:
        def __init__(self, symbol: str, side: str, quantity: int):
            self.symbol = symbol
            self.side = side
            self.quantity = quantity

    policy.engine = MockEngine()

    # Simulate existing long position with old entry time
    position = Position(symbol="AAPL", quantity=100, avg_cost=152.0)
    policy.engine.portfolio.positions["AAPL"] = position
    # Set entry time to 15 minutes ago (exceeding max_position_bars=10)
    old_entry_time = 1640995200000000000 - (15 * 60 * 1_000_000_000)
    policy.position_entry_times["AAPL"] = old_entry_time

    bar = {
        "ts": 1640995200000000000,
        "symbol": "AAPL",
        "close": 155.0,  # Still above VWAP but should exit due to timeout
        "high": 156.0,
        "low": 154.0,
        "f__ta__vwap_30": 150.0,
        "f__vol__rel_volume_30": 1.2,
    }

    policy.process_bar(bar)

    # Should have generated a sell order due to timeout
    assert len(policy.engine.orders) == 1
    assert policy.engine.orders[0].side.value == "SELL"
    assert policy.engine.orders[0].tags["exit_reason"] == "timeout_long"


def test_calculate_position_size():
    """Test position size calculation based on equity percentage."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    # Constants for testing
    EXPECTED_SHARES_100_PRICE = 1000
    EXPECTED_SHARES_500_PRICE = 200
    EXPECTED_SHARES_HALF_EQUITY = 500

    policy = VwapMomentumPolicy(position_size_pct=0.1)

    # Mock engine with portfolio
    class MockEngine:
        def __init__(self):
            self.portfolio = MockPortfolio()

    class MockPortfolio:
        def __init__(self):
            self.total_equity = 1000000.0

    policy.engine = MockEngine()

    # With $1M equity and 10% allocation, at $100/share should get 1000 shares
    position_size = policy._calculate_position_size(100.0)
    assert position_size == EXPECTED_SHARES_100_PRICE

    # Test with higher price
    position_size_500 = policy._calculate_position_size(500.0)
    assert (
        position_size_500 == EXPECTED_SHARES_500_PRICE
    )  # $100,000 / $500 = 200 shares

    # Test minimum size constraint (should return 0 if can't afford 1 share)
    position_size_expensive = policy._calculate_position_size(
        2000000.0
    )  # $2M per share
    assert position_size_expensive == 0  # Should be 0 if can't afford at least 1 share

    # Test different equity amount
    policy.engine.portfolio.total_equity = 500000.0  # $500K equity
    position_size_half = policy._calculate_position_size(100.0)
    assert (
        position_size_half == EXPECTED_SHARES_HALF_EQUITY
    )  # $50,000 / $100 = 500 shares


def test_lifecycle_methods():
    """Test on_start and on_end lifecycle methods."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    policy = VwapMomentumPolicy()

    # Start with some position entry times
    policy.position_entry_times["AAPL"] = 1640995200000000000
    policy.position_entry_times["MSFT"] = 1640995260000000000

    # on_start should clear position entry times
    policy.on_start()
    assert len(policy.position_entry_times) == 0

    # Add some positions again for on_end test
    policy.position_entry_times["AAPL"] = 1640995200000000000
    policy.position_entry_times["MSFT"] = 1640995260000000000

    # on_end should complete without errors (may log statistics)
    policy.on_end()  # Should not raise any exceptions


def test_position_sizing_edge_cases():
    """Test edge cases in position sizing."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    policy = VwapMomentumPolicy(position_size_pct=0.1)

    # Mock engine with portfolio
    class MockEngine:
        def __init__(self):
            self.portfolio = MockPortfolio()

    class MockPortfolio:
        def __init__(self):
            self.total_equity = 1000000.0

    policy.engine = MockEngine()

    # Test with zero price (should not crash)
    try:
        size_zero_price = policy._calculate_position_size(0.0)
        assert size_zero_price == 0
    except (ZeroDivisionError, ValueError):
        # Either is acceptable - just should not crash the program
        pass

    # Test with negative price (should not crash)
    try:
        size_negative_price = policy._calculate_position_size(-100.0)
        # If it doesn't crash, the size should be 0 or handled gracefully
        assert size_negative_price >= 0
    except (ValueError, ZeroDivisionError):
        # Either is acceptable - just should not crash the program
        pass

    # Test with very small percentage
    policy.position_size_pct = 0.0001  # 0.01%
    size_small_pct = policy._calculate_position_size(100.0)
    assert size_small_pct == 1  # $100 / $100 = 1 share

    # Reset for other tests
    policy.position_size_pct = 0.1


def test_calculate_bars_held():
    """Test bars held calculation with different time intervals."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicy

    # Constants for testing
    MINUTES_30 = 30

    policy = VwapMomentumPolicy()

    # Test 1 minute later (should be 1 bar)
    entry_time = 1640995200000000000  # 2022-01-01 09:00:00 UTC
    one_minute_later = entry_time + (60 * 1_000_000_000)  # 1 minute in nanoseconds
    bars_held = policy._calculate_bars_held(entry_time, one_minute_later)
    assert bars_held == 1

    # Test 30 minutes later (should be 30 bars)
    thirty_minutes_later = entry_time + (MINUTES_30 * 60 * 1_000_000_000)
    bars_held_30 = policy._calculate_bars_held(entry_time, thirty_minutes_later)
    assert bars_held_30 == MINUTES_30

    # Test same time (should be 0 bars)
    same_time = entry_time
    bars_held_0 = policy._calculate_bars_held(entry_time, same_time)
    assert bars_held_0 == 0

    # Test earlier time (should be 0 or negative, but should not crash)
    earlier_time = entry_time - (60 * 1_000_000_000)
    bars_held_negative = policy._calculate_bars_held(entry_time, earlier_time)
    assert bars_held_negative <= 0


def test_vwap_momentum_enhanced_initialization():
    """Test enhanced policy with ATR stops."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicyEnhanced

    policy = VwapMomentumPolicyEnhanced(
        vwap_window=20,
        min_rvol=1.2,
        atr_window=14,
        atr_multiplier=2.0,
        min_profit_atr=1.0,
    )

    assert policy.name == "VwapMomentumEnhanced"
    assert policy.vwap_window == 20
    assert policy.min_rvol == 1.2
    assert policy.atr_window == 14
    assert policy.atr_multiplier == 2.0
    assert policy.min_profit_atr == 1.0


def test_enhanced_entry_signal_with_atr():
    """Test enhanced entry signal includes ATR validation."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicyEnhanced

    policy = VwapMomentumPolicyEnhanced(
        vwap_window=30,
        min_breakout_strength=0.5,
        atr_window=14,
        min_profit_atr=2.0,  # Higher requirement - need 2x ATR profit potential
    )

    # Mock engine and portfolio
    class MockEngine:
        def __init__(self):
            self.orders = []
            self.portfolio = MockPortfolio()
            self.order_factory = MockOrderFactory()

        def get_position(self, symbol: str):
            """Mock get_position method."""
            return None  # No position initially

        def get_pending_orders(self, symbol: str | None = None):
            """Mock get_pending_orders method."""
            return []

        def submit_order(self, order) -> None:
            """Mock submit_order method."""
            self.orders.append(order)

    class MockPortfolio:
        def __init__(self):
            self.positions = {}
            self.total_equity = 1000000.0

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

    policy.engine = MockEngine()

    bar = {
        "ts": 1640995200000000000,
        "symbol": "AAPL",
        "close": 152.0,  # 2.0 above VWAP (1.33% breakout)
        "high": 152.5,
        "low": 151.5,
        "f__ta__vwap_30": 150.0,
        "f__vol__rel_volume_30": 1.5,
        "f__vol__atr_14": 2.0,  # ATR of $2.0, breakout is only 1x ATR
    }

    policy.process_bar(bar)

    # Should NOT have generated order (breakout < min_profit_atr * ATR)
    # 2.0 breakout < 2.0 * 2.0 ATR requirement = 4.0
    assert len(policy.engine.orders) == 0


def test_enhanced_exit_signal_with_atr():
    """Test enhanced exit signal with ATR-based stops and profit targets."""
    from qx_backtest.policies.vwap_momentum import VwapMomentumPolicyEnhanced
    from qx_backtest.portfolio import Position

    policy = VwapMomentumPolicyEnhanced(
        vwap_window=30, atr_window=14, atr_multiplier=2.0, min_profit_atr=1.0
    )

    # Mock engine and portfolio
    class MockEngine:
        def __init__(self):
            self.orders = []
            self.portfolio = MockPortfolio()
            self.order_factory = MockOrderFactory()

        def get_position(self, symbol: str):
            """Mock get_position method."""
            return self.portfolio.positions.get(symbol)

        def get_pending_orders(self, symbol: str | None = None):
            """Mock get_pending_orders method."""
            return []

        def submit_order(self, order) -> None:
            """Mock submit_order method."""
            self.orders.append(order)

    class MockPortfolio:
        def __init__(self):
            self.positions = {}
            self.total_equity = 1000000.0

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

    policy.engine = MockEngine()

    # Simulate existing long position
    position = Position(symbol="AAPL", quantity=100, avg_cost=152.0)
    policy.engine.portfolio.positions["AAPL"] = position
    policy.position_entry_times["AAPL"] = 1640995200000000000

    bar = {
        "ts": 1640995260000000000,  # 1 minute later
        "symbol": "AAPL",
        "close": 148.0,  # Below stop loss (152.0 - 2.0 * 2.0 = 148.0)
        "high": 149.0,
        "low": 147.0,
        "f__ta__vwap_30": 150.0,
        "f__vol__rel_volume_30": 1.2,
        "f__vol__atr_14": 2.0,  # ATR of $2.0
    }

    policy.process_bar(bar)

    # Should have generated sell order due to stop loss
    assert len(policy.engine.orders) == 1
    assert policy.engine.orders[0].side.value == "SELL"
    assert policy.engine.orders[0].tags["exit_reason"] == "stop_loss"


def test_legacy_generate_signals():
    """Test legacy signal generation function for compatibility."""
    import pandas as pd

    from qx_backtest.policies.vwap_momentum import generate_signals

    # Create test data with breakout above VWAP
    data = {
        "ts": [1640995200000000000, 1640995260000000000, 1640995320000000000],
        "symbol": ["AAPL", "AAPL", "AAPL"],
        "close": [149.0, 152.0, 153.0],  # Breaking out above VWAP
        "high": [149.5, 152.5, 153.5],
        "low": [148.5, 151.5, 152.5],
        "f__ta__vwap_30": [149.0, 149.2, 149.4],  # VWAP trending up
        "f__vol__rel_volume_30": [1.2, 1.5, 1.8],
        "f__warmup_ok": [True, True, True],
    }
    df = pd.DataFrame(data)

    params = {
        "rvol_min": 1.0,
        "vwap_col": "f__ta__vwap_30",
        "rvol_col": "f__vol__rel_volume_30",
        "timeout_bars": 10,
        "min_breakout_strength": 0.5,
    }

    signals = generate_signals(df, params)

    assert len(signals) == 3
    assert "signal" in signals.columns
    assert "breakout_strength" in signals.columns
    assert signals.iloc[0]["signal"] == 0  # No signal initially (close = VWAP)
    assert signals.iloc[1]["signal"] == 1  # Long signal on breakout
    assert signals.iloc[2]["signal"] == 1  # Still in position
    assert signals.iloc[1]["decision"] == "enter"


def test_legacy_generate_signals_short():
    """Test legacy signal generation for short breakdowns."""
    import pandas as pd

    from qx_backtest.policies.vwap_momentum import generate_signals

    # Create test data with breakdown below VWAP
    data = {
        "ts": [1640995200000000000, 1640995260000000000, 1640995320000000000],
        "symbol": ["AAPL", "AAPL", "AAPL"],
        "close": [151.0, 148.0, 147.0],  # Breaking down below VWAP
        "high": [151.5, 148.5, 147.5],
        "low": [150.5, 147.5, 146.5],
        "f__ta__vwap_30": [151.0, 150.8, 150.6],  # VWAP trending down
        "f__vol__rel_volume_30": [1.2, 1.5, 1.8],
        "f__warmup_ok": [True, True, True],
    }
    df = pd.DataFrame(data)

    params = {
        "rvol_min": 1.0,
        "vwap_col": "f__ta__vwap_30",
        "rvol_col": "f__vol__rel_volume_30",
        "timeout_bars": 10,
        "min_breakout_strength": 0.5,
    }

    signals = generate_signals(df, params)

    assert len(signals) == 3
    assert signals.iloc[0]["signal"] == 0  # No signal initially (close = VWAP)
    # Note: Current implementation only supports long signals (1) vs flat (0)
    # Since close < vwap, it doesn't trigger entry for this momentum strategy
    assert signals.iloc[1]["decision"] == "hold"  # No entry for breakdown
    assert signals.iloc[2]["decision"] == "hold"  # Continue holding


def test_legacy_generate_signals_timeout():
    """Test legacy signal generation timeout logic."""
    import pandas as pd

    from qx_backtest.policies.vwap_momentum import generate_signals

    # Create test data with position that times out
    data = {
        "ts": [
            1640995200000000000,
            1640995260000000000,
            1640995320000000000,
            1640995380000000000,
            1640995440000000000,
        ],
        "symbol": ["AAPL", "AAPL", "AAPL", "AAPL", "AAPL"],
        "close": [149.0, 152.0, 153.0, 154.0, 155.0],  # Continues above VWAP
        "f__ta__vwap_30": [149.0, 149.2, 149.4, 149.6, 149.8],  # VWAP follows
        "f__vol__rel_volume_30": [1.5, 1.5, 1.5, 1.5, 1.5],
        "f__warmup_ok": [True, True, True, True, True],
    }
    df = pd.DataFrame(data)

    params = {
        "rvol_min": 1.0,
        "vwap_col": "f__ta__vwap_30",
        "rvol_col": "f__vol__rel_volume_30",
        "timeout_bars": 2,  # Very short timeout for testing
        "min_breakout_strength": 0.5,
    }

    signals = generate_signals(df, params)

    assert len(signals) == 5
    assert signals.iloc[1]["decision"] == "enter"  # Enter on breakout (bars_held = 1)
    assert (
        signals.iloc[2]["decision"] == "exit"
    )  # Exit due to timeout (bars_held = 2 >= timeout_bars)
    assert signals.iloc[2]["signal"] == 0  # Signal goes to 0 after exit
    # After exit, position can immediately re-enter if conditions are still met
    assert signals.iloc[3]["decision"] == "enter"  # Re-enter after exit
    assert signals.iloc[3]["signal"] == 1  # Signal back to 1
    assert (
        signals.iloc[4]["decision"] == "exit"
    )  # Exit again due to timeout (bars_held = 2 >= timeout_bars)
    assert signals.iloc[4]["signal"] == 0  # Signal goes to 0 after second exit


def test_legacy_generate_signals_sip_filter():
    """Test legacy signal generation with SIP universe filtering."""
    import pandas as pd

    from qx_backtest.policies.vwap_momentum import generate_signals

    # Create test data
    data = {
        "ts": [1640995200000000000, 1640995260000000000],
        "symbol": ["AAPL", "AAPL"],
        "close": [149.0, 152.0],  # Breakout above VWAP
        "f__ta__vwap_30": [149.0, 149.2],
        "f__vol__rel_volume_30": [1.5, 1.5],
        "f__warmup_ok": [True, True],
    }
    df = pd.DataFrame(data)

    # Create SIP universe that excludes AAPL at the breakout time
    sip_universe = {
        1640995200000000000: {"MSFT", "GOOG"},  # AAPL not in universe
        1640995260000000000: {"AAPL", "MSFT"},  # AAPL added to universe
    }

    params = {
        "rvol_min": 1.0,
        "vwap_col": "f__ta__vwap_30",
        "rvol_col": "f__vol__rel_volume_30",
        "timeout_bars": 10,
        "min_breakout_strength": 0.5,
        "sip_universe": sip_universe,
    }

    signals = generate_signals(df, params)

    # Should not enter at first bar (AAPL not in SIP universe)
    assert signals.iloc[0]["in_sip"] == False
    assert signals.iloc[0]["decision"] == "hold"
    assert signals.iloc[0]["signal"] == 0

    # Should enter at second bar (AAPL now in SIP universe)
    assert signals.iloc[1]["in_sip"] == True
    assert signals.iloc[1]["decision"] == "enter"
    assert signals.iloc[1]["signal"] == 1
