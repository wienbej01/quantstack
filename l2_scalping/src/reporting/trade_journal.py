"""Trade Journal for L2 Scalping System

Records all trades, signals, and performance metrics.
Uses shared event store for consistency with intraday-paper system.
"""

import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

# Add intraday_stack to path for shared event store
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "intraday_stack" / "src"))

try:
    from journal.event_store import EventStore
    SHARED_EVENT_STORE = True
except ImportError:
    SHARED_EVENT_STORE = False
    logging.warning("Could not import shared event store, using local journal")

logger = logging.getLogger(__name__)


class TradeStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class TradeRecord:
    """Individual trade record"""

    timestamp: str
    symbol: str
    side: str  # BUY/SELL
    quantity: int
    entry_price: float
    exit_price: float | None = None
    signal_type: str = ""
    signal_strength: float = 0.0
    pnl: float = 0.0
    commission: float = 0.0
    status: str = TradeStatus.PENDING.value
    order_id: str | None = None
    fill_time: str | None = None
    hold_duration_seconds: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class TradeJournal:
    """Manages trade records and persistence"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

        # Use shared event store if available
        if SHARED_EVENT_STORE:
            self.event_store = EventStore("/home/jacobw/intraday_stack/data/journal/events.db")
            logger.info("Using shared event store for L2 scalping trades")
        else:
            self.event_store = None
            # Daily journal file fallback
            today = datetime.now().strftime("%Y%m%d")
            self.journal_file = self.data_dir / f"trades_{today}.jsonl"

        # In-memory storage
        self.trades: list[TradeRecord] = []
        if not SHARED_EVENT_STORE:
            self.load_today_trades()

        logger.info(f"L2 Trade journal initialized")

    def record_signal(
        self, symbol: str, signal_type: str, signal_strength: float
    ) -> str:
        """Record a trading signal (before execution)"""
        trade_id = f"{symbol}_{datetime.now().strftime('%H%M%S_%f')}"

        if SHARED_EVENT_STORE:
            # Log decision to shared event store
            self.event_store.log_decision(
                symbol=symbol,
                strategy="l2_scalping",
                direction="long" if signal_strength > 0 else "short",
                signal_strength=abs(signal_strength),
                net_edge_bps=signal_strength * 100,  # Convert to bps
                decision="TRADE",
                features={"signal_type": signal_type}
            )

        trade = TradeRecord(
            timestamp=datetime.now().isoformat(),
            symbol=symbol,
            side="",  # Will be filled on execution
            quantity=0,  # Will be filled on execution
            entry_price=0.0,  # Will be filled on execution
            signal_type=signal_type,
            signal_strength=signal_strength,
            status=TradeStatus.PENDING.value,
        )

        self.trades.append(trade)
        if not SHARED_EVENT_STORE:
            self._persist_trade(trade)

        logger.info(
            f"L2 Signal recorded: {symbol} {signal_type} strength={signal_strength:.3f}"
        )
        return trade_id

    def record_trade_entry(
        self, symbol: str, side: str, quantity: int, entry_price: float, order_id: str
    ) -> str:
        """Record trade entry"""
        if SHARED_EVENT_STORE:
            # Open trade in shared event store
            trade_id = self.event_store.open_trade(
                symbol=symbol,
                strategy="l2_scalping",
                direction="long" if side == "BUY" else "short",
                signal_id=f"l2_{symbol}_{datetime.now().strftime('%H%M%S')}",
                entry_order_id=int(order_id) if order_id.isdigit() else 0,
                entry_price=entry_price,
                entry_qty=quantity,
                signal_price=entry_price,
                system="l2-scalping"
            )
            logger.info(f"L2 Trade opened in shared store: {trade_id}")
            return trade_id

        # Fallback to local journal
        trade = self._find_pending_trade(symbol)
        if not trade:
            trade = TradeRecord(
                timestamp=datetime.now().isoformat(),
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=entry_price,
                order_id=order_id,
                status=TradeStatus.FILLED.value,
            )
            self.trades.append(trade)
        else:
            trade.side = side
            trade.quantity = quantity
            trade.entry_price = entry_price
            trade.order_id = order_id
            trade.fill_time = datetime.now().isoformat()
            trade.status = TradeStatus.FILLED.value

        self._persist_trade(trade)
        logger.info(f"L2 Trade entry: {symbol} {side} {quantity}@{entry_price:.4f}")
        return f"local_{symbol}_{datetime.now().strftime('%H%M%S')}"

    def record_trade_exit(
        self, trade_id: str, symbol: str, exit_price: float, pnl: float, commission: float = 0.0
    ) -> None:
        """Record trade exit"""
        if SHARED_EVENT_STORE and trade_id:
            # Close trade in shared event store
            self.event_store.close_trade(
                trade_id=trade_id,
                exit_order_id=0,  # L2 scalping uses market orders
                exit_price=exit_price,
                exit_qty=100,  # Standard L2 scalping size
                exit_reason="L2_SIGNAL",
                commission=commission,
                signal_price=exit_price
            )
            logger.info(f"L2 Trade closed in shared store: {trade_id}")
            return

        # Fallback to local journal
        trade = self._find_open_trade(symbol)
        if not trade:
            logger.warning(f"No open L2 trade found for exit: {symbol}")
            return

        entry_time = datetime.fromisoformat(trade.fill_time or trade.timestamp)
        exit_time = datetime.now()
        hold_duration = int((exit_time - entry_time).total_seconds())

        trade.exit_price = exit_price
        trade.pnl = pnl
        trade.commission = commission
        trade.hold_duration_seconds = hold_duration

        self._persist_trade(trade)
        logger.info(
            f"L2 Trade exit: {symbol} {exit_price:.4f} PnL=${pnl:.2f} hold={hold_duration}s"
        )

    def get_daily_summary(self) -> dict:
        """Get daily trading summary"""
        filled_trades = [t for t in self.trades if t.status == TradeStatus.FILLED.value]
        completed_trades = [t for t in filled_trades if t.exit_price is not None]

        total_pnl = sum(t.pnl for t in completed_trades)
        total_commission = sum(t.commission for t in completed_trades)
        net_pnl = total_pnl - total_commission

        winning_trades = [t for t in completed_trades if t.pnl > 0]
        losing_trades = [t for t in completed_trades if t.pnl < 0]

        avg_hold_time = 0
        if completed_trades:
            hold_times = [
                t.hold_duration_seconds
                for t in completed_trades
                if t.hold_duration_seconds
            ]
            avg_hold_time = sum(hold_times) / len(hold_times) if hold_times else 0

        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "total_signals": len(self.trades),
            "total_trades": len(filled_trades),
            "completed_trades": len(completed_trades),
            "open_positions": len(filled_trades) - len(completed_trades),
            "gross_pnl": total_pnl,
            "commission": total_commission,
            "net_pnl": net_pnl,
            "winning_trades": len(winning_trades),
            "losing_trades": len(losing_trades),
            "win_rate": len(winning_trades) / max(1, len(completed_trades)) * 100,
            "avg_win": sum(t.pnl for t in winning_trades) / max(1, len(winning_trades)),
            "avg_loss": sum(t.pnl for t in losing_trades) / max(1, len(losing_trades)),
            "avg_hold_time_seconds": avg_hold_time,
            "profit_factor": abs(
                sum(t.pnl for t in winning_trades)
                / max(1, abs(sum(t.pnl for t in losing_trades)))
            ),
        }

    def _find_pending_trade(self, symbol: str) -> TradeRecord | None:
        """Find pending trade for symbol"""
        for trade in reversed(self.trades):
            if trade.symbol == symbol and trade.status == TradeStatus.PENDING.value:
                return trade
        return None

    def _find_open_trade(self, symbol: str) -> TradeRecord | None:
        """Find open trade for symbol"""
        for trade in reversed(self.trades):
            if (
                trade.symbol == symbol
                and trade.status == TradeStatus.FILLED.value
                and trade.exit_price is None
            ):
                return trade
        return None

    def _persist_trade(self, trade: TradeRecord) -> None:
        """Persist trade to journal file"""
        try:
            with open(self.journal_file, "a") as f:
                f.write(json.dumps(trade.to_dict()) + "\n")
        except Exception as e:
            logger.error(f"Failed to persist trade: {e}")

    def load_today_trades(self) -> None:
        """Load today's trades from journal file"""
        if not self.journal_file.exists():
            return

        try:
            with open(self.journal_file) as f:
                for line in f:
                    if line.strip():
                        trade_data = json.loads(line.strip())
                        trade = TradeRecord(**trade_data)
                        self.trades.append(trade)

            logger.info(f"Loaded {len(self.trades)} trades from journal")
        except Exception as e:
            logger.error(f"Failed to load trades: {e}")
