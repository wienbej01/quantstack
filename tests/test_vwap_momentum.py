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
