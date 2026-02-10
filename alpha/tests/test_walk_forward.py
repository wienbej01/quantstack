"""Tests for walk-forward validation and regime stratification.

Tests verify:
- Period generation is correct
- No look-ahead bias (validation uses only past data)
- Consistency checks work correctly
- Regime classification matches SPY/VIX logic
"""

import numpy as np
import pandas as pd
import pytest
from datetime import datetime, timedelta

from src.backtest.walk_forward import (
    WalkForwardValidator,
    Period,
    WalkForwardPeriod,
    ConsistencyReport,
)
from src.backtest.regime_split import (
    RegimeStratifier,
    RegimeClassification,
    RegimeStats,
    RobustnessReport,
)


class TestWalkForwardValidator:
    """Tests for walk-forward validation."""

    def test_period_generation(self):
        """Test correct train/val period splits."""
        validator = WalkForwardValidator(train_months=3, val_months=1)

        periods = validator.generate_periods("2024-01-01", "2024-06-30")

        # Should generate multiple periods
        assert len(periods) >= 2

        # Check first period
        p1 = periods[0]
        assert p1.train_period.period_type == "train"
        assert p1.val_period.period_type == "val"
        assert p1.period_index == 0

        # Check validation periods don't overlap (critical for no lookahead)
        for i in range(len(periods) - 1):
            current_val_end = periods[i].val_period.end_date
            next_val_start = periods[i + 1].val_period.start_date
            assert current_val_end < next_val_start, "Validation periods should not overlap"

    def test_no_lookahead(self):
        """Validation uses only past data (no future peeking)."""
        validator = WalkForwardValidator(train_months=3, val_months=1)

        periods = validator.generate_periods("2024-01-01", "2024-06-30")

        # Each period's validation should be after its training
        for wf_period in periods:
            train_end = datetime.strptime(wf_period.train_period.end_date, "%Y-%m-%d")
            val_start = datetime.strptime(wf_period.val_period.start_date, "%Y-%m-%d")

            assert val_start > train_end, "Validation should start after training ends"

    def test_consistency_check(self):
        """Test consistency calculation correct."""
        validator = WalkForwardValidator(train_months=3, val_months=1, min_profitable_periods=0.7)

        # Create mock period results
        period_results = [
            {"period_index": 0, "is_profitable": True, "total_pnl": 1000},
            {"period_index": 1, "is_profitable": True, "total_pnl": 500},
            {"period_index": 2, "is_profitable": False, "total_pnl": -200},
            {"period_index": 3, "is_profitable": True, "total_pnl": 300},
        ]

        report = validator.check_consistency(period_results)

        assert report.total_periods == 4
        assert report.profitable_periods == 3
        assert report.consistency_pct == 75.0
        assert report.passes_threshold == True  # 75% >= 70%

    def test_consistency_fail(self):
        """Test consistency fails when below threshold."""
        validator = WalkForwardValidator(train_months=3, val_months=1, min_profitable_periods=0.7)

        period_results = [
            {"period_index": 0, "is_profitable": True, "total_pnl": 100},
            {"period_index": 1, "is_profitable": False, "total_pnl": -500},
            {"period_index": 2, "is_profitable": False, "total_pnl": -200},
            {"period_index": 3, "is_profitable": False, "total_pnl": -100},
        ]

        report = validator.check_consistency(period_results)

        assert report.total_periods == 4
        assert report.profitable_periods == 1
        assert report.consistency_pct == 25.0
        assert report.passes_threshold == False  # 25% < 70%

    def test_degradation_analysis(self):
        """Test degradation analysis detects performance drop."""
        validator = WalkForwardValidator()

        period_results = [
            {"period_index": 0, "is_profitable": True, "total_pnl": 1000},
            {"period_index": 1, "is_profitable": True, "total_pnl": 800},
            {"period_index": 2, "is_profitable": True, "total_pnl": 100},
            {"period_index": 3, "is_profitable": False, "total_pnl": -200},
            {"period_index": 4, "is_profitable": False, "total_pnl": -300},
        ]

        analysis = validator.analyze_degradation(period_results)

        assert "has_degradation" in analysis
        assert "pnl_degradation_pct" in analysis
        assert "first_half_avg_pnl" in analysis
        assert "second_half_avg_pnl" in analysis

        # Second half should be worse
        assert analysis["second_half_avg_pnl"] < analysis["first_half_avg_pnl"]

    def test_empty_period_results(self):
        """Test handles empty period results."""
        validator = WalkForwardValidator()

        report = validator.check_consistency([])

        assert report.total_periods == 0
        assert report.profitable_periods == 0
        assert report.passes_threshold == False

    def test_period_duration(self):
        """Test period duration calculation."""
        period = Period(
            start_date="2024-01-01",
            end_date="2024-01-31",
            period_type="train",
        )

        # January has 31 days
        assert period.duration_days == 31

    def test_generate_periods_short_range(self):
        """Test period generation with minimal data."""
        validator = WalkForwardValidator(train_months=1, val_months=1)

        # Only 2 months of data
        periods = validator.generate_periods("2024-01-01", "2024-02-29")

        # Should generate at least one period
        assert len(periods) >= 1


class TestRegimeStratifier:
    """Tests for regime stratification."""

    def test_regime_classification(self):
        """Test regimes classified correctly."""
        stratifier = RegimeStratifier()

        # Bull market, low vol
        regime1 = stratifier.classify_regime(
            spy_close=450,
            spy_sma20=440,
            vix=15,
        )
        assert regime1 == "bull_low_vol"

        # Bull market, high vol
        regime2 = stratifier.classify_regime(
            spy_close=450,
            spy_sma20=440,
            vix=25,
        )
        assert regime2 == "bull_high_vol"

        # Bear market, low vol
        regime3 = stratifier.classify_regime(
            spy_close=430,
            spy_sma20=440,
            vix=15,
        )
        assert regime3 == "bear_low_vol"

        # Bear market, high vol
        regime4 = stratifier.classify_regime(
            spy_close=430,
            spy_sma20=440,
            vix=25,
        )
        assert regime4 == "bear_high_vol"

    def test_regime_without_vix(self):
        """Test regime classification without VIX defaults to low vol."""
        stratifier = RegimeStratifier()

        # No VIX - should classify as low vol
        regime = stratifier.classify_regime(
            spy_close=450,
            spy_sma20=440,
            vix=None,
        )
        assert regime == "bull_low_vol"

    def test_regime_series_classification(self):
        """Test classify regime series for SPY data."""
        stratifier = RegimeStratifier()

        # Create simple SPY data (need more than SMA window)
        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        spy_data = pd.DataFrame({
            "ts": dates,
            "close": 440 + np.arange(50) * 0.5,  # Rising trend
        })

        regimes = stratifier.classify_regime_series(spy_data)

        assert len(regimes) == len(spy_data)
        # Most should be bull (rising price) - skip first 20 (SMA warmup period)
        bull_regimes = regimes[20:]  # After SMA warmup
        assert all(r in ["bull_low_vol", "bull_high_vol"] for r in bull_regimes)

    def test_robustness_check(self):
        """Test robustness calculation correct."""
        stratifier = RegimeStratifier(min_regimes_profitable=2)

        # Create mock regime stats
        regime_stats = {
            "bull_low_vol": RegimeStats(
                regime="bull_low_vol",
                num_trades=10,
                total_pnl=1000,
                win_rate=60.0,
                sharpe=1.5,
                profit_factor=1.5,
                avg_trade_pnl=100,
                max_drawdown=500,
            ),
            "bear_low_vol": RegimeStats(
                regime="bear_low_vol",
                num_trades=5,
                total_pnl=-200,
                win_rate=40.0,
                sharpe=-0.5,
                profit_factor=0.8,
                avg_trade_pnl=-40,
                max_drawdown=300,
            ),
            "bull_high_vol": RegimeStats(
                regime="bull_high_vol",
                num_trades=8,
                total_pnl=500,
                win_rate=55.0,
                sharpe=0.8,
                profit_factor=1.2,
                avg_trade_pnl=62.5,
                max_drawdown=200,
            ),
        }

        report = stratifier.check_regime_robustness(regime_stats)

        assert report.num_regimes_tested == 3
        assert report.num_profitable_regimes == 2  # bull_low_vol and bull_high_vol
        assert report.passes_threshold == True  # 2 >= 2

    def test_robustness_fail(self):
        """Test robustness fails with only 1 profitable regime."""
        stratifier = RegimeStratifier(min_regimes_profitable=2)

        regime_stats = {
            "bull_low_vol": RegimeStats(
                regime="bull_low_vol",
                num_trades=10,
                total_pnl=1000,
                win_rate=60.0,
                sharpe=1.5,
                profit_factor=1.5,
                avg_trade_pnl=100,
                max_drawdown=500,
            ),
            "bear_low_vol": RegimeStats(
                regime="bear_low_vol",
                num_trades=5,
                total_pnl=-500,
                win_rate=30.0,
                sharpe=-1.0,
                profit_factor=0.5,
                avg_trade_pnl=-100,
                max_drawdown=400,
            ),
            "bull_high_vol": RegimeStats(
                regime="bull_high_vol",
                num_trades=8,
                total_pnl=-300,
                win_rate=45.0,
                sharpe=-0.3,
                profit_factor=0.9,
                avg_trade_pnl=-37.5,
                max_drawdown=250,
            ),
        }

        report = stratifier.check_regime_robustness(regime_stats)

        assert report.num_profitable_regimes == 1
        assert report.passes_threshold == False  # 1 < 2

    def test_calculate_regime_stats_empty(self):
        """Test regime stats calculation with no trades."""
        stratifier = RegimeStratifier()

        from src.backtest.engine import BacktestResult
        empty_result = BacktestResult(trades=[])

        stats = stratifier.calculate_regime_stats(empty_result)

        assert stats.num_trades == 0
        assert stats.total_pnl == 0.0
        assert stats.win_rate == 0.0

    def test_calculate_regime_stats_with_trades(self):
        """Test regime stats calculation with trades."""
        stratifier = RegimeStratifier()

        from src.backtest.engine import BacktestResult, Trade
        from src.signals.base import SignalSide

        trades = [
            Trade(
                symbol="AAPL",
                signal_name="TestSignal",
                side=SignalSide.LONG,
                entry_time=pd.Timestamp("2024-01-02 09:30:00"),
                entry_price=150.0,
                exit_time=pd.Timestamp("2024-01-02 10:00:00"),
                exit_price=151.0,
                quantity=100,
                exit_reason="target",
                pnl=100 - 0.5,  # $100 - $0.50 commission
                pnl_pct=0.66,
                hold_minutes=30.0,
            ),
            Trade(
                symbol="AAPL",
                signal_name="TestSignal",
                side=SignalSide.LONG,
                entry_time=pd.Timestamp("2024-01-02 10:30:00"),
                entry_price=151.0,
                exit_time=pd.Timestamp("2024-01-02 11:00:00"),
                exit_price=150.0,
                quantity=100,
                exit_reason="stop",
                pnl=-100 - 0.5,
                pnl_pct=-0.66,
                hold_minutes=30.0,
            ),
        ]

        result = BacktestResult(trades=trades)
        stats = stratifier.calculate_regime_stats(result)

        assert stats.num_trades == 2
        assert stats.total_pnl == pytest.approx(-1.0)  # -$1 net
        assert stats.win_rate == 50.0
        assert stats.avg_trade_pnl == -0.5


class TestValidationIntegration:
    """Integration tests for validation framework."""

    def test_validation_framework_setup(self):
        """Test both validators initialize correctly."""
        wf_validator = WalkForwardValidator()
        regime_stratifier = RegimeStratifier()

        assert wf_validator.train_months == 3
        assert regime_stratifier.spy_sma_period == 20

    def test_all_four_regimes_defined(self):
        """Test all four regimes are defined."""
        assert set(RegimeStratifier.REGIMES) == {
            "bull_low_vol",
            "bull_high_vol",
            "bear_low_vol",
            "bear_high_vol",
        }
