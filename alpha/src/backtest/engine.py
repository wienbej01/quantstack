"""Main backtest engine for Alpha hypothesis testing.

Orchestrates the backtesting loop:
1. Load data for symbols in universe
2. For each bar:
   - Compute features (L2, price, flow)
   - Check entry conditions (signals)
   - Execute entries at NEXT bar open with slippage
   - Check exit conditions for open positions
   - Execute exits at NEXT bar open

Temporal integrity is maintained:
- Signal evaluated at bar N close
- Trade executes at bar N+1 OPEN (next bar)
- Slippage applied to execution price
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..features.l2_features import AlphaL2Features
from ..features.price_features import compute_all_price_features
from ..features.flow_features import compute_all_flow_features
from ..signals.base import Position, Signal, SignalEvent, ExitEvent, SignalSide

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """A completed trade (entry + exit)."""
    symbol: str
    signal_name: str
    side: SignalSide
    entry_time: pd.Timestamp
    entry_price: float
    exit_time: pd.Timestamp
    exit_price: float
    quantity: int
    exit_reason: str
    pnl: float
    pnl_pct: float
    hold_minutes: float


@dataclass
class BacktestResult:
    """Results from a backtest run."""
    trades: List[Trade] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=pd.Series)
    signals_generated: int = 0
    entries_executed: int = 0
    exits_executed: int = 0
    start_date: str = ""
    end_date: str = ""
    symbols_tested: List[str] = field(default_factory=list)

    @property
    def num_trades(self) -> int:
        return len(self.trades)

    @property
    def final_equity(self) -> float:
        if len(self.equity_curve) > 0:
            return self.equity_curve.iloc[-1]
        return 100000.0  # Starting capital


@dataclass
class BarData:
    """Container for all data at a single timestamp."""
    bars: pd.Series  # Current OHLCV bar
    l2_snapshot: Optional[pd.Series] = None  # L2 snapshot if available
    features: Dict[str, Any] = field(default_factory=dict)  # Computed features


class AlphaBacktestEngine:
    """Main backtest engine for Alpha hypothesis testing.

    Processes bars sequentially, maintaining temporal integrity:
    - Signals evaluated at bar close
    - Trades executed at next bar open
    - Slippage applied to execution
    """

    def __init__(self, config: dict):
        """Initialize backtest engine.

        Args:
            config: Configuration dict with:
                - initial_capital: Starting capital (default: 100000)
                - commission_per_share: Commission per share (default: 0.005)
                - slippage_bps: Slippage in bps (default: 5 bps = 0.05%)
                - position_size_pct: Position size as % of capital (default: 0.02 = 2%)
                - max_positions: Max concurrent positions (default: 10)
        """
        self.config = config

        # Execution parameters
        risk_cfg = config.get("risk", {})
        exec_cfg = config.get("execution", {})

        self.initial_capital = config.get("initial_capital", 100000)
        self.commission_per_share = exec_cfg.get("commission_per_share", 0.005)
        self.slippage_bps = exec_cfg.get("slippage_bps", 5) / 10000  # Convert bps to decimal
        self.position_size_pct = risk_cfg.get("max_position_pct", 0.02)
        self.max_positions = risk_cfg.get("max_positions", 10)

        # State
        self.capital: float = self.initial_capital
        self.positions: Dict[str, Position] = {}  # symbol -> Position
        self.pending_entries: List[SignalEvent] = []  # Signals to execute at next bar
        self.pending_exits: List[ExitEvent] = []  # Exits to execute at next bar
        self.entries_executed: int = 0
        self.exits_executed: int = 0

        # Feature engineers
        self.l2_engineer = AlphaL2Features(config)
        self.price_features_computed = False

    def run(
        self,
        bars_df: pd.DataFrame,
        l2_df: Optional[pd.DataFrame] = None,
        signals: Optional[List[Signal]] = None,
    ) -> BacktestResult:
        """Run backtest on historical data.

        Args:
            bars_df: OHLCV data with columns: ts, symbol, open, high, low, close, volume
            l2_df: Optional L2 snapshots with columns: ts_utc, symbol, bid_px_N, ask_sz_N, etc.
            signals: List of Signal instances to test

        Returns:
            BacktestResult with trades and equity curve
        """
        # Reset state for fresh run
        self.capital = self.initial_capital
        self.positions = {}
        self.pending_entries = []
        self.pending_exits = []
        self.entries_executed = 0
        self.exits_executed = 0

        result = BacktestResult()

        if bars_df.empty:
            logger.warning("Empty bars DataFrame")
            return result

        # Set date range
        result.start_date = bars_df["ts"].min().strftime("%Y-%m-%d")
        result.end_date = bars_df["ts"].max().strftime("%Y-%m-%d")
        result.symbols_tested = bars_df["symbol"].unique().tolist()

        # Sort by timestamp
        bars_df = bars_df.sort_values("ts").reset_index(drop=True)

        # Group by symbol for processing
        symbols = bars_df["symbol"].unique()
        logger.info(f"Running backtest for {len(symbols)} symbols from {result.start_date} to {result.end_date}")

        # Process bars by timestamp (maintain temporal integrity)
        current_ts_idx = 0

        # Track equity curve
        equity_values = [self.initial_capital]
        equity_timestamps = [bars_df["ts"].iloc[0]]

        # Group bars by timestamp
        bars_by_ts = bars_df.groupby("ts")

        for ts, group in bars_by_ts:
            # Process pending entries (execute at this bar's OPEN)
            self._execute_pending_entries(group)

            # Process pending exits (execute at this bar's OPEN)
            self._execute_pending_exits(group, result)

            # Check signals and generate new entries
            for _, bar in group.iterrows():
                bar_data = self._prepare_bar_data(bar, l2_df, ts)
                self._process_bar(bar_data, signals, result)

            # Update equity
            current_equity = self._calculate_equity(group)
            equity_values.append(current_equity)
            equity_timestamps.append(ts)

            current_ts_idx += 1
            if current_ts_idx % 1000 == 0:
                logger.debug(f"Processed {current_ts_idx} timestamps")

        # Close any remaining positions at last price
        self._close_remaining_positions(bars_df, result)

        # Build equity curve
        result.equity_curve = pd.Series(equity_values, index=equity_timestamps)

        logger.info(
            f"Backtest complete: {result.num_trades} trades, "
            f"final equity: ${result.final_equity:,.2f}"
        )

        return result

    def _prepare_bar_data(
        self,
        bar: pd.Series,
        l2_df: Optional[pd.DataFrame],
        ts: pd.Timestamp,
    ) -> BarData:
        """Prepare BarData with features for current bar."""
        bar_data = BarData(bars=bar)

        # Find L2 snapshot for this symbol and timestamp
        # Match within 1 minute window since bar ts is in ET and L2 ts_utc is in UTC
        if l2_df is not None and not l2_df.empty:
            # Convert bar timestamp to UTC for comparison
            ts_utc = ts.tz_localize('America/New_York').tz_convert('UTC') if ts.tz is None else ts.tz_convert('UTC')
            
            symbol_l2 = l2_df[
                (l2_df["symbol"] == bar["symbol"]) &
                (l2_df["ts_utc"] >= ts_utc - pd.Timedelta(seconds=30)) &
                (l2_df["ts_utc"] <= ts_utc + pd.Timedelta(seconds=30))
            ]

            if not symbol_l2.empty:
                # Use closest snapshot
                symbol_l2['time_diff'] = abs((symbol_l2['ts_utc'] - ts_utc).dt.total_seconds())
                closest_idx = symbol_l2['time_diff'].idxmin()
                bar_data.l2_snapshot = symbol_l2.loc[closest_idx]
                print(f"DEBUG: Loaded L2 snapshot for {bar['symbol']} @ {ts}, {len(symbol_l2)} snapshots in window")
            else:
                print(f"DEBUG: No L2 snapshot for {bar['symbol']} @ {ts} (ts_utc={ts_utc})")
        else:
            print(f"DEBUG: L2 data is None or empty")

        # Compute L2 features if snapshot available
        if bar_data.l2_snapshot is not None:
            l2_features = self.l2_engineer.compute_all_features(bar_data.l2_snapshot)
            bar_data.features.update(l2_features)
            print(f"DEBUG: L2 features computed - spread={l2_features.get('spread'):.4f}, book_imb={l2_features.get('book_imbalance_5'):.3f}")
        else:
            # Provide fallback values when L2 data unavailable
            # These neutral values won't trigger signals but won't crash either
            bar_data.features.update({
                "book_imbalance_5": 0.0,
                "book_imbalance_10": 0.0,
                "depth_ratio_5": 1.0,
                "depth_ratio_10": 1.0,
                "spread": bar["high"] - bar["low"],  # Approximate spread
                "bid_slope": 0.0,
                "ask_slope": 0.0,
                "has_large_bid": False,
                "has_large_ask": False,
                "large_bid_size": 0,
                "large_ask_size": 0,
                "bid_drop_pct": 0.0,
                "ask_drop_pct": 0.0,
                "trade_imbalance_5": 0.0,
                "rvol": 1.0,
            })

        # Compute price-based features (always available)
        # These require historical bars, so we'll use simple approximations
        # In production, these should be computed from rolling windows
        if "ret_1m" in bar.index:
            # Use existing return if available
            bar_data.features["ret_5"] = bar.get("ret_1m", 0) * 5  # Rough approximation

        return bar_data

    def _process_bar(
        self,
        bar_data: BarData,
        signals: Optional[List[Signal]],
        result: BacktestResult,
    ) -> None:
        """Process a single bar: check entries/exits."""
        bar = bar_data.bars

        # Check entries for symbols we don't already have positions in
        if signals and bar["symbol"] not in self.positions:
            for signal in signals:
                signal_event = signal.check_entry(
                    bar_data.features,
                    bar,
                    bar["ts"],
                )

                if signal_event:
                    print(f"DEBUG: SIGNAL GENERATED! {signal_event.signal_name} {signal_event.side} for {bar['symbol']} @ {bar['ts']}")
                    result.signals_generated += 1
                    self.pending_entries.append(signal_event)
                    logger.debug(
                        f"Signal generated: {signal_event.signal_name} "
                        f"{signal_event.side.value} {bar['symbol']} at {bar['ts']}"
                    )
                    break  # Only take first signal

        # Check exits for positions we have
        if bar["symbol"] in self.positions:
            position = self.positions[bar["symbol"]]

            for signal in signals:
                if signal.signal_name == position.signal_name:
                    exit_event = signal.check_exit(
                        position,
                        bar_data.features,
                        bar,
                        bar["ts"],
                    )

                    if exit_event:
                        self.pending_exits.append(exit_event)
                        logger.debug(
                            f"Exit signal: {exit_event.reason} "
                            f"{bar['symbol']} at {bar['ts']}"
                        )
                        break

    def _execute_pending_entries(self, bars_group: pd.DataFrame) -> None:
        """Execute pending entries at this bar's OPEN.

        Critical for temporal integrity:
        - Signal was generated at previous bar close
        - Entry executes at THIS bar's OPEN
        - Apply slippage to open price
        """
        if not self.pending_entries:
            return

        entries_to_execute = self.pending_entries.copy()
        self.pending_entries.clear()

        for signal in entries_to_execute:
            # Find bar for this symbol
            symbol_bar = bars_group[bars_group["symbol"] == signal.symbol]

            if symbol_bar.empty:
                continue

            bar = symbol_bar.iloc[0]

            # Calculate position size
            entry_price = bar["open"] * (1 + self.slippage_bps if signal.side == SignalSide.LONG else 1 - self.slippage_bps)
            position_value = self.capital * self.position_size_pct
            quantity = int(position_value / entry_price)

            if quantity <= 0:
                continue

            # Create position
            position = self._create_position_from_signal(signal, entry_price, bar["ts"], quantity)

            # Check max positions
            if len(self.positions) >= self.max_positions:
                logger.debug(f"Max positions reached, skipping entry for {signal.symbol}")
                continue

            self.positions[signal.symbol] = position
            result = None  # Would need result reference
            self.entries_executed += 1

            logger.debug(
                f"Entry executed: {signal.side.value} {quantity} shares "
                f"{signal.symbol} @ ${entry_price:.2f}"
            )

    def _execute_pending_exits(self, bars_group: pd.DataFrame, result: 'BacktestResult') -> None:
        """Execute pending exits at this bar's OPEN."""
        if not self.pending_exits:
            return

        exits_to_execute = self.pending_exits.copy()
        self.pending_exits.clear()

        for exit_event in exits_to_execute:
            symbol = exit_event.symbol

            if symbol not in self.positions:
                continue

            position = self.positions[symbol]

            # Find bar for this symbol
            symbol_bar = bars_group[bars_group["symbol"] == symbol]

            if symbol_bar.empty:
                continue

            bar = symbol_bar.iloc[0]

            # Execute exit at open with slippage
            if position.side == SignalSide.LONG:
                exit_price = bar["open"] * (1 - self.slippage_bps)
            else:
                exit_price = bar["open"] * (1 + self.slippage_bps)

            # Calculate P&L
            if position.side == SignalSide.LONG:
                pnl = (exit_price - position.entry_price) * position.quantity
            else:
                pnl = (position.entry_price - exit_price) * position.quantity

            # Subtract commission
            commission = self.commission_per_share * position.quantity * 2  # Entry + exit
            pnl -= commission

            # Update capital
            self.capital += pnl

            # Create trade record
            hold_minutes = (bar["ts"] - position.entry_time).total_seconds() / 60
            pnl_pct = (pnl / (position.entry_price * position.quantity)) * 100

            trade = Trade(
                symbol=position.symbol,
                signal_name=position.signal_name,
                side=position.side,
                entry_time=position.entry_time,
                entry_price=position.entry_price,
                exit_time=bar["ts"],
                exit_price=exit_price,
                quantity=position.quantity,
                exit_reason=exit_event.reason,
                pnl=pnl,
                pnl_pct=pnl_pct,
                hold_minutes=hold_minutes,
            )

            del self.positions[symbol]
            self.exits_executed += 1

            logger.debug(
                f"Exit executed: {position.side.value} {symbol} @ ${exit_price:.2f}, "
                f"P&L: ${pnl:.2f} ({pnl_pct:.2f}%), reason: {exit_event.reason}"
            )

            # Store trade
            result.trades.append(trade)

    def _create_position_from_signal(
        self,
        signal: SignalEvent,
        entry_price: float,
        entry_time: pd.Timestamp,
        quantity: int,
    ) -> Position:
        """Create Position from SignalEvent.

        Would normally call signal.create_position(), but we need to
        integrate with the backtest result tracking.
        """
        # Get target/stop from signal's signal
        # For now, use defaults based on signal name
        if signal.signal_name == "OrderFlowSignal":
            target_pct = 0.004
            stop_pct = 0.0025
            time_limit = 10
        elif signal.signal_name == "WhaleDetectSignal":
            target_pct = 0.008
            stop_pct = 0.004
            time_limit = 30
        elif signal.signal_name == "LiquidityFadeSignal":
            target_pct = 0.003
            stop_pct = 0.003
            time_limit = 5
        else:
            target_pct = 0.005
            stop_pct = 0.003
            time_limit = 15

        if signal.side == SignalSide.LONG:
            target_price = entry_price * (1 + target_pct)
            stop_price = entry_price * (1 - stop_pct)
        else:
            target_price = entry_price * (1 - target_pct)
            stop_price = entry_price * (1 + stop_pct)

        return Position(
            symbol=signal.symbol,
            side=signal.side,
            entry_price=entry_price,
            entry_time=entry_time,
            quantity=quantity,
            target_price=target_price,
            stop_price=stop_price,
            time_limit_minutes=time_limit,
            signal_name=signal.signal_name,
        )

    def _calculate_equity(self, bars_group: pd.DataFrame) -> float:
        """Calculate current equity including open positions."""
        equity = self.capital

        # Add unrealized P&L from open positions
        for symbol, position in self.positions.items():
            symbol_bar = bars_group[bars_group["symbol"] == symbol]

            if not symbol_bar.empty:
                current_price = symbol_bar.iloc[0]["close"]

                if position.side == SignalSide.LONG:
                    unrealized = (current_price - position.entry_price) * position.quantity
                else:
                    unrealized = (position.entry_price - current_price) * position.quantity

                equity += unrealized

        return equity

    def _close_remaining_positions(
        self,
        bars_df: pd.DataFrame,
        result: BacktestResult,
    ) -> None:
        """Close any remaining positions at last known price."""
        if not self.positions:
            return

        last_ts = bars_df["ts"].max()

        for symbol, position in list(self.positions.items()):
            # Get last price for symbol
            symbol_bars = bars_df[bars_df["symbol"] == symbol]

            if symbol_bars.empty:
                continue

            last_price = symbol_bars.iloc[-1]["close"]

            # Calculate P&L
            if position.side == SignalSide.LONG:
                pnl = (last_price - position.entry_price) * position.quantity
            else:
                pnl = (position.entry_price - last_price) * position.quantity

            commission = self.commission_per_share * position.quantity * 2
            pnl -= commission

            self.capital += pnl

            hold_minutes = (last_ts - position.entry_time).total_seconds() / 60

            trade = Trade(
                symbol=position.symbol,
                signal_name=position.signal_name,
                side=position.side,
                entry_time=position.entry_time,
                entry_price=position.entry_price,
                exit_time=last_ts,
                exit_price=last_price,
                quantity=position.quantity,
                exit_reason="end_of_data",
                pnl=pnl,
                pnl_pct=(pnl / (position.entry_price * position.quantity)) * 100,
                hold_minutes=hold_minutes,
            )

            result.trades.append(trade)
            self.exits_executed += 1

            logger.debug(f"Closed position at end of data: {symbol}, P&L: ${pnl:.2f}")

        self.positions.clear()
