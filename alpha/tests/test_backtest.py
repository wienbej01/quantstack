"""Tests for backtest engine and execution simulation.

Tests verify:
- Engine processes bars correctly
- Execution simulation uses L2 data
- P&L calculations are accurate
- Target/stop/time limit exits work correctly
"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from src.backtest.engine import AlphaBacktestEngine, BacktestResult, BarData, Trade
from src.backtest.execution_sim import FillResult, L2ExecutionSimulator
from src.signals.base import ExitEvent, Position, SignalEvent, SignalSide
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
        bars.append(
            {
                "ts": ts,
                "symbol": "AAPL",
                "open": 150.0 + np.random.randn() * 0.1,
                "high": 150.2 + np.random.randn() * 0.1,
                "low": 149.8 + np.random.randn() * 0.1,
                "close": 150.0 + np.random.randn() * 0.1,
                "volume": 10000,
            }
        )

    return pd.DataFrame(bars)


@pytest.fixture
def sample_l2_snapshot():
    """Create sample L2 snapshot for testing."""
    return pd.Series(
        {
            "ts_utc": pd.Timestamp("2024-01-02 14:30:00+00:00"),
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
        }
    )


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
        shallow_book = pd.Series(
            {
                "ts_utc": pd.Timestamp("2024-01-02 09:30:00"),
                "symbol": "AAPL",
                "bid_px_1": 149.95,
                "bid_sz_1": 100,
                "ask_px_1": 150.05,
                "ask_sz_1": 100,
                "has_depth": True,
            }
        )

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

        empty_df = pd.DataFrame(
            columns=["ts", "symbol", "open", "high", "low", "close", "volume"]
        )
        result = engine.run(empty_df)

        assert result.num_trades == 0

    def test_prepare_bar_data(self, sample_l2_snapshot):
        """Test bar data preparation with L2."""
        engine = AlphaBacktestEngine(DEFAULT_CONFIG)

        bar = pd.Series(
            {
                "ts": pd.Timestamp("2024-01-02 09:30:00"),
                "symbol": "AAPL",
                "open": 150.0,
                "high": 150.2,
                "low": 149.8,
                "close": 150.1,
                "volume": 10000,
            }
        )

        # Create L2 DataFrame
        l2_df = pd.DataFrame([sample_l2_snapshot])

        bar_data = engine._prepare_bar_data(bar, l2_df, bar["ts"])

        assert bar_data.bars["symbol"] == "AAPL"
        assert bar_data.l2_snapshot is not None
        assert isinstance(bar_data.features, dict)

    def test_prepare_bar_data_adds_causal_bar_features_when_history_available(
        self, sample_l2_snapshot
    ):
        engine = AlphaBacktestEngine(DEFAULT_CONFIG)
        bars = pd.DataFrame(
            [
                {
                    "ts": pd.Timestamp("2024-01-02 09:30:00"),
                    "symbol": "AAPL",
                    "open": 150.0,
                    "high": 150.2,
                    "low": 149.8,
                    "close": 150.1,
                    "volume": 10000,
                },
                {
                    "ts": pd.Timestamp("2024-01-02 09:31:00"),
                    "symbol": "AAPL",
                    "open": 150.1,
                    "high": 150.4,
                    "low": 150.0,
                    "close": 150.3,
                    "volume": 12000,
                },
            ]
        )
        l2_df = pd.DataFrame([sample_l2_snapshot])

        bar_data = engine._prepare_bar_data(
            bars.iloc[-1],
            l2_df,
            bars.iloc[-1]["ts"],
            bar_history=bars,
        )

        assert "dist_vwap_bps" in bar_data.features
        assert "volume_rel_20" in bar_data.features

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

    def test_create_position_delegates_to_signal_impl(self):
        """Engine should honor signal-specific position construction when available."""
        engine = AlphaBacktestEngine(DEFAULT_CONFIG)

        class CustomSignal:
            signal_name = "CustomSignal"

            def create_position(self, signal, entry_price, entry_time, quantity):
                return Position(
                    symbol=signal.symbol,
                    side=signal.side,
                    entry_price=entry_price,
                    entry_time=entry_time,
                    quantity=quantity,
                    target_price=entry_price * 1.01,
                    stop_price=entry_price * 0.99,
                    time_limit_minutes=7,
                    signal_name=self.signal_name,
                )

        engine._signals_by_name = {"CustomSignal": CustomSignal()}
        signal = SignalEvent(
            symbol="AAPL",
            timestamp=pd.Timestamp("2024-01-02 09:30:00"),
            side=SignalSide.LONG,
            confidence=0.8,
            features={},
            signal_name="CustomSignal",
        )

        position = engine._create_position_from_signal(
            signal,
            entry_price=150.0,
            entry_time=pd.Timestamp("2024-01-02 09:31:00"),
            quantity=100,
        )

        assert position.time_limit_minutes == 7
        assert position.target_price == pytest.approx(151.5)

    def test_prepare_bar_data_uses_only_current_bar_l2_context(self):
        """L2 matching may use the completed current bar, but not the next bar."""
        engine = AlphaBacktestEngine(DEFAULT_CONFIG)
        engine._build_l2_index(
            pd.DataFrame(
                [
                    {
                        "ts_utc": pd.Timestamp("2024-01-02 14:29:45+00:00"),
                        "symbol": "AAPL",
                        "bid_px_1": 149.95,
                        "bid_sz_1": 1000,
                        "ask_px_1": 150.05,
                        "ask_sz_1": 1000,
                        "has_depth": True,
                    },
                    {
                        "ts_utc": pd.Timestamp("2024-01-02 14:30:15+00:00"),
                        "symbol": "AAPL",
                        "bid_px_1": 149.85,
                        "bid_sz_1": 900,
                        "ask_px_1": 149.95,
                        "ask_sz_1": 900,
                        "has_depth": True,
                    },
                    {
                        "ts_utc": pd.Timestamp("2024-01-02 14:31:00+00:00"),
                        "symbol": "AAPL",
                        "bid_px_1": 149.75,
                        "bid_sz_1": 800,
                        "ask_px_1": 149.85,
                        "ask_sz_1": 800,
                        "has_depth": True,
                    },
                ]
            )
        )
        bar = pd.Series(
            {
                "ts": pd.Timestamp("2024-01-02 09:30:00"),
                "symbol": "AAPL",
                "open": 150.0,
                "high": 150.2,
                "low": 149.8,
                "close": 150.1,
                "volume": 10000,
            }
        )

        bar_data = engine._prepare_bar_data(bar, None, bar["ts"])

        assert bar_data.l2_snapshot is not None
        assert bar_data.l2_snapshot["ts_utc"] == pd.Timestamp(
            "2024-01-02 14:30:15+00:00"
        )

    def test_normalize_ml_window_preserves_precomputed_micro_off(self):
        """Precomputed feature inputs should not have micro_off overwritten to zero."""
        engine = AlphaBacktestEngine(DEFAULT_CONFIG)
        window = pd.DataFrame(
            [
                {
                    "ts_utc": pd.Timestamp("2024-01-02 14:29:45+00:00"),
                    "symbol": "AAPL",
                    "mid": 150.0,
                    "spread": 0.10,
                    "depth_bid_k": 1500,
                    "depth_ask_k": 1400,
                    "depth_imb_k": 0.034483,
                    "pressure_k": 100.0,
                    "obi_1": 0.10,
                    "obi_2": 0.08,
                    "obi_3": 0.07,
                    "obi_5": 0.06,
                    "obi_10": 0.05,
                    "microprice": 150.03,
                    "micro_off": 0.03,
                }
            ]
        )

        normalized = engine._normalize_ml_window(
            window, symbol="AAPL", date="2024-01-02"
        )

        assert normalized["microprice"].iloc[0] == pytest.approx(150.03)
        assert normalized["micro_off"].iloc[0] == pytest.approx(0.03)

    def test_normalize_ml_window_sanitizes_inverted_precomputed_l1(self):
        """Precomputed feature inputs should not feed inverted or absurd L1 values downstream."""
        engine = AlphaBacktestEngine(DEFAULT_CONFIG)
        window = pd.DataFrame(
            [
                {
                    "ts_utc": pd.Timestamp("2024-01-02 14:29:45+00:00"),
                    "symbol": "AAPL",
                    "mid": 23.805,
                    "spread": -26.51,
                    "depth_bid": 514637.0,
                    "depth_ask": 134683.0,
                    "pressure": 0.5851,
                    "obi_1": 0.0,
                    "obi_2": 0.47,
                    "obi_3": 0.62,
                    "obi_5": 0.19,
                    "microprice": 23.805,
                    "micro_off": 0.0,
                    "bid": 37.06,
                    "ask": 10.55,
                    "bid_size": 400.0,
                    "ask_size": 400.0,
                }
            ]
        )

        normalized = engine._normalize_ml_window(
            window, symbol="AAPL", date="2024-01-02"
        )

        assert normalized["mid"].iloc[0] == pytest.approx(23.805)
        assert normalized["spread"].iloc[0] == pytest.approx(0.0)
        assert normalized["microprice"].iloc[0] == pytest.approx(23.805)
        assert normalized["micro_off"].iloc[0] == pytest.approx(0.0)

    def test_prepare_bar_data_preserves_ml_feature_view_over_l2_snapshot_keys(
        self, monkeypatch
    ):
        """Stateful snapshot diagnostics must not overwrite the ML feature vector."""
        engine = AlphaBacktestEngine(DEFAULT_CONFIG)
        bar = pd.Series(
            {
                "ts": pd.Timestamp("2024-01-02 09:30:00"),
                "symbol": "AAPL",
                "open": 150.0,
                "high": 150.2,
                "low": 149.8,
                "close": 150.1,
                "volume": 10000,
            }
        )
        l2_df = pd.DataFrame(
            [
                {
                    "ts_utc": pd.Timestamp("2024-01-02 14:30:15+00:00"),
                    "symbol": "AAPL",
                    "bid_px_1": 149.95,
                    "bid_sz_1": 1000,
                    "ask_px_1": 150.05,
                    "ask_sz_1": 1000,
                    "has_depth": True,
                }
            ]
        )

        monkeypatch.setattr(
            engine,
            "_compute_ml_feature_view",
            lambda window, symbol, date, bar_history=None: {
                "spread": 0.12,
                "mid": 150.0,
                "pressure_k": 25.0,
            },
        )
        monkeypatch.setattr(
            engine.l2_engineer,
            "compute_all_features",
            lambda snapshot: {
                "spread": 99.0,
                "mid": 99.0,
                "pressure_k": -99.0,
                "book_imbalance_5": 0.5,
            },
        )

        bar_data = engine._prepare_bar_data(
            bar, l2_df, bar["ts"], bar_history=pd.DataFrame([bar])
        )

        assert bar_data.features["spread"] == pytest.approx(0.12)
        assert bar_data.features["mid"] == pytest.approx(150.0)
        assert bar_data.features["pressure_k"] == pytest.approx(25.0)
        assert bar_data.features["book_imbalance_5"] == pytest.approx(0.5)

    def test_prepare_bar_data_marks_ml_not_ready_before_first_l2_snapshot(self):
        engine = AlphaBacktestEngine(DEFAULT_CONFIG)
        bar = pd.Series(
            {
                "ts": pd.Timestamp("2024-01-02 09:30:00"),
                "symbol": "AAPL",
                "open": 150.0,
                "high": 150.2,
                "low": 149.8,
                "close": 150.1,
                "volume": 10000,
            }
        )
        l2_df = pd.DataFrame(
            [
                {
                    "ts_utc": pd.Timestamp("2024-01-02 14:48:24+00:00"),
                    "symbol": "AAPL",
                    "bid_px_1": 149.95,
                    "bid_sz_1": 1000,
                    "ask_px_1": 150.05,
                    "ask_sz_1": 1000,
                    "has_depth": True,
                }
            ]
        )

        bar_data = engine._prepare_bar_data(bar, l2_df, bar["ts"])

        assert bar_data.l2_snapshot is None
        assert bar_data.features["_ml_features_ready"] is False


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
            bars.append(
                {
                    "ts": base_time + timedelta(minutes=i),
                    "symbol": "AAPL",
                    "open": 150.0 + i * 0.01,  # Rising
                    "high": 150.1 + i * 0.01,
                    "low": 149.9 + i * 0.01,
                    "close": 150.0 + i * 0.01,
                    "volume": 10000,
                }
            )

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

        # Result counters should mirror engine counters for observability.
        assert result.entries_executed == engine.entries_executed
        assert result.exits_executed == engine.exits_executed
        assert result.entries_executed > 0
        assert result.exits_executed > 0
        assert result.num_trades > 0
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
