"""Daily Performance Reporter for L2 Scalping System

Generates daily performance reports and analytics.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PerformanceReporter:
    """Generates performance reports"""

    def __init__(self, reports_dir: str = "logs"):
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(exist_ok=True)

    def generate_daily_report(self, summary: dict, journal_file: Path) -> str:
        """Generate daily performance report"""

        report_lines = [
            "=" * 70,
            f"L2 SCALPING DAILY REPORT - {summary['date']}",
            "=" * 70,
            "",
            "TRADING ACTIVITY",
            "-" * 70,
            f"Total Signals:        {summary['total_signals']:>6}",
            f"Trades Executed:      {summary['total_trades']:>6}",
            f"Completed Trades:     {summary['completed_trades']:>6}",
            f"Open Positions:       {summary['open_positions']:>6}",
            "",
            "PERFORMANCE METRICS",
            "-" * 70,
            f"Gross P&L:           ${summary['gross_pnl']:>8.2f}",
            f"Commission:          ${summary['commission']:>8.2f}",
            f"Net P&L:             ${summary['net_pnl']:>8.2f}",
            "",
            f"Winning Trades:       {summary['winning_trades']:>6}",
            f"Losing Trades:        {summary['losing_trades']:>6}",
            f"Win Rate:             {summary['win_rate']:>5.1f}%",
            "",
            f"Average Win:         ${summary['avg_win']:>8.2f}",
            f"Average Loss:        ${summary['avg_loss']:>8.2f}",
            f"Profit Factor:        {summary['profit_factor']:>8.2f}",
            "",
            "EXECUTION METRICS",
            "-" * 70,
            f"Avg Hold Time:        {summary['avg_hold_time_seconds']:>6.0f}s",
            "",
            "DATA FILES",
            "-" * 70,
            f"Trade Journal:        {journal_file}",
            "=" * 70,
        ]

        report_text = "\n".join(report_lines)

        # Save report
        report_file = self.reports_dir / f"daily_report_{summary['date']}.txt"
        try:
            with open(report_file, "w") as f:
                f.write(report_text)
            logger.info(f"Daily report saved: {report_file}")
        except Exception as e:
            logger.error(f"Failed to save report: {e}")

        # Also save JSON version
        json_file = self.reports_dir / f"daily_summary_{summary['date']}.json"
        try:
            with open(json_file, "w") as f:
                json.dump(summary, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save JSON summary: {e}")

        return report_text

    def print_report(self, report_text: str) -> None:
        """Print report to console"""
        print("\n" + report_text + "\n")
