"""Event-driven backtesting engine."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import pandas as pd

from .fill import DefaultFiller, Fill, Filler
from .order import Order, OrderFactory, OrderStatus
from .portfolio import Portfolio, Position


@dataclass
class BacktestConfig:
    """Configuration for backtesting engine."""

    # Initial conditions
    initial_cash: float = 1_000_000.0
    start_date: str | None = None
    end_date: str | None = None

    # Simulation parameters
    benchmark: str = "SPY"
    risk_free_rate: float = 0.02  # 2% annual risk-free rate

    # Order execution
    filler: Filler | None = None

    # Data requirements
    required_columns: list[str] = field(
        default_factory=lambda: [
            "ts",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]
    )

    # Progress tracking
    show_progress: bool = True
    progress_callback: Callable[[int, int], None] | None = None

    def __post_init__(self) -> None:
        """Initialize default values."""
        if self.filler is None:
            self.filler = DefaultFiller()


@dataclass
class BacktestResult:
    """Results from backtesting run."""

    # Portfolio evolution
    equity_curve: pd.DataFrame = field(default_factory=pd.DataFrame)
    positions_history: list[dict[str, Any]] = field(default_factory=list)
    trades_history: list[dict[str, Any]] = field(default_factory=list)
    orders_history: list[dict[str, Any]] = field(default_factory=list)

    # Performance metrics
    total_return: float = 0.0
    annualized_return: float = 0.0
    volatility: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0

    # Trading statistics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_trade_pnl: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0

    # Execution statistics
    total_commissions: float = 0.0
    total_slippage: float = 0.0
    fill_rate: float = 0.0

    # Metadata
    start_date: str | None = None
    end_date: str | None = None
    benchmark: str = "SPY"
    strategy_name: str = "Unknown"

    def calculate_performance_metrics(self) -> None:
        """Calculate performance metrics from equity curve."""
        if self.equity_curve.empty:
            return

        equity_series = self.equity_curve["total_equity"]
        returns = equity_series.pct_change().dropna()

        # Basic return metrics
        self.total_return = (equity_series.iloc[-1] / equity_series.iloc[0]) - 1

        # Annualized metrics (assuming daily data)
        trading_days = len(equity_series)
        years = trading_days / 252.0
        if years > 0:
            self.annualized_return = (
                equity_series.iloc[-1] / equity_series.iloc[0]
            ) ** (1 / years) - 1

        # Risk metrics
        self.volatility = returns.std() * (252**0.5)  # Annualized volatility

        if self.volatility > 0:
            excess_return = self.annualized_return - 0.02  # Assuming 2% risk-free rate
            self.sharpe_ratio = excess_return / self.volatility

        # Drawdown metrics
        cumulative_returns = equity_series / equity_series.iloc[0]
        rolling_max = cumulative_returns.expanding().max()
        drawdown = (cumulative_returns - rolling_max) / rolling_max
        self.max_drawdown = drawdown.min()

        # Drawdown duration
        drawdown_duration = 0
        max_duration = 0
        for dd in drawdown:
            if dd < 0:
                drawdown_duration += 1
                max_duration = max(max_duration, drawdown_duration)
            else:
                drawdown_duration = 0
        self.max_drawdown_duration = max_duration

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "performance": {
                "total_return": self.total_return,
                "annualized_return": self.annualized_return,
                "volatility": self.volatility,
                "sharpe_ratio": self.sharpe_ratio,
                "max_drawdown": self.max_drawdown,
                "max_drawdown_duration": self.max_drawdown_duration,
                "win_rate": self.win_rate,
                "profit_factor": self.profit_factor,
            },
            "trading": {
                "total_trades": self.total_trades,
                "winning_trades": self.winning_trades,
                "losing_trades": self.losing_trades,
                "avg_trade_pnl": self.avg_trade_pnl,
                "avg_win": self.avg_win,
                "avg_loss": self.avg_loss,
                "largest_win": self.largest_win,
                "largest_loss": self.largest_loss,
            },
            "execution": {
                "total_commissions": self.total_commissions,
                "total_slippage": self.total_slippage,
                "fill_rate": self.fill_rate,
            },
            "metadata": {
                "start_date": self.start_date,
                "end_date": self.end_date,
                "benchmark": self.benchmark,
                "strategy_name": self.strategy_name,
                "equity_curve_length": len(self.equity_curve),
            },
        }


class BacktestEngine:
    """Event-driven backtesting engine."""

    def __init__(self, config: BacktestConfig):
        """Initialize backtesting engine.

        Args:
            config: Backtest configuration
        """
        self.config = config
        self.portfolio = Portfolio(cash=config.initial_cash)
        self.order_factory = OrderFactory()
        self.filler = config.filler

        # Event tracking
        self.current_time = None
        self.current_bar = None
        self.pending_orders: list[Order] = []

        # Results tracking
        self.equity_curve: list[dict[str, Any]] = []
        self.positions_history: list[dict[str, Any]] = []
        self.trades_history: list[dict[str, Any]] = []

        # Daily universe tracking
        self._daily_universes: dict[date, set[str]] = {}
        self._current_universe: set[str] = set()
        self._last_processed_date: date | None = None

    def run(self, data: pd.DataFrame, strategy_func: Any) -> BacktestResult:
        """Run backtest on historical data.

        Args:
            data: Historical OHLCV data
            strategy_func: Strategy function that takes engine and bar data

        Returns:
            BacktestResult with performance metrics
        """
        # Validate data
        self._validate_data(data)

        # Process data bar by bar
        total_bars = len(data.groupby("ts"))

        for processed_bars, (timestamp, group) in enumerate(
            data.groupby("ts"), start=1
        ):
            self.current_time = timestamp

            # Update portfolio market values
            market_data = dict(zip(group["symbol"], group["close"], strict=False))
            self.portfolio.update_market_values(market_data)

            # Process each symbol's bar
            for _, bar in group.iterrows():
                self.current_bar = bar.to_dict()
                strategy_func(self, bar.to_dict())

            # Process pending orders
            self._process_pending_orders(group)

            # Record portfolio state
            self._record_portfolio_state()

            # Progress callback
            if self.config.progress_callback:
                self.config.progress_callback(processed_bars, total_bars)

        # Generate results
        return self._generate_results()

    def _validate_data(self, data: pd.DataFrame) -> None:
        """Validate input data."""
        if data.empty:
            raise ValueError("Input data is empty")

        missing_cols = [
            col for col in self.config.required_columns if col not in data.columns
        ]
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}")

        # Check data is sorted by timestamp
        if not data["ts"].is_monotonic_increasing:
            raise ValueError("Data must be sorted by timestamp")

    def _process_pending_orders(self, bars: pd.DataFrame) -> None:
        """Process pending orders against current bars."""
        orders_to_remove = []

        for order in self.pending_orders:
            symbol_bars = bars[bars["symbol"] == order.symbol]
            if not symbol_bars.empty:
                bar_data = symbol_bars.iloc[0].to_dict()
                self._process_order(order, bar_data)

                if not order.is_active:
                    orders_to_remove.append(order)

        # Remove filled/cancelled orders
        for order in orders_to_remove:
            if order in self.pending_orders:
                self.pending_orders.remove(order)

    def _process_order(self, order: Order, bar_data: dict[str, Any]) -> None:
        """Process an order against bar data."""
        if not order.is_active:
            return

        # Simulate fills
        fills = self.filler.simulate_fill(order, bar_data, self.current_time)

        # Apply fills
        for fill in fills:
            self._apply_fill(fill, order)

        # Update order status
        if order.is_fully_filled:
            order.status = OrderStatus.FILLED
            self.portfolio.add_filled_order(order)
        elif fills and order.status == OrderStatus.PENDING:
            order.status = OrderStatus.SUBMITTED

    def _apply_fill(self, fill: Fill, order: Order) -> None:
        """Apply a fill to order and portfolio."""
        # Update order
        order.add_fill(fill.quantity, fill.price, fill.timestamp)

        # Update portfolio
        self.portfolio.apply_fill(fill)

        # Record trade
        trade_info = {
            "timestamp": fill.timestamp,
            "symbol": fill.symbol,
            "side": fill.side.value,
            "quantity": fill.quantity,
            "price": fill.price,
            "commission": fill.commission,
            "total_cost": fill.total_cost,
            "order_id": order.order_id,
        }
        self.trades_history.append(trade_info)

    def _record_portfolio_state(self) -> None:
        """Record current portfolio state."""
        state = {
            "timestamp": self.current_time,
            "cash": self.portfolio.cash,
            "total_market_value": self.portfolio.total_market_value,
            "total_equity": self.portfolio.total_equity,
            "total_unrealized_pnl": self.portfolio.total_unrealized_pnl,
            "total_realized_pnl": self.portfolio.total_realized_pnl,
            "total_pnl": self.portfolio.total_pnl,
            "position_count": len(self.portfolio.positions),
            "pending_order_count": len(self.pending_orders),
        }

        # Add position details
        for symbol, position in self.portfolio.positions.items():
            state[f"position_{symbol}_quantity"] = position.quantity
            state[f"position_{symbol}_market_value"] = position.market_value
            state[f"position_{symbol}_pnl"] = position.get_total_pnl()

        self.equity_curve.append(state)

    def submit_order(self, order: Order) -> None:
        """Submit an order to the engine."""
        if order.status != OrderStatus.PENDING:
            raise ValueError(f"Cannot submit order in status {order.status}")

        self.pending_orders.append(order)
        self.portfolio.add_order(order)

    def cancel_order(self, order: Order) -> None:
        """Cancel an order."""
        if order in self.pending_orders:
            order.cancel()
            self.pending_orders.remove(order)

    def get_pending_orders(self, symbol: str | None = None) -> list[Order]:
        """Get pending orders, optionally filtered by symbol."""
        if symbol is None:
            return self.pending_orders.copy()
        return [order for order in self.pending_orders if order.symbol == symbol]

    def get_position(self, symbol: str) -> Position | None:
        """Get current position for symbol."""
        return (
            self.portfolio.get_position(symbol)
            if symbol in self.portfolio.positions
            else None
        )

    def _get_daily_universe_updates(self, bars: list[dict]) -> dict[date, set[str]]:
        """Extract trading days and prepare for daily universe updates."""
        trading_days = set()
        for bar in bars:
            bar_date = datetime.fromtimestamp(bar["ts"]).date()
            trading_days.add(bar_date)

        # For days we haven't processed yet, we'll need to compute universes
        new_days = trading_days - set(self._daily_universes.keys())
        universe_updates: dict[date, set[str]] = {}

        for day in sorted(new_days):
            universe_updates[day] = set()  # Will be populated by SIP selector

        return universe_updates

    def _update_daily_universe(self, trading_date: date, universe: set[str]) -> None:
        """Update the current universe for a trading day."""
        self._daily_universes[trading_date] = universe
        if trading_date == self._last_processed_date:
            self._current_universe = universe

    def _check_universe_update_needed(self, bar: dict) -> bool:
        """Check if we need to update universe for this bar's date."""
        bar_date = datetime.fromtimestamp(bar["ts"]).date()
        return bar_date != self._last_processed_date

    def _generate_results(self) -> BacktestResult:
        """Generate backtest results."""
        result = BacktestResult()

        # Convert equity curve to DataFrame
        if self.equity_curve:
            result.equity_curve = pd.DataFrame(self.equity_curve)
            result.equity_curve["datetime"] = pd.to_datetime(
                result.equity_curve["timestamp"]
            )

        # Copy histories
        result.positions_history = self.positions_history.copy()
        result.trades_history = self.trades_history.copy()
        result.orders_history = [
            order.to_dict() for order in self.portfolio.filled_orders
        ]

        # Copy portfolio statistics
        result.total_commissions = self.portfolio.total_commissions
        result.total_slippage = self.portfolio.total_slippage
        result.max_drawdown = self.portfolio.max_drawdown

        # Calculate trading statistics
        self._calculate_trading_stats(result)

        # Calculate performance metrics
        result.calculate_performance_metrics()

        # Set metadata
        if self.equity_curve:
            result.start_date = pd.to_datetime(
                self.equity_curve[0]["timestamp"]
            ).strftime("%Y-%m-%d")
            result.end_date = pd.to_datetime(
                self.equity_curve[-1]["timestamp"]
            ).strftime("%Y-%m-%d")

        result.benchmark = self.config.benchmark

        # Calculate fill rate
        total_orders = len(self.portfolio.filled_orders) + len(
            self.portfolio.pending_orders
        )
        if total_orders > 0:
            result.fill_rate = len(self.portfolio.filled_orders) / total_orders

        return result

    def _calculate_trading_stats(self, result: BacktestResult) -> None:
        """Calculate trading statistics."""
        if not result.trades_history:
            return

        # Group trades by round-trip (entry + exit)
        trades_by_symbol: dict[str, list[dict[str, Any]]] = {}
        for trade in result.trades_history:
            symbol = trade["symbol"]
            if symbol not in trades_by_symbol:
                trades_by_symbol[symbol] = []
            trades_by_symbol[symbol].append(trade)

        # Calculate round-trip P&L
        round_trip_pnls = []
        for _symbol, symbol_trades in trades_by_symbol.items():
            position = 0
            total_cost = 0.0

            for trade in symbol_trades:
                if trade["side"] == "BUY":
                    position += trade["quantity"]
                    total_cost += trade["total_cost"]
                elif position > 0:
                    # Closing long position
                    sell_quantity = min(trade["quantity"], position)
                    sell_proceeds = -trade["total_cost"]  # Negative because it's a cost
                    avg_cost_basis = (total_cost / position) * sell_quantity
                    pnl = sell_proceeds - avg_cost_basis

                    round_trip_pnls.append(pnl)

                    position -= sell_quantity
                    total_cost -= avg_cost_basis

        # Calculate statistics
        if round_trip_pnls:
            result.total_trades = len(round_trip_pnls)
            result.winning_trades = sum(1 for pnl in round_trip_pnls if pnl > 0)
            result.losing_trades = sum(1 for pnl in round_trip_pnls if pnl < 0)

            if result.total_trades > 0:
                result.win_rate = result.winning_trades / result.total_trades
                result.avg_trade_pnl = sum(round_trip_pnls) / result.total_trades

            winning_pnls = [pnl for pnl in round_trip_pnls if pnl > 0]
            losing_pnls = [pnl for pnl in round_trip_pnls if pnl < 0]

            if winning_pnls:
                result.avg_win = sum(winning_pnls) / len(winning_pnls)
                result.largest_win = max(winning_pnls)

            if losing_pnls:
                result.avg_loss = sum(losing_pnls) / len(losing_pnls)
                result.largest_loss = min(losing_pnls)

            # Profit factor
            total_wins = sum(winning_pnls)
            total_losses = abs(sum(losing_pnls))
            if total_losses > 0:
                result.profit_factor = total_wins / total_losses


# Legacy function for backward compatibility
def run_backtest(
    df: pd.DataFrame, orders_df: pd.DataFrame, signals_df: pd.DataFrame, params: dict
) -> dict:
    """Run backtest simulation (legacy function).

    Args:
        df: DataFrame with bars and features
        orders_df: DataFrame with orders (entries with sizing)
        signals_df: DataFrame with signals (for exits)
        params: Backtest params

    Returns:
        Dict with artifacts
    """
    # This is a simplified version for backward compatibility
    # In practice, use the new BacktestEngine class

    initial_equity = params.get("initial_equity", 100000.0)

    # Create backtest config
    config = BacktestConfig(initial_cash=initial_equity)

    # Create engine
    engine = BacktestEngine(config)

    # Simple strategy function (placeholder)
    def simple_strategy(engine: Any, bar: Any) -> None:
        pass

    # Run backtest
    result = engine.run(df, simple_strategy)

    # Convert to legacy format
    return {
        "equity": result.equity_curve,
        "trades": pd.DataFrame(result.trades_history),
        "orders": pd.DataFrame(result.orders_history),
        "metrics": result.to_dict()["performance"],
    }


def calculate_fees(qty: int, px: float, bps: float, per_share: float) -> float:
    """Calculate trading fees."""
    return qty * (px * bps / 10000 + per_share)
