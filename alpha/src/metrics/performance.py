"""Performance metrics for backtesting results.

Computes key metrics for strategy evaluation:
- Sharpe ratio (risk-adjusted return)
- Expectancy (average $ per trade)
- Win rate
- Profit factor
- Max drawdown
- t-stat (statistical significance)
"""

import logging
from typing import List, Optional

import numpy as np
import pandas as pd

from ..backtest.engine import BacktestResult, Trade

logger = logging.getLogger(__name__)


def compute_sharpe(
    returns: pd.Series,
    annualize: bool = True,
    risk_free_rate: float = 0.02,
) -> float:
    """Compute Sharpe ratio.

    Sharpe = (mean_return - risk_free) / std_return

    Args:
        returns: Series of returns (decimal, e.g., 0.01 for 1%)
        annualize: Whether to annualize (multiply by sqrt(252))
        risk_free_rate: Annual risk-free rate (default 2%)

    Returns:
        Sharpe ratio, or 0.0 if insufficient data
    """
    if len(returns) < 2:
        return 0.0

    excess_returns = returns - risk_free_rate / 252  # Daily risk-free

    mean_excess = excess_returns.mean()
    std_excess = excess_returns.std()

    if std_excess == 0:
        return 0.0

    sharpe = mean_excess / std_excess

    if annualize:
        sharpe *= np.sqrt(252)

    return sharpe


def compute_expectancy(trades: List[Trade]) -> float:
    """Compute expectancy (expected value per trade).

    Expectancy = Sum(P&L) / Number of trades

    Args:
        trades: List of Trade objects

    Returns:
        Average P&L per trade in dollars
    """
    if not trades:
        return 0.0

    total_pnl = sum(t.pnl for t in trades)
    return total_pnl / len(trades)


def compute_win_rate(trades: List[Trade]) -> float:
    """Compute win rate.

    Args:
        trades: List of Trade objects

    Returns:
        Win rate as percentage (0-100)
    """
    if not trades:
        return 0.0

    winners = sum(1 for t in trades if t.pnl > 0)
    return (winners / len(trades)) * 100


def compute_profit_factor(trades: List[Trade]) -> float:
    """Compute profit factor.

    Profit Factor = Gross Profit / Gross Loss

    Args:
        trades: List of Trade objects

    Returns:
        Profit factor, or 0.0 if no losers
    """
    winning_trades = [t for t in trades if t.pnl > 0]
    losing_trades = [t for t in trades if t.pnl < 0]

    if not losing_trades:
        return float("inf") if winning_trades else 0.0

    gross_profit = sum(t.pnl for t in winning_trades)
    gross_loss = abs(sum(t.pnl for t in losing_trades))

    if gross_loss == 0:
        return float("inf")

    return gross_profit / gross_loss


def compute_max_drawdown(equity_curve: pd.Series) -> float:
    """Compute maximum drawdown from equity curve.

    Args:
        equity_curve: Series of equity values over time

    Returns:
        Maximum drawdown as positive number
    """
    if len(equity_curve) < 2:
        return 0.0

    # Calculate running maximum
    running_max = equity_curve.cummax()

    # Calculate drawdown at each point
    drawdown = (equity_curve - running_max) / running_max

    # Max drawdown (most negative)
    max_dd = drawdown.min()

    return abs(max_dd)


def compute_t_stat(trades: List[Trade]) -> float:
    """Compute t-statistic for trade returns.

    Tests whether mean return is significantly different from zero.

    Args:
        trades: List of Trade objects

    Returns:
        t-statistic value
    """
    if len(trades) < 2:
        return 0.0

    returns = np.array([t.pnl_pct for t in trades])

    if np.std(returns) == 0:
        return 0.0

    # t-stat = mean / (std / sqrt(n))
    t_stat = np.mean(returns) / (np.std(returns) / np.sqrt(len(returns)))

    return t_stat


def compute_all_metrics(
    result: BacktestResult,
    initial_capital: float = 100000,
) -> dict:
    """Compute all performance metrics for a backtest result.

    Args:
        result: BacktestResult with trades and equity curve
        initial_capital: Starting capital for return calculation

    Returns:
        Dict of all computed metrics
    """
    trades = result.trades

    # Basic stats
    num_trades = len(trades)
    total_pnl = sum(t.pnl for t in trades)
    final_equity = result.final_equity
    total_return = (final_equity - initial_capital) / initial_capital

    # Compute metrics
    sharpe = 0.0
    if len(result.equity_curve) > 1:
        # Calculate returns from equity curve
        equity_returns = result.equity_curve.pct_change().dropna()
        sharpe = compute_sharpe(equity_returns)

    expectancy = compute_expectancy(trades)
    win_rate = compute_win_rate(trades)
    profit_factor = compute_profit_factor(trades)
    max_drawdown = (
        compute_max_drawdown(result.equity_curve)
        if len(result.equity_curve) > 0
        else 0.0
    )
    t_stat = compute_t_stat(trades)

    # Additional stats
    winning_trades = [t for t in trades if t.pnl > 0]
    losing_trades = [t for t in trades if t.pnl < 0]

    avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0.0
    avg_loss = np.mean([t.pnl for t in losing_trades]) if losing_trades else 0.0

    avg_hold_minutes = np.mean([t.hold_minutes for t in trades]) if trades else 0.0

    # Best and worst trades
    best_trade = max(trades, key=lambda t: t.pnl) if trades else None
    worst_trade = min(trades, key=lambda t: t.pnl) if trades else None

    return {
        # Basic stats
        "num_trades": num_trades,
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "total_pnl": total_pnl,
        "total_return_pct": total_return * 100,
        # Performance metrics
        "sharpe_ratio": sharpe,
        "expectancy": expectancy,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_drawdown * 100,
        "t_stat": t_stat,
        # Trade statistics
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "avg_hold_minutes": avg_hold_minutes,
        # Best/worst
        "best_trade_pnl": best_trade.pnl if best_trade else 0.0,
        "worst_trade_pnl": worst_trade.pnl if worst_trade else 0.0,
    }


def format_metrics_report(metrics: dict) -> str:
    """Format metrics as a readable report.

    Args:
        metrics: Dict of computed metrics

    Returns:
        Formatted string report
    """
    lines = [
        "=" * 60,
        "BACKTEST PERFORMANCE REPORT",
        "=" * 60,
        "",
        "CAPITAL & RETURNS",
        "-" * 40,
        f"Initial Capital: ${metrics['initial_capital']:,.2f}",
        f"Final Equity:    ${metrics['final_equity']:,.2f}",
        f"Total P&L:      ${metrics['total_pnl']:,.2f}",
        f"Total Return:    {metrics['total_return_pct']:.2f}%",
        "",
        "PERFORMANCE METRICS",
        "-" * 40,
        f"Sharpe Ratio:    {metrics['sharpe_ratio']:.2f}",
        f"Expectancy:      ${metrics['expectancy']:,.2f} per trade",
        f"Win Rate:        {metrics['win_rate']:.1f}%",
        f"Profit Factor:   {metrics['profit_factor']:.2f}",
        f"Max Drawdown:    {metrics['max_drawdown_pct']:.2f}%",
        f"T-Statistic:     {metrics['t_stat']:.2f}",
        "",
        "TRADE STATISTICS",
        "-" * 40,
        f"Number of Trades: {metrics['num_trades']}",
        f"Average Win:      ${metrics['avg_win']:,.2f}",
        f"Average Loss:     ${metrics['avg_loss']:,.2f}",
        f"Avg Hold Time:    {metrics['avg_hold_minutes']:.1f} minutes",
        f"Best Trade:       ${metrics['best_trade_pnl']:,.2f}",
        f"Worst Trade:      ${metrics['worst_trade_pnl']:,.2f}",
        "",
        "=" * 60,
    ]

    return "\n".join(lines)


def check_minimum_thresholds(
    metrics: dict,
    min_sharpe: float = 0.75,
    min_win_rate: float = 52.0,
    min_profit_factor: float = 1.2,
    min_t_stat: float = 2.0,
    min_trades: int = 500,
) -> dict:
    """Check if metrics meet minimum thresholds.

    Args:
        metrics: Dict of computed metrics
        min_sharpe: Minimum Sharpe ratio
        min_win_rate: Minimum win rate %
        min_profit_factor: Minimum profit factor
        min_t_stat: Minimum t-statistic
        min_trades: Minimum number of trades

    Returns:
        Dict with pass/fail status for each threshold
    """
    return {
        "sharpe_pass": metrics["sharpe_ratio"] >= min_sharpe,
        "win_rate_pass": metrics["win_rate"] >= min_win_rate,
        "profit_factor_pass": metrics["profit_factor"] >= min_profit_factor,
        "t_stat_pass": metrics["t_stat"] >= min_t_stat,
        "min_trades_pass": metrics["num_trades"] >= min_trades,
        "all_pass": (
            metrics["sharpe_ratio"] >= min_sharpe
            and metrics["win_rate"] >= min_win_rate
            and metrics["profit_factor"] >= min_profit_factor
            and metrics["t_stat"] >= min_t_stat
            and metrics["num_trades"] >= min_trades
        ),
    }
