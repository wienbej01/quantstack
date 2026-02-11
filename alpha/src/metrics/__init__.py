"""Performance metrics and diagnostics modules."""

from .diagnostics import (
    DegradationReport,
    analyze_attribution,
    analyze_degradation,
    generate_summary_report,
    generate_trade_attribution,
    save_report,
)
from .performance import (
    check_minimum_thresholds,
    compute_all_metrics,
    compute_expectancy,
    compute_max_drawdown,
    compute_profit_factor,
    compute_sharpe,
    compute_t_stat,
    compute_win_rate,
    format_metrics_report,
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
