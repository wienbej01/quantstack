"""Walk-forward validation for strategy testing.

Implements rolling walk-forward validation:
- Train for N months, validate for M months
- Roll forward and repeat
- Check consistency: must be profitable in >70% of validation periods

This prevents look-ahead bias and tests strategy robustness over time.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

import numpy as np
import pandas as pd

from ..backtest.engine import AlphaBacktestEngine, BacktestResult

logger = logging.getLogger(__name__)


@dataclass
class Period:
    """A time period for training or validation."""

    start_date: str  # YYYY-MM-DD
    end_date: str  # YYYY-MM-DD
    period_type: str  # "train" or "val"

    @property
    def duration_days(self) -> int:
        """Calculate duration in days."""
        start = datetime.strptime(self.start_date, "%Y-%m-%d")
        end = datetime.strptime(self.end_date, "%Y-%m-%d")
        return (end - start).days + 1


@dataclass
class WalkForwardPeriod:
    """A train/validation period pair."""

    train_period: Period
    val_period: Period
    period_index: int


@dataclass
class ConsistencyReport:
    """Report on strategy consistency across validation periods."""

    total_periods: int
    profitable_periods: int
    consistency_pct: float
    passes_threshold: bool
    period_results: List[dict] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"Consistency: {self.consistency_pct:.1f}% "
            f"({self.profitable_periods}/{self.total_periods} periods profitable) "
            f"- {'PASS' if self.passes_threshold else 'FAIL'}"
        )


class WalkForwardValidator:
    """Implement walk-forward validation for strategy testing.

    Prevents look-ahead bias by ensuring:
    - Validation data never seen during training
    - Periods are sequential in time
    - No peeking into future performance
    """

    def __init__(
        self,
        train_months: int = 3,
        val_months: int = 1,
        min_profitable_periods: float = 0.7,
    ):
        """Initialize walk-forward validator.

        Args:
            train_months: Training period length in months
            val_months: Validation period length in months
            min_profitable_periods: Min % of periods that must be profitable (0-1)
        """
        self.train_months = train_months
        self.val_months = val_months
        self.min_profitable_periods = min_profitable_periods

        logger.info(
            f"WalkForwardValidator initialized: "
            f"train={train_months}mo, val={val_months}mo, "
            f"min_profitable={min_profitable_periods*100}%"
        )

    def generate_periods(
        self,
        start_date: str,
        end_date: str,
    ) -> List[WalkForwardPeriod]:
        """Generate train/validation period pairs.

        Creates rolling periods:
        - Period 1: Train [start, start+3mo], Val [start+3mo+1day, start+4mo]
        - Period 2: Train [start+1mo, start+4mo], Val [start+4mo+1day, start+5mo]
        - And so on...

        Args:
            start_date: Overall start date (YYYY-MM-DD)
            end_date: Overall end date (YYYY-MM-DD)

        Returns:
            List of WalkForwardPeriod pairs
        """
        periods = []

        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        current_train_start = start_dt
        period_idx = 0

        while True:
            # Calculate train period
            train_start = current_train_start
            train_end = self._add_months(train_start, self.train_months) - timedelta(
                days=1
            )

            # Calculate validation period
            val_start = train_end + timedelta(days=1)
            val_end = self._add_months(val_start, self.val_months) - timedelta(days=1)

            # Check if we've exceeded the overall end date
            if val_end > end_dt:
                break

            # Create period pair
            train_period = Period(
                start_date=train_start.strftime("%Y-%m-%d"),
                end_date=train_end.strftime("%Y-%m-%d"),
                period_type="train",
            )

            val_period = Period(
                start_date=val_start.strftime("%Y-%m-%d"),
                end_date=val_end.strftime("%Y-%m-%d"),
                period_type="val",
            )

            periods.append(
                WalkForwardPeriod(
                    train_period=train_period,
                    val_period=val_period,
                    period_index=period_idx,
                )
            )

            # Roll forward by 1 month
            current_train_start = self._add_months(current_train_start, 1)
            period_idx += 1

        logger.info(f"Generated {len(periods)} walk-forward periods")
        return periods

    def _add_months(self, date: datetime, months: int) -> datetime:
        """Add months to a date, handling month-end correctly."""
        year = date.year + (date.month + months - 1) // 12
        month = (date.month + months - 1) % 12 + 1
        day = min(date.day, self._days_in_month(year, month))
        return datetime(year, month, day)

    @staticmethod
    def _days_in_month(year: int, month: int) -> int:
        """Get number of days in a month."""
        if month == 2:
            return (
                29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28
            )
        elif month in [4, 6, 9, 11]:
            return 30
        else:
            return 31

    def run_validation(
        self,
        engine: AlphaBacktestEngine,
        bars_df: pd.DataFrame,
        signals: list,
        start_date: str,
        end_date: str,
        l2_df: Optional[pd.DataFrame] = None,  # ADD THIS PARAMETER
    ) -> Tuple[List[BacktestResult], ConsistencyReport]:
        """Run walk-forward validation.

        Args:
            engine: Backtest engine instance
            bars_df: Full historical data
            signals: List of signals to test
            start_date: Overall start date
            end_date: Overall end date

        Returns:
            Tuple of (list of results per period, consistency report)
        """
        # Generate periods
        periods = self.generate_periods(start_date, end_date)

        if not periods:
            logger.warning("No periods generated - date range too short")
            return [], ConsistencyReport(
                total_periods=0,
                profitable_periods=0,
                consistency_pct=0.0,
                passes_threshold=False,
            )

        # Run backtest for each period
        results = []
        period_results = []

        for wf_period in periods:
            logger.info(
                f"Running Period {wf_period.period_index}: "
                f"Train {wf_period.train_period.start_date} to {wf_period.train_period.end_date}, "
                f"Val {wf_period.val_period.start_date} to {wf_period.val_period.end_date}"
            )

            # Filter data to validation period
            val_start = pd.Timestamp(wf_period.val_period.start_date)
            val_end = pd.Timestamp(wf_period.val_period.end_date)

            val_bars = bars_df[
                (bars_df["ts"] >= val_start) & (bars_df["ts"] <= val_end)
            ]

            if val_bars.empty:
                logger.warning(
                    f"No data for validation period {wf_period.period_index}"
                )
                continue

            # Run backtest on validation period
            # Filter L2 data to validation period if available
            val_l2 = None
            if l2_df is not None and not l2_df.empty:
                val_l2 = l2_df[
                    (l2_df["ts_utc"] >= val_start) & (l2_df["ts_utc"] <= val_end)
                ]
            period_result = engine.run(val_bars, l2_df=val_l2, signals=signals)
            results.append(period_result)

            # Record period stats
            period_pnl = sum(t.pnl for t in period_result.trades)
            is_profitable = period_pnl > 0

            period_results.append(
                {
                    "period_index": wf_period.period_index,
                    "val_start": wf_period.val_period.start_date,
                    "val_end": wf_period.val_period.end_date,
                    "num_trades": period_result.num_trades,
                    "total_pnl": period_pnl,
                    "is_profitable": is_profitable,
                    "final_equity": period_result.final_equity,
                }
            )

            logger.info(
                f"Period {wf_period.period_index}: "
                f"{period_result.num_trades} trades, P&L: ${period_pnl:.2f}, "
                f"{'PROFITABLE' if is_profitable else 'UNPROFITABLE'}"
            )

        # Generate consistency report
        report = self.check_consistency(period_results)

        return results, report

    def check_consistency(self, period_results: List[dict]) -> ConsistencyReport:
        """Check if strategy meets consistency threshold.

        Args:
            period_results: List of period results from run_validation

        Returns:
            ConsistencyReport with findings
        """
        if not period_results:
            return ConsistencyReport(
                total_periods=0,
                profitable_periods=0,
                consistency_pct=0.0,
                passes_threshold=False,
                period_results=[],
            )

        total = len(period_results)
        profitable = sum(1 for r in period_results if r["is_profitable"])
        consistency = profitable / total if total > 0 else 0.0

        passes = consistency >= self.min_profitable_periods

        logger.info(
            f"Consistency check: {consistency*100:.1f}% ({profitable}/{total}) - {'PASS' if passes else 'FAIL'}"
        )

        return ConsistencyReport(
            total_periods=total,
            profitable_periods=profitable,
            consistency_pct=consistency * 100,
            passes_threshold=passes,
            period_results=period_results,
        )

    def analyze_degradation(
        self,
        period_results: List[dict],
    ) -> dict:
        """Analyze performance degradation across periods.

        Checks if performance degrades over time (common sign of overfitting).

        Args:
            period_results: List of period results

        Returns:
            Dict with degradation metrics
        """
        if len(period_results) < 3:
            return {
                "has_degradation": False,
                "reason": "Insufficient periods for analysis",
            }

        # Split into first half and second half
        mid = len(period_results) // 2
        first_half = period_results[:mid]
        second_half = period_results[mid:]

        # Calculate average P&L for each half
        first_avg = np.mean([r["total_pnl"] for r in first_half])
        second_avg = np.mean([r["total_pnl"] for r in second_half])

        # Calculate win rate for each half
        first_wr = sum(1 for r in first_half if r["is_profitable"]) / len(first_half)
        second_wr = sum(1 for r in second_half if r["is_profitable"]) / len(second_half)

        # Check for significant degradation
        pnl_degradation = (
            (first_avg - second_avg) / abs(first_avg) if first_avg != 0 else 0
        )
        wr_degradation = first_wr - second_wr

        has_degradation = (
            pnl_degradation > 0.3  # P&L degraded by >30%
            or wr_degradation > 0.2  # Win rate degraded by >20%
        )

        return {
            "has_degradation": has_degradation,
            "first_half_avg_pnl": first_avg,
            "second_half_avg_pnl": second_avg,
            "pnl_degradation_pct": pnl_degradation * 100,
            "first_half_win_rate": first_wr * 100,
            "second_half_win_rate": second_wr * 100,
            "wr_degradation_pct": wr_degradation * 100,
        }
