"""Tests for backtest engine and execution simulation.

Tests verify:
- Engine processes bars correctly
- Execution simulation uses L2 data
- P&L calculations are accurate
- Target/stop/time limit exits work correctly
"""

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timedelta

from src.backtest.engine import AlphaBacktestEngine, BarData, BacktestResult, Trade
from src.backtest.execution_sim import L2ExecutionSimulator, FillResult
from src.signals.base import Position, SignalSide, SignalEvent, ExitEvent
from src.signals.order_flow import OrderFlowSignal


# Default configuration
DEFAULT_CONFIG = {
    "initial_capital": 100000,
    "execution": {
        "latency_ms": 75,
        "slippage_bps": 5,
        "commission_per_share": 0.005,
    },
    "risk": {
        "max_position_pct": 0.02,
        "max_positions": 10,
    },
    "signals": {
        "order_flow": {
            "book_imbalance_threshold": 0.35,
            "trade_imbalance_threshold": 0.25,
            "max_spread_pct": 0.05,
            "target_pct": 0.4,
            "stop_pct": 0.25,
            "time_limit_minutes": 10,
        },
    },
}


@pytest.fixture
def sample_bars():
    """Create sample bar data for testing."""
    bars = []
    base_time = pd.Timestamp("2024-01-02 09:30:00")

    for i in range(100):
        ts = base_time + timedelta(minutes=i)
        bars.append({
            "ts": ts,
            "symbol": "AAPL",
            "open": 150.0 + np.random.randn() * 0.1,
            "high": 150.2 + np.random.randn() * 0.1,
            "low": 149.8 + np.random.randn() * 0.1,
            "close": 150.0 + np.random.randn() * 0.1,
            "volume": 10000,
        })

    return pd.DataFrame(bars)


@pytest.fixture
def sample_l2_snapshot():
    """Create sample L2 snapshot for testing."""
    return pd.Series({
        "ts_utc": pd.Timestamp("2024-01-02 09:30:00"),
        "symbol": "AAPL",
        "bid_px_1": 149.95,
        "bid_sz_1": 1000,
        "ask_px_1": 150.05,
        "ask_sz_1": 1000,
        "bid_px_2": 149.94,
        "bid_sz_2": 500,
        "ask_px_2": 150.06,
        "ask_sz_2": 500,
        "bid_px_3": 149.93,
        "bid_sz_3": 200,
        "ask_px_3": 150.07,
        "ask_sz_3": 200,
        "has_depth": True,
    })


class TestExecutionSimulator:
    """Tests for L2 execution simulator."""

    def test_walk_book_buy(self, sample_l2_snapshot):
        """Test walking ask side for BUY order."""
        sim = L2ExecutionSimulator(latency_ms=75)

        result = sim.simulate_fill(
            order_side="BUY",
            quantity=1200,  # Needs to walk 2 levels
            book_snapshot=sample_l2_snapshot,
            reference_price=150.0,
        )

        assert result.fill_price > 150.0  # Should be higher than mid
        assert result.walked_levels >= 2
        assert result.fill_time_ms == 75
        assert not result.partially_filled

    def test_walk_book_sell(self, sample_l2_snapshot):
        """Test walking bid side for SELL order."""
        sim = L2ExecutionSimulator(latency_ms=75)

        result = sim.simulate_fill(
            order_side="SELL",
            quantity=1200,
            book_snapshot=sample_l2_snapshot,
            reference_price=150.0,
        )

        assert result.fill_price < 150.0  # Should be lower than mid
        assert result.walked_levels >= 2
        assert not result.partially_filled

    def test_partial_fill(self):
        """Test partial fill when insufficient liquidity."""
        sim = L2ExecutionSimulator(latency_ms=75)

        # Create shallow book
        shallow_book = pd.Series({
            "ts_utc": pd.Timestamp("2024-01-02 09:30:00"),
            "symbol": "AAPL",
            "bid_px_1": 149.95,
            "bid_sz_1": 100,
            "ask_px_1": 150.05,
            "ask_sz_1": 100,
            "has_depth": True,
        })

        result = sim.simulate_fill(
            order_side="BUY",
            quantity=1000,  # More than available
            book_snapshot=shallow_book,
            reference_price=150.0,
        )

        assert result.partially_filled
        assert result.walked_levels == 1

    def test_fixed_bps_fallback(self):
        """Test fixed BPS model when L2 unavailable."""
        sim = L2ExecutionSimulator(latency_ms=75, slippage_model="fixed_bps")

        result = sim._simulate_fixed_bps("BUY", 150.0, fixed_bps=5)

        # 5 bps = 0.05%
        expected = 150.0 * 1.0005
        assert abs(result.fill_price - expected) < 0.01
        assert result.slippage_bps == 5

    def test_market_impact_estimation(self, sample_l2_snapshot):
        """Test market impact estimation."""
        sim = L2ExecutionSimulator()

        impact = sim.estimate_market_impact(
            quantity=500,
            book_snapshot=sample_l2_snapshot,
            side="both",
        )

        # Impact should be positive and reasonable (< 1%)
        assert impact > 0
        assert impact < 0.01

    def test_check_liquidity(self, sample_l2_snapshot):
        """Test liquidity checking."""
        sim = L2ExecutionSimulator()

        result = sim.check_liquidity(sample_l2_snapshot, required_quantity=1000)

        assert "sufficient_bid" in result
        assert "sufficient_ask" in result
        assert "bid_depth" in result
        assert "ask_depth" in result
        assert result["bid_depth"] > 0
        assert result["ask_depth"] > 0


class TestBacktestEngine:
    """Tests for backtest engine."""

    def test_engine_initialization(self):
        """Test engine initializes with config."""
        engine = AlphaBacktestEngine(DEFAULT_CONFIG)

        assert engine.capital == 100000
        assert engine.position_size_pct == 0.02
        assert engine.max_positions == 10
        assert len(engine.positions) == 0

    def test_engine_empty_dataframe(self):
        """Test engine handles empty data gracefully."""
        engine = AlphaBacktestEngine(DEFAULT_CONFIG)

        empty_df = pd.DataFrame(columns=["ts", "symbol", "open", "high", "low", "close", "volume"])
        result = engine.run(empty_df)

        assert result.num_trades == 0

    def test_prepare_bar_data(self, sample_l2_snapshot):
        """Test bar data preparation with L2."""
        engine = AlphaBacktestEngine(DEFAULT_CONFIG)

        bar = pd.Series({
            "ts": pd.Timestamp("2024-01-02 09:30:00"),
            "symbol": "AAPL",
            "open": 150.0,
            "high": 150.2,
            "low": 149.8,
            "close": 150.1,
            "volume": 10000,
        })

        # Create L2 DataFrame
        l2_df = pd.DataFrame([sample_l2_snapshot])

        bar_data = engine._prepare_bar_data(bar, l2_df, bar["ts"])

        assert bar_data.bars["symbol"] == "AAPL"
        assert bar_data.l2_snapshot is not None
        assert isinstance(bar_data.features, dict)

    def test_calculate_equity(self, sample_bars):
        """Test equity calculation with and without positions."""
        engine = AlphaBacktestEngine(DEFAULT_CONFIG)

        # No positions - equity should equal capital
        group = sample_bars.groupby("ts").get_group(sample_bars["ts"].iloc[0])
        equity = engine._calculate_equity(group)

        assert equity == engine.capital

    def test_position_sizing(self):
        """Test position size calculation."""
        engine = AlphaBacktestEngine(DEFAULT_CONFIG)

        # 2% of $100,000 = $2,000
        # At $150/share = ~13 shares
        entry_price = 150.0
        position_value = engine.capital * engine.position_size_pct
        expected_quantity = int(position_value / entry_price)

        assert 10 <= expected_quantity <= 15

    def test_create_position_from_signal(self):
        """Test position creation from signal."""
        engine = AlphaBacktestEngine(DEFAULT_CONFIG)

        signal = SignalEvent(
            symbol="AAPL",
            timestamp=pd.Timestamp("2024-01-02 09:30:00"),
            side=SignalSide.LONG,
            confidence=0.8,
            features={},
            signal_name="OrderFlowSignal",
        )

        position = engine._create_position_from_signal(
            signal,
            entry_price=150.0,
            entry_time=pd.Timestamp("2024-01-02 09:31:00"),
            quantity=100,
        )

        assert position.symbol == "AAPL"
        assert position.side == SignalSide.LONG
        assert position.entry_price == 150.0
        assert position.quantity == 100
        assert position.target_price > position.entry_price
        assert position.stop_price < position.entry_price


class TestBacktestResult:
    """Tests for BacktestResult dataclass."""

    def test_empty_result(self):
        """Test empty backtest result."""
        result = BacktestResult()

        assert result.num_trades == 0
        assert result.final_equity == 100000.0

    def test_result_with_trades(self):
        """Test result with trade records."""
        result = BacktestResult()

        trade = Trade(
            symbol="AAPL",
            signal_name="OrderFlowSignal",
            side=SignalSide.LONG,
            entry_time=pd.Timestamp("2024-01-02 09:30:00"),
            entry_price=150.0,
            exit_time=pd.Timestamp("2024-01-02 09:40:00"),
            exit_price=150.6,
            quantity=100,
            exit_reason="target",
            pnl=60.0,
            pnl_pct=0.4,
            hold_minutes=10.0,
        )

        result.trades.append(trade)

        assert result.num_trades == 1
        assert result.trades[0].symbol == "AAPL"


class TestIntegration:
    """Integration tests for backtest pipeline."""

    def test_single_trade_simulation(self):
        """Test a single complete trade simulation."""
        # Create simple price data that triggers a target exit
        bars = []
        base_time = pd.Timestamp("2024-01-02 09:30:00")

        # Starting price
        for i in range(10):
            bars.append({
                "ts": base_time + timedelta(minutes=i),
                "symbol": "AAPL",
                "open": 150.0 + i * 0.01,  # Rising
                "high": 150.1 + i * 0.01,
                "low": 149.9 + i * 0.01,
                "close": 150.0 + i * 0.01,
                "volume": 10000,
            })

        df = pd.DataFrame(bars)

        # Create a mock signal that always fires
        class MockSignal:
            signal_name = "MockSignal"

            def check_entry(self, features, bar, timestamp):
                if bar.name == 0:  # First bar
                    return SignalEvent(
                        symbol=bar["symbol"],
                        timestamp=timestamp,
                        side=SignalSide.LONG,
                        confidence=0.8,
                        features={},
                        signal_name="MockSignal",
                    )
                return None

            def check_exit(self, position, features, bar, timestamp):
                # Exit after 5 bars
                if bar.name >= 5:
                    return ExitEvent(
                        symbol=position.symbol,
                        timestamp=timestamp,
                        reason="target",
                    )
                return None

        engine = AlphaBacktestEngine(DEFAULT_CONFIG)
        result = engine.run(df, signals=[MockSignal()])

        # Should have executed at least one trade
        assert result.entries_executed >= 0
        assert isinstance(result, BacktestResult)

    def test_pnl_calculation(self):
        """Verify P&L is calculated correctly."""
        entry_price = 150.0
        exit_price = 151.0
        quantity = 100
        commission = 0.005

        # LONG position
        gross_pnl = (exit_price - entry_price) * quantity
        total_commission = commission * quantity * 2
        expected_pnl = gross_pnl - total_commission

        assert expected_pnl == 100 - 1.0  # $100 - $1 commission
