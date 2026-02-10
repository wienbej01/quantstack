"""Performance metrics and diagnostics modules."""

from .performance import (
    compute_sharpe,
    compute_expectancy,
    compute_win_rate,
    compute_profit_factor,
    compute_max_drawdown,
    compute_t_stat,
    compute_all_metrics,
    format_metrics_report,
    check_minimum_thresholds,
)
from .diagnostics import (
    DegradationReport,
    analyze_degradation,
    generate_trade_attribution,
    analyze_attribution,
    generate_summary_report,
    save_report,
)

__all__ = [
    "compute_sharpe",
    "compute_expectancy",
    "compute_win_rate",
    "compute_profit_factor",
    "compute_max_drawdown",
    "compute_t_stat",
    "compute_all_metrics",
    "format_metrics_report",
    "check_minimum_thresholds",
    "DegradationReport",
    "analyze_degradation",
    "generate_trade_attribution",
    "analyze_attribution",
    "generate_summary_report",
    "save_report",
]
