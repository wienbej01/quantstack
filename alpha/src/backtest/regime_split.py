"""Regime stratification for backtesting results.

Classifies market into 4 regimes based on SPY and VIX:
- bull_low_vol: SPY > SMA20, VIX < 20
- bull_high_vol: SPY > SMA20, VIX >= 20
- bear_low_vol: SPY < SMA20, VIX < 20
- bear_high_vol: SPY < SMA20, VIX >= 20

Strategy must work in at least 2 regimes to be considered robust.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..backtest.engine import BacktestResult

logger = logging.getLogger(__name__)


@dataclass
class RegimeClassification:
    """Classification for a specific date."""

    date: str
    regime: str  # bull_low_vol, bull_high_vol, bear_low_vol, bear_high_vol
    spy_close: float
    spy_sma20: float
    vix: Optional[float] = None


@dataclass
class RegimeStats:
    """Statistics for a single regime."""

    regime: str
    num_trades: int
    total_pnl: float
    win_rate: float
    sharpe: float
    profit_factor: float
    avg_trade_pnl: float
    max_drawdown: float


@dataclass
class RobustnessReport:
    """Report on regime robustness."""

    num_regimes_tested: int
    num_profitable_regimes: int
    min_required: int
    passes_threshold: bool
    regime_stats: Dict[str, RegimeStats]

    def __str__(self) -> str:
        return (
            f"Regime Robustness: {self.num_profitable_regimes}/{self.num_regimes_tested} "
            f"regimes profitable (min {self.min_required}) - "
            f"{'PASS' if self.passes_threshold else 'FAIL'}"
        )


class RegimeStratifier:
    """Classify and analyze performance by market regime.

    Uses SPY price and VIX to classify market conditions.
    Strategy should work across multiple regimes to be robust.
    """

    # Regime definitions
    REGIMES = ["bull_low_vol", "bull_high_vol", "bear_low_vol", "bear_high_vol"]

    def __init__(
        self,
        spy_sma_period: int = 20,
        vix_threshold: float = 20.0,
        min_regimes_profitable: int = 2,
    ):
        """Initialize regime stratifier.

        Args:
            spy_sma_period: Period for SPY SMA (default: 20)
            vix_threshold: VIX threshold for high/low vol (default: 20)
            min_regimes_profitable: Min regimes that must be profitable (default: 2)
        """
        self.spy_sma_period = spy_sma_period
        self.vix_threshold = vix_threshold
        self.min_regimes_profitable = min_regimes_profitable

        logger.info(
            f"RegimeStratifier initialized: "
            f"SMA{spy_sma_period}, VIX threshold={vix_threshold}, "
            f"min_profitable={min_regimes_profitable}"
        )

    def classify_regime(
        self,
        spy_close: float,
        spy_sma20: float,
        vix: Optional[float] = None,
    ) -> str:
        """Classify market regime for given conditions.

        Args:
            spy_close: Current SPY close price
            spy_sma20: SPY SMA20 value
            vix: VIX value (optional, if not available uses default)

        Returns:
            Regime string (one of REGIMES)
        """
        # Determine bull/bear
        is_bull = spy_close > spy_sma20

        # Determine vol level (use VIX if available, else assume low vol)
        if vix is not None:
            is_high_vol = vix >= self.vix_threshold
        else:
            is_high_vol = False  # Default to low vol if VIX unavailable

        # Classify
        if is_bull and not is_high_vol:
            return "bull_low_vol"
        elif is_bull and is_high_vol:
            return "bull_high_vol"
        elif not is_bull and not is_high_vol:
            return "bear_low_vol"
        else:
            return "bear_high_vol"

    def classify_regime_series(
        self,
        spy_data: pd.DataFrame,
    ) -> pd.Series:
        """Classify regime for each day in SPY data.

        Args:
            spy_data: DataFrame with ts, close columns (from SPY loader)

        Returns:
            Series with regime classification for each timestamp
        """
        # Ensure datetime
        if not pd.api.types.is_datetime64_any_dtype(spy_data["ts"]):
            spy_data = spy_data.copy()
            spy_data["ts"] = pd.to_datetime(spy_data["ts"])

        # Calculate SMA20
        spy_data = spy_data.sort_values("ts").reset_index(drop=True)
        spy_data["spy_sma20"] = (
            spy_data["close"].rolling(window=self.spy_sma_period).mean()
        )

        # Classify each row
        regimes = []
        for _, row in spy_data.iterrows():
            regime = self.classify_regime(
                spy_close=row["close"],
                spy_sma20=row["spy_sma20"],
                vix=row.get("vix"),  # VIX if available
            )
            regimes.append(regime)

        return pd.Series(regimes, index=spy_data["ts"])

    def split_by_regime(
        self,
        backtest_results: BacktestResult,
        spy_data: pd.DataFrame,
    ) -> Dict[str, BacktestResult]:
        """Split backtest results by market regime.

        Args:
            backtest_results: Full backtest results
            spy_data: SPY data for regime classification

        Returns:
            Dict mapping regime name to filtered BacktestResult
        """
        # Classify regimes for each day
        regime_series = self.classify_regime_series(spy_data)

        # Group trades by regime
        regime_results = {}

        for regime in self.REGIMES:
            # Find dates that match this regime
            regime_dates = regime_series[regime_series == regime].index

            if len(regime_dates) == 0:
                logger.warning(f"No data for regime: {regime}")
                continue

            # Filter trades to this regime
            regime_trades = []
            for trade in backtest_results.trades:
                if trade.exit_time in regime_dates:
                    regime_trades.append(trade)

            # Create BacktestResult for this regime
            if regime_trades:
                regime_results[regime] = BacktestResult(
                    trades=regime_trades,
                    equity_curve=pd.Series(),  # Would need to reconstruct
                    signals_generated=backtest_results.signals_generated,
                    entries_executed=backtest_results.entries_executed,
                    exits_executed=backtest_results.exits_executed,
                    start_date=regime_dates.min().strftime("%Y-%m-%d"),
                    end_date=regime_dates.max().strftime("%Y-%m-%d"),
                    symbols_tested=backtest_results.symbols_tested,
                )

        logger.info(f"Split results into {len(regime_results)} regimes")
        return regime_results

    def check_regime_robustness(
        self,
        regime_stats: Dict[str, RegimeStats],
    ) -> RobustnessReport:
        """Check if strategy works in enough regimes.

        Args:
            regime_stats: Dict of regime name to RegimeStats

        Returns:
            RobustnessReport with findings
        """
        num_regimes = len(regime_stats)
        num_profitable = sum(1 for s in regime_stats.values() if s.total_pnl > 0)
        passes = num_profitable >= self.min_regimes_profitable

        logger.info(
            f"Regime robustness: {num_profitable}/{num_regimes} profitable "
            f"(min {self.min_regimes_profitable}) - {'PASS' if passes else 'FAIL'}"
        )

        return RobustnessReport(
            num_regimes_tested=num_regimes,
            num_profitable_regimes=num_profitable,
            min_required=self.min_regimes_profitable,
            passes_threshold=passes,
            regime_stats=regime_stats,
        )

    def calculate_regime_stats(
        self,
        result: BacktestResult,
    ) -> RegimeStats:
        """Calculate performance statistics for a backtest result.

        Args:
            result: BacktestResult (could be full or regime-specific)

        Returns:
            RegimeStats with calculated metrics
        """
        trades = result.trades

        if not trades:
            return RegimeStats(
                regime="unknown",
                num_trades=0,
                total_pnl=0.0,
                win_rate=0.0,
                sharpe=0.0,
                profit_factor=0.0,
                avg_trade_pnl=0.0,
                max_drawdown=0.0,
            )

        # Basic stats
        num_trades = len(trades)
        total_pnl = sum(t.pnl for t in trades)
        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl < 0]

        win_rate = len(winning_trades) / num_trades if num_trades > 0 else 0.0

        # Average trade P&L
        avg_trade_pnl = total_pnl / num_trades if num_trades > 0 else 0.0

        # Profit factor
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

        # Calculate Sharpe (simplified - using trade returns)
        returns = [t.pnl_pct / 100 for t in trades]
        if len(returns) > 1 and np.std(returns) > 0:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)  # Annualized
        else:
            sharpe = 0.0

        # Calculate max drawdown (simplified - from equity curve)
        # Use trade P&L cumulative to approximate
        cumulative = np.cumsum([t.pnl for t in trades])
        if len(cumulative) > 0:
            running_max = np.maximum.accumulate(cumulative)
            drawdown = running_max - cumulative
            max_drawdown = np.max(drawdown)
        else:
            max_drawdown = 0.0

        return RegimeStats(
            regime="regime",
            num_trades=num_trades,
            total_pnl=total_pnl,
            win_rate=win_rate * 100,
            sharpe=sharpe,
            profit_factor=profit_factor,
            avg_trade_pnl=avg_trade_pnl,
            max_drawdown=max_drawdown,
        )

    def analyze_all_regimes(
        self,
        backtest_results: BacktestResult,
        spy_data: pd.DataFrame,
    ) -> RobustnessReport:
        """Analyze performance across all regimes.

        Args:
            backtest_results: Full backtest results
            spy_data: SPY data for regime classification

        Returns:
            RobustnessReport with full analysis
        """
        # Split by regime
        regime_results = self.split_by_regime(backtest_results, spy_data)

        # Calculate stats for each regime
        regime_stats = {}

        for regime, result in regime_results.items():
            stats = self.calculate_regime_stats(result)
            stats.regime = regime
            regime_stats[regime] = stats

            logger.info(
                f"{regime}: {stats.num_trades} trades, "
                f"P&L: ${stats.total_pnl:.2f}, "
                f"Win Rate: {stats.win_rate:.1f}%, "
                f"Sharpe: {stats.sharpe:.2f}"
            )

        # Check robustness
        report = self.check_regime_robustness(regime_stats)

        return report
