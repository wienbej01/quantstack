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

from ..data.ml_compact_cache import compute_event_score
from ..data.ml_dataset import FEATURE_COLS, compute_features_from_raw
from ..features.flow_features import compute_all_flow_features
from ..features.l2_features import AlphaL2Features
from ..features.ml_features import compute_ml_features
from ..features.price_features import compute_all_price_features
from ..signals.base import ExitEvent, Position, Signal, SignalEvent, SignalSide

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
        self.slippage_bps = (
            exec_cfg.get("slippage_bps", 5) / 10000
        )  # Convert bps to decimal
        self.position_size_pct = risk_cfg.get("max_position_pct", 0.02)
        self.max_positions = risk_cfg.get("max_positions", 10)

        # State
        self.capital: float = self.initial_capital
        self.positions: Dict[str, Position] = {}  # symbol -> Position
        self.pending_entries: List[SignalEvent] = []  # Signals to execute at next bar
        self.pending_exits: List[ExitEvent] = []  # Exits to execute at next bar
        self.entries_executed: int = 0
        self.exits_executed: int = 0
        self._signals_by_name: Dict[str, Signal] = {}
        self._l2_by_symbol: Dict[str, pd.DataFrame] = {}
        self._l2_ts_by_symbol: Dict[str, np.ndarray] = {}
        ml_cfg = config.get("ml", {})
        self._ml_lookback_seconds = int(ml_cfg.get("backtest_lookback_seconds", 300))
        self._l2_staleness_seconds = int(
            ml_cfg.get("backtest_snapshot_staleness_seconds", 60)
        )
        self._bar_interval_seconds = int(
            ml_cfg.get("backtest_bar_interval_seconds", 60)
        )

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
        self._signals_by_name = {
            signal.signal_name: signal for signal in (signals or [])
        }
        self._build_l2_index(l2_df)

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
        bars_df["_symbol_bar_idx"] = bars_df.groupby("symbol").cumcount()
        bars_by_symbol = {
            str(symbol): group.reset_index(drop=True)
            for symbol, group in bars_df.groupby("symbol", sort=False)
        }

        # Group by symbol for processing
        symbols = bars_df["symbol"].unique()
        logger.info(
            f"Running backtest for {len(symbols)} symbols from {result.start_date} to {result.end_date}"
        )

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
                symbol_history = (
                    bars_by_symbol[str(bar["symbol"])]
                    .iloc[: int(bar["_symbol_bar_idx"]) + 1]
                    .copy()
                )
                bar_data = self._prepare_bar_data(
                    bar, l2_df, ts, bar_history=symbol_history
                )
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
        result.entries_executed = self.entries_executed
        result.exits_executed = self.exits_executed

        logger.info(
            f"Backtest complete: {result.num_trades} trades, "
            f"final equity: ${result.final_equity:,.2f}"
        )

        return result

    def _build_l2_index(self, l2_df: Optional[pd.DataFrame]) -> None:
        """Pre-index L2 snapshots by symbol for causal lookups."""
        self._l2_by_symbol = {}
        self._l2_ts_by_symbol = {}

        if l2_df is None or l2_df.empty:
            return

        indexed = l2_df.copy()
        indexed["ts_utc"] = pd.to_datetime(indexed["ts_utc"], utc=True)
        for symbol, group in indexed.groupby("symbol", sort=False):
            ordered = group.sort_values("ts_utc").reset_index(drop=True)
            self._l2_by_symbol[str(symbol)] = ordered
            self._l2_ts_by_symbol[str(symbol)] = (
                ordered["ts_utc"].astype("int64").to_numpy()
            )

    def _lookup_l2_context(
        self,
        symbol: str,
        ts_utc: pd.Timestamp,
    ) -> tuple[pd.DataFrame, Optional[pd.Series]]:
        """Return a causal lookback window and the latest non-stale snapshot."""
        symbol_key = str(symbol)
        if symbol_key not in self._l2_by_symbol:
            return pd.DataFrame(), None

        ts_ns = int(ts_utc.value)
        timestamps = self._l2_ts_by_symbol[symbol_key]
        end = int(np.searchsorted(timestamps, ts_ns, side="right"))
        if end <= 0:
            return pd.DataFrame(), None

        latest_ts_ns = int(timestamps[end - 1])
        if ts_ns - latest_ts_ns > self._l2_staleness_seconds * 1_000_000_000:
            return pd.DataFrame(), None

        start_ns = ts_ns - self._ml_lookback_seconds * 1_000_000_000
        start = int(np.searchsorted(timestamps, start_ns, side="left"))
        window = self._l2_by_symbol[symbol_key].iloc[start:end].copy()
        latest = window.iloc[-1].copy() if not window.empty else None
        return window, latest

    def _decision_cutoff_utc(
        self,
        ts: pd.Timestamp,
        bar_history: Optional[pd.DataFrame] = None,
    ) -> pd.Timestamp:
        """Return the latest timestamp that is causally available for the current bar decision.

        Minute bars in this repo are bucket-labelled by their start time, while signal generation
        happens after the bar is complete. We therefore allow L2 context up to the end of the
        current bar, but exclude the next bar's opening snapshot.
        """
        if ts.tz is None:
            ts_utc = ts.tz_localize("America/New_York").tz_convert("UTC")
        else:
            ts_utc = ts.tz_convert("UTC")

        interval_seconds = self._bar_interval_seconds
        if (
            bar_history is not None
            and not bar_history.empty
            and "ts" in bar_history.columns
        ):
            ordered = pd.to_datetime(bar_history["ts"]).sort_values().drop_duplicates()
            if len(ordered) >= 2:
                delta = ordered.iloc[-1] - ordered.iloc[-2]
                if delta > pd.Timedelta(0):
                    interval_seconds = max(int(delta.total_seconds()), 1)

        return (
            ts_utc
            + pd.Timedelta(seconds=interval_seconds)
            - pd.Timedelta(nanoseconds=1)
        )

    @staticmethod
    def _series_from_frame(
        frame: pd.DataFrame,
        column: str,
        default: float = 0.0,
    ) -> pd.Series:
        if column in frame.columns:
            return pd.to_numeric(frame[column], errors="coerce").fillna(default)
        return pd.Series(default, index=frame.index, dtype=np.float32)

    def _normalize_ml_window(
        self,
        window: pd.DataFrame,
        symbol: str,
        date: str,
    ) -> pd.DataFrame:
        """Normalize raw or pre-computed L2 rows into the training feature schema."""
        cols = set(window.columns)
        if any(col.startswith("bid_px_") for col in cols):
            normalized = compute_features_from_raw(window).copy()
            if "ts_epoch" not in normalized.columns:
                normalized["ts_epoch"] = (
                    pd.to_datetime(normalized["ts_utc"], utc=True).astype("int64") / 1e9
                )
        else:
            normalized = window.copy()
            normalized["ts_utc"] = pd.to_datetime(normalized["ts_utc"], utc=True)
            if "ts_epoch" not in normalized.columns:
                normalized["ts_epoch"] = normalized["ts_utc"].astype("int64") / 1e9
            normalized["mid"] = self._series_from_frame(normalized, "mid")
            normalized["spread"] = self._series_from_frame(normalized, "spread")

            depth_bid = self._series_from_frame(normalized, "depth_bid_k")
            if "depth_bid_k" not in normalized.columns:
                depth_bid = self._series_from_frame(normalized, "depth_bid")
            depth_ask = self._series_from_frame(normalized, "depth_ask_k")
            if "depth_ask_k" not in normalized.columns:
                depth_ask = self._series_from_frame(normalized, "depth_ask")

            normalized["depth_bid_k"] = depth_bid
            normalized["depth_ask_k"] = depth_ask
            total_depth = depth_bid + depth_ask
            normalized["depth_imb_k"] = np.where(
                total_depth > 0,
                (depth_bid - depth_ask) / total_depth,
                0.0,
            )
            normalized["pressure_k"] = self._series_from_frame(normalized, "pressure_k")
            if "pressure_k" not in normalized.columns:
                normalized["pressure_k"] = self._series_from_frame(
                    normalized, "pressure", 0.0
                )
                if "pressure" not in normalized.columns:
                    normalized["pressure_k"] = depth_bid - depth_ask

            normalized["obi_1"] = self._series_from_frame(normalized, "obi_1")
            normalized["obi_2"] = self._series_from_frame(normalized, "obi_2")
            if "obi_2" not in normalized.columns:
                normalized["obi_2"] = normalized["obi_1"]
            normalized["obi_3"] = self._series_from_frame(normalized, "obi_3")
            if "obi_3" not in normalized.columns:
                normalized["obi_3"] = normalized["obi_1"]
            normalized["obi_5"] = self._series_from_frame(normalized, "obi_5")
            normalized["obi_10"] = self._series_from_frame(normalized, "obi_10")
            if "obi_10" not in normalized.columns:
                normalized["obi_10"] = normalized["obi_5"]

            bid = self._series_from_frame(normalized, "bid")
            ask = self._series_from_frame(normalized, "ask")
            bid_size = self._series_from_frame(normalized, "bid_size")
            ask_size = self._series_from_frame(normalized, "ask_size")
            if {"l1_bid", "l1_ask"} <= cols:
                bid = self._series_from_frame(normalized, "l1_bid")
                ask = self._series_from_frame(normalized, "l1_ask")
                bid_size = self._series_from_frame(normalized, "l1_bid_size")
                ask_size = self._series_from_frame(normalized, "l1_ask_size")

            has_l1 = (bid > 0) & (ask > 0)
            inverted_l1 = has_l1 & (ask < bid)
            clean_bid = bid.where(~inverted_l1, ask)
            clean_ask = ask.where(~inverted_l1, bid)
            derived_mid = (clean_bid + clean_ask) / 2.0
            derived_spread = clean_ask - clean_bid
            absurd_l1 = has_l1 & (
                (derived_mid <= 0)
                | (derived_spread <= 0)
                | ((derived_spread / np.maximum(np.abs(derived_mid), 1e-6)) > 0.50)
            )
            sane_l1 = has_l1 & ~absurd_l1

            normalized["mid"] = normalized["mid"].where(~sane_l1, derived_mid)
            normalized["spread"] = normalized["spread"].where(~sane_l1, derived_spread)
            normalized["spread"] = normalized["spread"].where(
                normalized["spread"] >= 0, 0.0
            )

            total_l1 = bid_size + ask_size
            normalized["microprice"] = self._series_from_frame(normalized, "microprice")
            derived_microprice = np.where(
                total_l1 > 0,
                (clean_bid * ask_size + clean_ask * bid_size) / total_l1,
                normalized["mid"],
            )
            if "microprice" not in cols:
                normalized["microprice"] = derived_microprice
            else:
                out_of_book = sane_l1 & (
                    (normalized["microprice"] < clean_bid)
                    | (normalized["microprice"] > clean_ask)
                )
                normalized["microprice"] = normalized["microprice"].where(
                    ~(out_of_book | absurd_l1),
                    derived_microprice,
                )

            normalized["micro_off"] = normalized["microprice"] - normalized["mid"]

        normalized["symbol"] = symbol
        normalized["date"] = date
        if "source_type" not in normalized.columns:
            normalized["source_type"] = "backtest"
        for column in FEATURE_COLS:
            if column not in normalized.columns:
                normalized[column] = 0.0
        keep = ["ts_utc", "ts_epoch", "symbol", "date", "source_type", *FEATURE_COLS]
        normalized = normalized[keep].sort_values("ts_utc").reset_index(drop=True)
        return normalized

    def _compute_ml_feature_view(
        self,
        window: pd.DataFrame,
        symbol: str,
        date: str,
        bar_history: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """Compute the latest ML feature vector from a causal L2 lookback window."""
        normalized = self._normalize_ml_window(window, symbol=symbol, date=date)
        featured = compute_ml_features(normalized)
        featured["event_score"] = compute_event_score(featured)
        latest = featured.iloc[-1]
        numeric_cols = featured.select_dtypes(include=[np.number, bool]).columns
        features = {column: latest[column] for column in numeric_cols}
        if bar_history is not None and not bar_history.empty:
            features.update(self._compute_causal_bar_feature_view(bar_history))
        return features

    def _compute_causal_bar_feature_view(
        self, bar_history: pd.DataFrame
    ) -> Dict[str, Any]:
        """Compute OHLCV-derived features from completed bars only.

        This intentionally excludes the current decision bar so the causal price-feature
        branch remains safe even when bar timestamps are minute labels rather than explicit
        close timestamps.
        """
        required_cols = {"open", "high", "low", "close", "volume", "ts"}
        if not required_cols.issubset(bar_history.columns):
            return {}

        bars = bar_history.sort_values("ts").reset_index(drop=True).copy()
        completed = bars.iloc[:-1].copy()
        if completed.empty:
            return {}
        completed["ts_utc"] = pd.to_datetime(completed["ts"], utc=True)
        featured = compute_ml_features(completed)
        latest = featured.iloc[-1]
        numeric_cols = featured.select_dtypes(include=[np.number, bool]).columns
        return {
            column: latest[column]
            for column in numeric_cols
            if column not in {"ts_epoch"}
        }

    def _prepare_bar_data(
        self,
        bar: pd.Series,
        l2_df: Optional[pd.DataFrame],
        ts: pd.Timestamp,
        bar_history: Optional[pd.DataFrame] = None,
    ) -> BarData:
        """Prepare BarData with features for current bar."""
        bar_data = BarData(bars=bar)
        bar_data.features["_ml_features_ready"] = False

        if l2_df is not None and not self._l2_by_symbol:
            self._build_l2_index(l2_df)

        # Find the latest non-stale L2 context available by the end of the current bar.
        ts_utc = self._decision_cutoff_utc(ts, bar_history=bar_history)
        symbol_l2_window, latest_snapshot = self._lookup_l2_context(
            bar["symbol"], ts_utc
        )
        if latest_snapshot is not None:
            bar_data.l2_snapshot = latest_snapshot
            if bar_history is not None:
                feature_view = self._compute_ml_feature_view(
                    symbol_l2_window,
                    symbol=str(bar["symbol"]),
                    date=ts.strftime("%Y-%m-%d"),
                    bar_history=bar_history,
                )
            else:
                feature_view = self._compute_ml_feature_view(
                    symbol_l2_window,
                    symbol=str(bar["symbol"]),
                    date=ts.strftime("%Y-%m-%d"),
                )
            bar_data.features.update(feature_view)
            bar_data.features["_ml_features_ready"] = True
        elif bar_history is not None and not bar_history.empty:
            bar_data.features.update(self._compute_causal_bar_feature_view(bar_history))

        # Compute L2 features if snapshot available
        if bar_data.l2_snapshot is not None:
            l2_features = self.l2_engineer.compute_all_features(bar_data.l2_snapshot)
            # Preserve the causal ML feature view when it already populated a feature name.
            # Snapshot-level diagnostics are still added for non-overlapping keys.
            for key, value in l2_features.items():
                bar_data.features.setdefault(key, value)
        else:
            # Provide fallback values when L2 data unavailable
            # These neutral values won't trigger signals but won't crash either
            bar_data.features.update(
                {
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
                }
            )

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
            entry_price = bar["open"] * (
                1 + self.slippage_bps
                if signal.side == SignalSide.LONG
                else 1 - self.slippage_bps
            )
            position_value = self.capital * self.position_size_pct
            quantity = int(position_value / entry_price)

            if quantity <= 0:
                continue

            # Create position
            position = self._create_position_from_signal(
                signal, entry_price, bar["ts"], quantity
            )

            # Check max positions
            if len(self.positions) >= self.max_positions:
                logger.debug(
                    f"Max positions reached, skipping entry for {signal.symbol}"
                )
                continue

            self.positions[signal.symbol] = position
            result = None  # Would need result reference
            self.entries_executed += 1

            logger.debug(
                f"Entry executed: {signal.side.value} {quantity} shares "
                f"{signal.symbol} @ ${entry_price:.2f}"
            )

    def _execute_pending_exits(
        self, bars_group: pd.DataFrame, result: "BacktestResult"
    ) -> None:
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
            commission = (
                self.commission_per_share * position.quantity * 2
            )  # Entry + exit
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
        signal_impl = self._signals_by_name.get(signal.signal_name)
        if signal_impl is not None and hasattr(signal_impl, "create_position"):
            return signal_impl.create_position(
                signal, entry_price, entry_time, quantity
            )

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
                    unrealized = (
                        current_price - position.entry_price
                    ) * position.quantity
                else:
                    unrealized = (
                        position.entry_price - current_price
                    ) * position.quantity

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
