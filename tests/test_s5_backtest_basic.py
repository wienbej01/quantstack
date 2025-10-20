"""Basic integration tests for S5 backtesting engine."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

# Add required paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-backtest", "src"))

from qx_backtest.ab_testing import EntryExitABTest, create_default_ab_test_config
from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_backtest.order import OrderFactory, OrderSide, OrderType
from qx_backtest.policies.vwap_revert import VwapRevertPolicy
from qx_backtest.portfolio import Portfolio


class TestBacktestEngine:
    """Test backtesting engine functionality."""

    def setup_method(self):
        """Setup test data."""
        np.random.seed(42)

        # Create sample OHLCV data with features
        symbols = ["AAPL", "GOOGL"]
        dates = pd.date_range("2023-01-01", "2023-01-10", freq="D")

        bars = []
        for symbol in symbols:
            for date in dates:
                if date.weekday() >= 5:  # Skip weekends
                    continue

                # Generate OHLC data
                base_price = 100.0 if symbol == "AAPL" else 150.0
                close = base_price * (1 + np.random.normal(0, 0.02))
                high = close * (1 + abs(np.random.normal(0, 0.01)))
                low = close * (1 - abs(np.random.normal(0, 0.01)))
                open_price = low + (high - low) * np.random.uniform(0, 1)
                volume = int(1_000_000 * (1 + np.random.normal(0, 0.3)))

                # Add features
                vwap = close * (1 + np.random.normal(0, 0.005))
                rvol = 1.0 + np.random.normal(0, 0.2)
                atr = close * 0.02 * (1 + np.random.normal(0, 0.3))

                ts = pd.Timestamp(date).value

                bars.append(
                    {
                        "ts": ts,
                        "symbol": symbol,
                        "open": round(open_price, 2),
                        "high": round(high, 2),
                        "low": round(low, 2),
                        "close": round(close, 2),
                        "volume": max(volume, 1000),
                        "f__ta__vwap_30": round(vwap, 2),
                        "f__vol__rel_volume_30": round(max(rvol, 0.1), 2),
                        "f__vol__atr_14": round(max(atr, 0.1), 2),
                        "f__warmup_ok": True,
                    }
                )

        self.test_data = (
            pd.DataFrame(bars).sort_values(["ts", "symbol"]).reset_index(drop=True)
        )

    def test_engine_initialization(self):
        """Test engine initialization."""
        config = BacktestConfig(initial_cash=500_000.0)
        engine = BacktestEngine(config)

        assert engine.config.initial_cash == 500_000.0
        assert engine.portfolio.cash == 500_000.0
        assert len(engine.pending_orders) == 0
        assert len(engine.equity_curve) == 0

    def test_basic_backtest_run(self):
        """Test basic backtest execution."""
        config = BacktestConfig(initial_cash=1_000_000.0)
        engine = BacktestEngine(config)

        # Simple strategy: buy on first bar, sell on second bar for each symbol
        orders_placed = []

        def simple_strategy(engine, bar):
            symbol = bar["symbol"]
            timestamp = bar["ts"]

            # Place orders based on timestamp (simplified logic)
            if timestamp not in orders_placed:
                order = engine.order_factory.create_market_order(
                    symbol=symbol, side=OrderSide.BUY, quantity=100
                )
                engine.submit_order(order)
                orders_placed.append(timestamp)

            # Sell if we have a position
            position = engine.get_position(symbol)
            if position and not position.is_flat:
                order = engine.order_factory.create_market_order(
                    symbol=symbol, side=OrderSide.SELL, quantity=position.quantity
                )
                engine.submit_order(order)

        result = engine.run(self.test_data, simple_strategy)

        # Verify results
        assert result is not None
        assert not result.equity_curve.empty
        assert len(result.trades_history) > 0
        assert result.total_commissions >= 0

    def test_vwap_revert_policy(self):
        """Test VWAP revert policy integration."""
        config = BacktestConfig(initial_cash=1_000_000.0)
        engine = BacktestEngine(config)

        # Create VWAP revert policy
        policy = VwapRevertPolicy(
            vwap_window=30,
            min_rvol=0.5,  # Low threshold for testing
            max_position_bars=20,
            position_size_pct=0.2,
            max_positions=2,
        )

        engine.add_policy(policy)

        def strategy_func(engine, bar):
            # Policy will be called automatically via engine.add_policy
            pass

        result = engine.run(self.test_data, strategy_func)

        # Verify results
        assert result is not None
        assert not result.equity_curve.empty

    def test_portfolio_management(self):
        """Test portfolio management functionality."""
        portfolio = Portfolio(cash=100_000.0)

        # Test initial state
        assert portfolio.cash == 100_000.0
        assert portfolio.total_equity == 100_000.0
        assert len(portfolio.positions) == 0

        # Test position tracking
        from qx_backtest.fill import Fill

        fill = Fill(
            fill_id="test_fill",
            order_id="test_order",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=100,
            price=150.0,
            timestamp=1640995200000000000,
            commission=5.0,
        )

        portfolio.apply_fill(fill)

        # Verify position created
        assert len(portfolio.positions) == 1
        assert "AAPL" in portfolio.positions
        position = portfolio.positions["AAPL"]
        assert position.quantity == 100

        # Test market value update
        portfolio.update_market_values({"AAPL": 155.0})
        assert position.market_value == 100 * 155.0

    def test_order_management(self):
        """Test order management functionality."""
        order_factory = OrderFactory()

        # Test order creation
        order = order_factory.create_market_order(
            symbol="AAPL", side=OrderSide.BUY, quantity=100
        )

        assert order.symbol == "AAPL"
        assert order.side == OrderSide.BUY
        assert order.quantity == 100
        assert order.order_type == OrderType.MARKET
        assert order.is_active

        # Test order fills
        from qx_backtest.fill import Fill

        fill = Fill(
            fill_id="test_fill",
            order_id=order.order_id,
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=100,
            price=150.0,
            timestamp=1640995200000000000,
        )

        order.add_fill(fill.quantity, fill.price, fill.timestamp)

        assert order.is_fully_filled
        assert order.status.value == "FILLED"
        assert order.filled_quantity == 100

    def test_performance_metrics_calculation(self):
        """Test performance metrics calculation."""
        from qx_backtest.engine import BacktestResult

        # Create sample equity curve
        equity_data = [
            {"timestamp": 1, "total_equity": 1000000},
            {"timestamp": 2, "total_equity": 1010000},
            {"timestamp": 3, "total_equity": 1005000},
            {"timestamp": 4, "total_equity": 1020000},
            {"timestamp": 5, "total_equity": 1030000},
        ]

        result = BacktestResult()
        result.equity_curve = pd.DataFrame(equity_data)

        # Calculate metrics
        result.calculate_performance_metrics()

        # Verify calculations
        assert result.total_return > 0  # Should be positive
        assert result.annualized_return > 0
        assert result.volatility >= 0
        assert result.max_drawdown <= 0  # Drawdown should be negative or zero


class TestABTesting:
    """Test AB testing framework."""

    def setup_method(self):
        """Setup test data."""
        np.random.seed(42)

        # Create sample data
        symbols = ["AAPL", "GOOGL", "MSFT"]
        dates = pd.date_range("2023-01-01", "2023-01-20", freq="D")

        bars = []
        for symbol in symbols:
            for date in dates:
                if date.weekday() >= 5:
                    continue

                base_price = {"AAPL": 100.0, "GOOGL": 150.0, "MSFT": 200.0}[symbol]
                close = base_price * (1 + np.random.normal(0, 0.03))
                high = close * 1.02
                low = close * 0.98
                open_price = close
                volume = int(1_000_000 * (1 + np.random.normal(0, 0.5)))

                # Add features
                vwap = close * (1 + np.random.normal(0, 0.01))
                rvol = max(0.5, 1.0 + np.random.normal(0, 0.5))

                ts = pd.Timestamp(date).value

                bars.append(
                    {
                        "ts": ts,
                        "symbol": symbol,
                        "open": round(open_price, 2),
                        "high": round(high, 2),
                        "low": round(low, 2),
                        "close": round(close, 2),
                        "volume": max(volume, 1000),
                        "f__ta__vwap_30": round(vwap, 2),
                        "f__vol__rel_volume_30": round(rvol, 2),
                        "f__warmup_ok": True,
                    }
                )

        self.test_data = (
            pd.DataFrame(bars).sort_values(["ts", "symbol"]).reset_index(drop=True)
        )

    def test_ab_test_config_creation(self):
        """Test AB test configuration creation."""
        config = create_default_ab_test_config()

        assert len(config.entry_variants) == 3
        assert len(config.exit_variants) == 3
        assert config.initial_cash == 1_000_000.0
        assert config.position_size_pct == 0.1
        assert config.max_positions == 5

    def test_ab_test_basic_execution(self):
        """Test basic AB test execution."""
        config = create_default_ab_test_config()
        ab_test = EntryExitABTest(config)

        # Run with limited data for faster testing
        limited_data = self.test_data.head(100)
        result = ab_test.run_tests(limited_data)

        # Verify results
        assert result is not None
        assert result.total_tests_run > 0
        assert result.test_duration > 0
        assert len(result.entry_results) > 0
        assert len(result.exit_results) > 0

    def test_ab_test_result_analysis(self):
        """Test AB test result analysis."""
        config = create_default_ab_test_config()
        ab_test = EntryExitABTest(config)

        # Run tests
        limited_data = self.test_data.head(50)
        result = ab_test.run_tests(limited_data)

        # Test comparison analysis
        assert "ranking" in result.entry_comparison
        assert "significance_tests" in result.entry_comparison
        assert "metrics_comparison" in result.entry_comparison

        # Test best configuration identification
        assert result.best_entry is not None
        assert result.best_exit is not None

    def test_ab_test_report_generation(self):
        """Test AB test report generation."""
        config = create_default_ab_test_config()
        ab_test = EntryExitABTest(config)

        # Run tests
        limited_data = self.test_data.head(50)
        result = ab_test.run_tests(limited_data)

        # Generate report
        report = ab_test.generate_report(result)

        # Verify report content
        assert isinstance(report, str)
        assert "Entry/Exit AB Testing Report" in report
        assert "Total Tests Run:" in report
        assert "Entry Variant Results" in report
        assert "Exit Variant Results" in report


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
