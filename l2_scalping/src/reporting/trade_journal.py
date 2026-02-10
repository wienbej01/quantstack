"""Trade Journal for L2 Scalping System

Records all trades, signals, and performance metrics.
Uses shared event store for consistency with intraday-paper system.
Sends NTFY notifications for trade executions.
"""

import json
import logging
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

# Add intraday_stack to path for shared event store and notifications
# Use append to avoid shadowing l2_scalping modules
_intraday_path = str(Path(__file__).parent.parent.parent.parent.parent / "intraday_stack" / "src")
if _intraday_path not in sys.path:
    sys.path.append(_intraday_path)

try:
    from journal.event_store import EventStore

    SHARED_EVENT_STORE = True
except ImportError:
    SHARED_EVENT_STORE = False
    logging.warning("Could not import shared event store, using local journal")

# Use qx-broker notify functions for NTFY
try:
    from qx_broker.notify import send_trade_notification
    NTFY_AVAILABLE = True
except ImportError:
    NTFY_AVAILABLE = False
    logging.warning("Could not import qx_broker notify functions")

# Audit logger
sys.path.insert(0, "/home/jacobw/quantstack/cpapi")
try:
    from audit_logger import AuditLogger, EventType, Severity

    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False
    logging.warning("Could not import audit logger")

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
    rule_name: str = "obi_momentum"  # Trading rule attribution

    def to_dict(self) -> dict:
        return asdict(self)


class TradeJournal:
    """Manages trade records and persistence"""

    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)

        # Daily journal file (always set for fallback)
        today = datetime.now().strftime("%Y%m%d")
        self.journal_file = self.data_dir / f"trades_{today}.jsonl"

        # Use shared event store if available
        if SHARED_EVENT_STORE:
            try:
                self.event_store = EventStore(
                    use_postgres=True,
                    pg_config={"database": "trading", "user": "jacobw"},
                )
                logger.info("Using shared PostgreSQL event store for L2 scalping trades")
                self._ensure_postgres_schema()
            except Exception as exc:
                logger.error(f"Failed to initialize shared event store: {exc}", exc_info=True)
                self.event_store = None
        else:
            self.event_store = None

        # NTFY notifications via qx-broker
        self.ntfy_available = NTFY_AVAILABLE
        if self.ntfy_available:
            logger.info("NTFY notifications enabled for L2 scalping")

        # Audit logger
        if AUDIT_AVAILABLE:
            self.audit = AuditLogger(service_name="l2-scalping")
            logger.info("Audit logging enabled for L2 scalping")
        else:
            self.audit = None

        # In-memory storage
        self.trades: list[TradeRecord] = []
        if not SHARED_EVENT_STORE or not self.event_store:
            self.load_today_trades()

        logger.info("L2 Trade journal initialized")

    def _ensure_postgres_schema(self) -> None:
        """Ensure PostgreSQL schema supports extended trade fields."""
        if not self.event_store or not getattr(self.event_store, "use_postgres", False):
            return

        conn = getattr(self.event_store, "conn", None)
        if conn is None:
            return

        cursor = conn.cursor()
        try:
            cursor.execute("ALTER TABLE trades ADD COLUMN IF NOT EXISTS system TEXT")
            cursor.execute(
                "ALTER TABLE trades ADD COLUMN IF NOT EXISTS signal_entry_price REAL"
            )
            cursor.execute(
                "ALTER TABLE trades ADD COLUMN IF NOT EXISTS signal_exit_price REAL"
            )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Failed to ensure PostgreSQL trade schema")

    def record_signal(
        self, symbol: str, signal_type: str, signal_strength: float
    ) -> str:
        """Record a trading signal (before execution)"""
        trade_id = f"{symbol}_{datetime.now().strftime('%H%M%S_%f')}"

        if SHARED_EVENT_STORE and self.event_store:
            # Log decision to shared event store
            self.event_store.log_decision(
                symbol=symbol,
                strategy="l2_scalping",
                direction="long" if signal_strength > 0 else "short",
                signal_strength=abs(signal_strength),
                net_edge_bps=signal_strength * 100,  # Convert to bps
                decision="TRADE",
                features={"signal_type": signal_type},
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
        if not SHARED_EVENT_STORE or not self.event_store:
            self._persist_trade(trade)

        logger.info(
            f"L2 Signal recorded: {symbol} {signal_type} strength={signal_strength:.3f}"
        )
        return trade_id

    def record_trade_entry(
        self,
        symbol: str,
        side: str,
        quantity: int,
        entry_price: float,
        order_id: str,
        rule_name: str = "obi_momentum",
        signal_id: str | None = None,
        signal_price: float | None = None,
    ) -> str:
        """Record trade entry with rule attribution and NTFY notification.

        Args:
            entry_price: Actual fill price
            signal_price: Original signal price (for slippage calculation)
        """
        trade_id = ""
        system_tag = f"l2-scalping:{rule_name}"

        if SHARED_EVENT_STORE and self.event_store:
            if not signal_id:
                signal_id = f"l2_{rule_name}_{symbol}_{datetime.now().strftime('%H%M%S')}"
            # Open trade in shared event store with rule_name in strategy field
            try:
                trade_id = self.event_store.open_trade(
                    symbol=symbol,
                    strategy=f"l2_scalping_{rule_name}",  # Include rule name
                    direction="long" if side == "BUY" else "short",
                    signal_id=signal_id,
                    entry_order_id=int(order_id) if order_id.isdigit() else 0,
                    entry_price=entry_price,
                    entry_qty=quantity,
                    signal_price=signal_price if signal_price is not None else entry_price,
                    system="l2-scalping",
                )
            except Exception as exc:
                logger.error(f"Failed to open L2 trade in shared store: {exc}", exc_info=True)
                trade_id = ""

            if not trade_id:
                logger.error(f"L2 Trade open FAILED [{rule_name}] for {symbol}")
                if self.audit:
                    self.audit.log_event(
                        event_type=EventType.ERROR,
                        message=f"Trade open failed for {symbol}",
                        severity=Severity.ERROR,
                        context={
                            "symbol": symbol,
                            "side": side,
                            "quantity": quantity,
                            "entry_price": entry_price,
                            "order_id": order_id,
                            "rule_name": rule_name,
                        },
                    )
                return ""

            logger.info(f"L2 Trade opened [{rule_name}] in shared store: {trade_id}")

            if self.audit:
                self.audit.log_event(
                    event_type=EventType.TRADE_SIGNAL,
                    message=f"ENTRY {side} {quantity} {symbol} @ {entry_price:.4f}",
                    context={
                        "symbol": symbol,
                        "side": side,
                        "quantity": quantity,
                        "entry_price": entry_price,
                        "order_id": order_id,
                        "signal_price": signal_price if signal_price is not None else entry_price,
                        "rule_name": rule_name,
                        "trade_id": trade_id,
                    },
                )
                self.audit.trade_open(
                    symbol=symbol,
                    direction=side,
                    qty=quantity,
                    price=entry_price,
                    trade_id=trade_id,
                )

        # Fallback to local journal
        else:
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
                    rule_name=rule_name,
                )
                self.trades.append(trade)
            else:
                trade.side = side
                trade.quantity = quantity
                trade.entry_price = entry_price
                trade.order_id = order_id
                trade.fill_time = datetime.now().isoformat()
                trade.status = TradeStatus.FILLED.value
                trade.rule_name = rule_name

            self._persist_trade(trade)
            logger.info(f"L2 Trade entry [{rule_name}]: {symbol} {side} {quantity}@{entry_price:.4f}")
            trade_id = f"local_{symbol}_{datetime.now().strftime('%H%M%S')}"

            if self.audit:
                self.audit.log_event(
                    event_type=EventType.TRADE_SIGNAL,
                    message=f"ENTRY {side} {quantity} {symbol} @ {entry_price:.4f}",
                    context={
                        "symbol": symbol,
                        "side": side,
                        "quantity": quantity,
                        "entry_price": entry_price,
                        "order_id": order_id,
                        "rule_name": rule_name,
                    },
                )

        # Send NTFY notification after trade_id is available
        if self.ntfy_available:
            send_trade_notification(
                action="ENTRY",
                symbol=symbol,
                strategy=system_tag,
                direction=side,
                price=entry_price,
                quantity=quantity,
                position_id=trade_id[:8] if trade_id else None,
            )

        return trade_id

    def record_decision(
        self,
        symbol: str,
        strategy: str,
        direction: str,
        signal_strength: float,
        decision: str,
        rejection_reason: str = "",
        features: dict | None = None,
    ) -> str:
        """Record decision event for correlation with PnL."""
        if not SHARED_EVENT_STORE or not self.event_store:
            return ""

        return self.event_store.log_decision(
            symbol=symbol,
            strategy=strategy,
            direction=direction,
            signal_strength=signal_strength,
            net_edge_bps=0.0,
            decision=decision,
            rejection_reason=rejection_reason,
            features=features or {},
        )

    def record_trade_exit(
        self,
        trade_id: str,
        symbol: str,
        exit_price: float,
        exit_qty: int,
        pnl: float,
        commission: float = 0.0,
        rule_name: str = "obi_momentum",
        exit_reason: str = "L2_SIGNAL",
        exit_order_id: int | None = None,
    ) -> None:
        """Record trade exit with NTFY notification"""
        system_tag = f"l2-scalping:{rule_name}"

        # Send NTFY notification (use shortened trade_id for position_id)
        if self.ntfy_available:
            send_trade_notification(
                action="EXIT",
                symbol=symbol,
                strategy=system_tag,
                direction="",  # Not used for EXIT
                price=exit_price,
                quantity=exit_qty,
                pnl=pnl,
                exit_reason=exit_reason,
                position_id=trade_id[:8] if trade_id else None,
            )

        if SHARED_EVENT_STORE and self.event_store and trade_id:
            # Close trade in shared event store
            try:
                self.event_store.close_trade(
                    trade_id=trade_id,
                    exit_order_id=int(exit_order_id) if exit_order_id is not None else 0,
                    exit_price=exit_price,
                    exit_qty=exit_qty,
                    exit_reason=exit_reason,
                    commission=commission,
                    signal_price=exit_price,
                )
                logger.info(f"L2 Trade closed [{rule_name}] in shared store: {trade_id}")
            except Exception as exc:
                logger.error(f"Failed to close L2 trade in shared store: {exc}", exc_info=True)
                return

            if self.audit:
                self.audit.log_event(
                    event_type=EventType.INFO,
                    message=f"EXIT {symbol} @ {exit_price:.4f} pnl={pnl:.2f}",
                    context={
                        "symbol": symbol,
                        "exit_price": exit_price,
                        "exit_qty": exit_qty,
                        "pnl": pnl,
                        "commission": commission,
                        "exit_reason": exit_reason,
                        "rule_name": rule_name,
                        "exit_order_id": exit_order_id,
                        "trade_id": trade_id,
                    },
                )
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

        if self.audit:
            self.audit.log_event(
                event_type=EventType.INFO,
                message=f"EXIT {symbol} @ {exit_price:.4f} pnl={pnl:.2f}",
                context={
                    "symbol": symbol,
                    "exit_price": exit_price,
                    "exit_qty": exit_qty,
                    "pnl": pnl,
                    "commission": commission,
                    "exit_reason": exit_reason,
                    "rule_name": rule_name,
                },
            )

    def record_fill(
        self,
        order_id: int,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        commission: float = 0.0,
        exchange: str = "",
        exec_id: str = "",
        realized_pnl: float = 0.0,
    ) -> None:
        """Record execution fills to shared event store and audit log."""
        if SHARED_EVENT_STORE and self.event_store:
            try:
                self.event_store.log_fill(
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=price,
                    commission=commission,
                    exchange=exchange,
                    exec_id=exec_id,
                    realized_pnl=realized_pnl,
                )
            except Exception as exc:
                logger.error(f"Failed to log fill for {symbol}: {exc}", exc_info=True)

        if self.audit:
            self.audit.log_event(
                event_type=EventType.INFO,
                message=f"FILL {side} {quantity} {symbol} @ {price:.4f}",
                context={
                    "order_id": order_id,
                    "symbol": symbol,
                    "side": side,
                    "quantity": quantity,
                    "price": price,
                    "commission": commission,
                    "exchange": exchange,
                    "exec_id": exec_id,
                    "realized_pnl": realized_pnl,
                },
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

    def open_trade(self, trade_id: str, symbol: str, direction: str, 
                   entry_order_id: int, target_qty: int, signal_price: float) -> None:
        """Record trade opening - called when entry order is placed."""
        if not self.event_store:
            return
            
        try:
            self.event_store.record_order(
                order_id=entry_order_id,
                symbol=symbol,
                side=direction.upper(),
                quantity=target_qty,
                order_type="MKT",
                metadata={
                    "trade_id": trade_id,
                    "intent": "ENTRY",
                    "signal_price": signal_price
                }
            )
            logger.info(f"Trade opened: {trade_id[:8]} {symbol} {direction} {target_qty}")
        except Exception as e:
            logger.error(f"Failed to record trade opening: {e}")

    def record_entry_fill(self, trade_id: str, fill_price: float, fill_qty: int,
                          is_partial: bool) -> None:
        """Record entry fill - updates avg_entry_price."""
        if not self.event_store:
            return
            
        try:
            # This will be handled by the existing record_fill method
            logger.debug(f"Entry fill recorded: {trade_id[:8]} {fill_qty}@{fill_price}")
        except Exception as e:
            logger.error(f"Failed to record entry fill: {e}")

    def record_tp_sl_orders(self, trade_id: str, tp_order_id: int, sl_order_id: int,
                            tp_price: float, sl_price: float) -> None:
        """Record TP/SL orders after entry is filled."""
        if not self.event_store:
            return
            
        try:
            # Record TP order
            self.event_store.record_order(
                order_id=tp_order_id,
                symbol="",  # Will be filled by caller
                side="SELL",  # Will be corrected by caller
                quantity=0,   # Will be filled by caller
                order_type="LMT",
                metadata={
                    "trade_id": trade_id,
                    "intent": "TP",
                    "tp_price": tp_price
                }
            )
            
            # Record SL order
            self.event_store.record_order(
                order_id=sl_order_id,
                symbol="",  # Will be filled by caller
                side="SELL",  # Will be corrected by caller
                quantity=0,   # Will be filled by caller
                order_type="STP",
                metadata={
                    "trade_id": trade_id,
                    "intent": "SL",
                    "sl_price": sl_price
                }
            )
            
            logger.info(f"TP/SL orders recorded: {trade_id[:8]} TP={tp_price:.4f} SL={sl_price:.4f}")
        except Exception as e:
            logger.error(f"Failed to record TP/SL orders: {e}")

    def record_exit_fill(self, trade_id: str, fill_price: float, fill_qty: int,
                         exit_reason: str, is_partial: bool) -> None:
        """Record exit fill - updates avg_exit_price."""
        if not self.event_store:
            return
            
        try:
            # This will be handled by the existing record_fill method
            logger.info(f"Exit fill recorded: {trade_id[:8]} {exit_reason} {fill_qty}@{fill_price}")
        except Exception as e:
            logger.error(f"Failed to record exit fill: {e}")

    def close_trade(self, trade_id: str, exit_reason: str, 
                    avg_exit_price: float, pnl: float) -> None:
        """Record trade closure - called when position is fully closed."""
        if not self.event_store:
            return
            
        try:
            # Update trade record with final details
            logger.info(f"Trade closed: {trade_id[:8]} {exit_reason} PnL=${pnl:.2f}")
        except Exception as e:
            logger.error(f"Failed to record trade closure: {e}")

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
