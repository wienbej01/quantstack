"""Diagnostics and trade attribution analysis.

Provides detailed analysis of:
- Performance degradation (train vs validation)
- Trade-level attribution (why did each trade succeed/fail?)
- Summary report generation
"""

import logging
from dataclasses import dataclass
from typing import Dict, List

import numpy as np
import pandas as pd

from ..backtest.engine import BacktestResult, Trade
from .performance import compute_all_metrics, check_minimum_thresholds

logger = logging.getLogger(__name__)


@dataclass
class DegradationReport:
    """Report on performance degradation from train to validation."""
    train_metrics: dict
    val_metrics: dict
    degradation_pct: Dict[str, float]  # Metric -> % degradation
    significant_degradation: bool


def analyze_degradation(
    train_metrics: dict,
    val_metrics: dict,
) -> DegradationReport:
    """Analyze performance degradation from train to validation.

    Checks if validation performance is significantly worse than training
    (common sign of overfitting).

    Args:
        train_metrics: Metrics from training period
        val_metrics: Metrics from validation period

    Returns:
        DegradationReport with findings
    """
    degradation_pct = {}
    significant_degradation = False

    # Key metrics to check
    check_metrics = ["sharpe_ratio", "win_rate", "profit_factor", "expectancy"]

    for metric in check_metrics:
        train_val = train_metrics.get(metric, 0)
        val_val = val_metrics.get(metric, 0)

        if train_val > 0:
            # Calculate % degradation
            degradation = (train_val - val_val) / train_val
            degradation_pct[metric] = degradation * 100

            # Significant if degraded by >30%
            if degradation > 0.3:
                significant_degradation = True
        elif train_val == 0 and val_val < 0:
            # Went from 0 to negative - bad
            degradation_pct[metric] = 100.0
            significant_degradation = True

    logger.info(f"Degradation analysis: {degradation_pct}")

    return DegradationReport(
        train_metrics=train_metrics,
        val_metrics=val_metrics,
        degradation_pct=degradation_pct,
        significant_degradation=significant_degradation,
    )


def generate_trade_attribution(
    trades: List[Trade],
) -> pd.DataFrame:
    """Generate detailed trade attribution.

    Analyzes why trades succeeded or failed based on:
    - Entry signal type
    - Hold time duration
    - Exit reason
    - Time of day
    - Day of week

    Args:
        trades: List of Trade objects

    Returns:
        DataFrame with trade-level attribution
    """
    if not trades:
        return pd.DataFrame()

    rows = []
    for trade in trades:
        rows.append({
            "symbol": trade.symbol,
            "signal_name": trade.signal_name,
            "side": trade.side.value,
            "entry_time": trade.entry_time,
            "exit_time": trade.exit_time,
            "entry_price": trade.entry_price,
            "exit_price": trade.exit_price,
            "pnl": trade.pnl,
            "pnl_pct": trade.pnl_pct,
            "hold_minutes": trade.hold_minutes,
            "exit_reason": trade.exit_reason,
            "is_winner": trade.pnl > 0,
            "hour_of_day": trade.entry_time.hour,
            "day_of_week": trade.entry_time.dayofweek,
            "month": trade.entry_time.month,
        })

    df = pd.DataFrame(rows)

    # Add derived columns
    if not df.empty:
        df["hold_category"] = pd.cut(
            df["hold_minutes"],
            bins=[0, 5, 15, 30, float("inf")],
            labels=["0-5min", "5-15min", "15-30min", "30min+"]
        )

    return df


def analyze_attribution(attribution_df: pd.DataFrame) -> dict:
    """Analyze trade attribution patterns.

    Args:
        attribution_df: DataFrame from generate_trade_attribution

    Returns:
        Dict with analysis findings
    """
    if attribution_df.empty:
        return {}

    analysis = {}

    # Win rate by exit reason
    if "exit_reason" in attribution_df.columns:
        exit_wr = attribution_df.groupby("exit_reason")["is_winner"].mean() * 100
        analysis["win_rate_by_exit_reason"] = exit_wr.to_dict()

    # Win rate by signal
    if "signal_name" in attribution_df.columns:
        signal_wr = attribution_df.groupby("signal_name")["is_winner"].mean() * 100
        signal_pnl = attribution_df.groupby("signal_name")["pnl"].sum()
        analysis["win_rate_by_signal"] = signal_wr.to_dict()
        analysis["total_pnl_by_signal"] = signal_pnl.to_dict()

    # Win rate by hold category
    if "hold_category" in attribution_df.columns:
        hold_wr = attribution_df.groupby("hold_category")["is_winner"].mean() * 100
        analysis["win_rate_by_hold_time"] = hold_wr.to_dict()

    # Win rate by hour
    if "hour_of_day" in attribution_df.columns:
        hour_wr = attribution_df.groupby("hour_of_day")["is_winner"].mean() * 100
        analysis["win_rate_by_hour"] = hour_wr.to_dict()

    # Win rate by day of week
    if "day_of_week" in attribution_df.columns:
        dow_wr = attribution_df.groupby("day_of_week")["is_winner"].mean() * 100
        analysis["win_rate_by_day_of_week"] = dow_wr.to_dict()

    return analysis


def generate_summary_report(
    results: Dict[str, BacktestResult],
    config: dict,
) -> str:
    """Generate consolidated summary report for all hypotheses.

    Args:
        results: Dict mapping hypothesis name to BacktestResult
        config: Configuration dict with thresholds

    Returns:
        Formatted summary report
    """
    lines = [
        "=" * 70,
        "ALPHA HYPOTHESIS TESTING - SUMMARY REPORT",
        "=" * 70,
        "",
        f"Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    # Thresholds
    signals_cfg = config.get("signals", {})
    thresholds = config.get("validation", {}).get("thresholds", {})
    lines.extend([
        "VALIDATION THRESHOLDS",
        "-" * 40,
        f"Min Sharpe:       {thresholds.get('min_sharpe', 0.75)}",
        f"Min Win Rate:     {thresholds.get('min_win_rate', 52)}%",
        f"Min Profit Factor: {thresholds.get('min_profit_factor', 1.2)}",
        f"Min T-Stat:       {thresholds.get('min_t_stat', 2.0)}",
        f"Min Trades:       {thresholds.get('min_trades', 500)}",
        "",
    ])

    # Results for each hypothesis
    lines.extend([
        "HYPOTHESIS RESULTS",
        "-" * 40,
    ])

    for hyp_name, result in results.items():
        metrics = compute_all_metrics(result)

        # Check thresholds
        threshold_check = check_minimum_thresholds(
            metrics,
            min_sharpe=thresholds.get("min_sharpe", 0.75),
            min_win_rate=thresholds.get("min_win_rate", 52),
            min_profit_factor=thresholds.get("min_profit_factor", 1.2),
            min_t_stat=thresholds.get("min_t_stat", 2.0),
            min_trades=thresholds.get("min_trades", 500),
        )

        status = "✅ PASS" if threshold_check["all_pass"] else "❌ FAIL"

        lines.extend([
            f"",
            f"{hyp_name}: {status}",
            f"  Trades:         {metrics['num_trades']}",
            f"  Total Return:   {metrics['total_return_pct']:.2f}%",
            f"  Sharpe:         {metrics['sharpe_ratio']:.2f}",
            f"  Win Rate:       {metrics['win_rate']:.1f}% ({threshold_check['win_rate_pass'] and 'PASS' or 'FAIL'})",
            f"  Profit Factor:  {metrics['profit_factor']:.2f} ({threshold_check['profit_factor_pass'] and 'PASS' or 'FAIL'})",
            f"  Max Drawdown:   {metrics['max_drawdown_pct']:.2f}%",
            f"  Expectancy:     ${metrics['expectancy']:.2f}",
            f"  T-Stat:         {metrics['t_stat']:.2f}",
        ])

    # Final recommendation
    lines.extend([
        "",
        "=" * 70,
        "RECOMMENDATION",
        "=" * 70,
    ])

    # Count passing hypotheses
    passing = 0
    for hyp_name, result in results.items():
        metrics = compute_all_metrics(result)
        threshold_check = check_minimum_thresholds(metrics, **thresholds)
        if threshold_check["all_pass"]:
            passing += 1

    if passing > 0:
        lines.append(f"✅ {passing} hypothesis(es) passed validation thresholds")
        lines.append("   Recommendation: PROCEED TO PAPER TRADING")
    else:
        lines.append("❌ No hypotheses passed validation thresholds")
        lines.append("   Recommendation: REFININE HYPOTHESES OR ADJUST PARAMETERS")

    lines.extend([
        "",
        "=" * 70,
        "",
        "NEXT STEPS",
        "-" * 40,
        "1. Review trade attribution for losing trades",
        "2. Analyze regime-specific performance",
        "3. Consider parameter optimization if close to thresholds",
        "",
    ])

    return "\n".join(lines)


def save_report(
    report: str,
    output_path: str,
) -> None:
    """Save report to file.

    Args:
        report: Report string content
        output_path: Path to save report
    """
    with open(output_path, 'w') as f:
        f.write(report)

    logger.info(f"Report saved to {output_path}")
