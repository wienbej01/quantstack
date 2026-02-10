"""Trade Journal for L2 VWAP Mean Reversion

Records all trades to shared PostgreSQL event store.
Sends NTFY notifications for trade executions.
Posts audit logs for system events.
"""

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Add intraday_stack to path for shared event store and notifications
_intraday_path = str(Path("/home/jacobw/intraday_stack/src"))
if _intraday_path not in sys.path:
    sys.path.append(_intraday_path)

try:
    from journal.event_store import EventStore
    SHARED_EVENT_STORE = True
except ImportError:
    SHARED_EVENT_STORE = False
    logging.warning("Could not import shared event store, using local journal")

try:
    from notifications.ntfy_notifier import NTFYNotifier
    NTFY_AVAILABLE = True
except ImportError:
    NTFY_AVAILABLE = False
    logging.warning("Could not import NTFY notifier")

# Audit logger
sys.path.insert(0, "/home/jacobw/quantstack/cpapi")
try:
    from audit_logger import AuditLogger, EventType, Severity
    AUDIT_AVAILABLE = True
except ImportError:
    AUDIT_AVAILABLE = False
    logging.warning("Could not import audit logger")

logger = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")

STRATEGY_NAME = "l2_vwap_reversion"


@dataclass
class LocalTradeRecord:
    """Fallback local trade record."""
    timestamp: str
    symbol: str
    side: str
    quantity: int
    entry_price: float
    exit_price: float | None = None
    pnl: float = 0.0
    vwap: float = 0.0
    l2_ratio: float | None = None
    exit_reason: str = ""


class TradeJournal:
    """Trade journal with PostgreSQL event store and NTFY notifications."""

    def __init__(self, log_dir: Path | None = None):
        self.log_dir = log_dir or Path("/home/jacobw/quantstack/l2_vwap_reversion/logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Shared PostgreSQL event store
        if SHARED_EVENT_STORE:
            self.event_store = EventStore(
                use_postgres=True,
                pg_config={'database': 'trading', 'user': 'jacobw'}
            )
            logger.info("Using shared PostgreSQL event store")
        else:
            self.event_store = None

        # NTFY notifier
        if NTFY_AVAILABLE:
            self.notifier = NTFYNotifier()
            logger.info("NTFY notifications enabled")
        else:
            self.notifier = None

        # Audit logger
        if AUDIT_AVAILABLE:
            self.audit = AuditLogger(service_name="l2-vwap-reversion")
            logger.info("Audit logging enabled")
        else:
            self.audit = None

        # Local fallback journal
        self._local_trades: list[LocalTradeRecord] = []
        self._open_trade_ids: dict[str, str] = {}  # symbol -> trade_id

    def log_entry(
        self,
        symbol: str,
        side: str,
        price: float,
        quantity: int,
        vwap: float,
        l2_ratio: float | None,
        stop_loss: float,
        take_profit: float,
        entry_order_id: int | None = None,
    ) -> str | None:
        """Log trade entry to event store and send notification."""
        
        signal_id = f"vwap_{symbol}_{datetime.now(ET).strftime('%H%M%S')}"
        trade_id = None

        # Log to PostgreSQL event store
        if self.event_store:
            try:
                # Log decision first
                self.event_store.log_decision(
                    symbol=symbol,
                    strategy=STRATEGY_NAME,
                    direction="long" if side == "LONG" else "short",
                    signal_strength=l2_ratio or 0.0,
                    net_edge_bps=0.0,
                    decision="TRADE",
                    features={
                        "vwap": vwap,
                        "l2_ratio": l2_ratio,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                    },
                )

                # Open trade
                trade_id = self.event_store.open_trade(
                    symbol=symbol,
                    strategy=STRATEGY_NAME,
                    direction="long" if side == "LONG" else "short",
                    signal_id=signal_id,
                    entry_order_id=int(entry_order_id) if entry_order_id is not None else 0,
                    entry_price=price,
                    entry_qty=quantity,
                    signal_price=price,
                    system="l2-vwap-reversion",
                )
                self._open_trade_ids[symbol] = trade_id
                logger.info(f"Trade opened in event store: {trade_id}")
            except Exception as e:
                logger.error(f"Failed to log entry to event store: {e}")

        # Send NTFY notification
        if self.notifier:
            try:
                self.notifier.trade_alert(
                    symbol=symbol,
                    direction=side,
                    price=price,
                    quantity=quantity,
                    system="l2-vwap-reversion"
                )
            except Exception as e:
                logger.warning(f"NTFY notification failed: {e}")

        # Audit log - use TRADE_OPEN for reconciliation
        if self.audit:
            self.audit.trade_open(
                symbol=symbol,
                direction=side,
                qty=quantity,
                price=price,
                trade_id=trade_id,
            )

        # Local fallback
        self._local_trades.append(LocalTradeRecord(
            timestamp=datetime.now(ET).isoformat(),
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=price,
            vwap=vwap,
            l2_ratio=l2_ratio,
        ))
        self._write_local({"event": "ENTRY", "symbol": symbol, "side": side, 
                          "price": price, "quantity": quantity, "vwap": vwap,
                          "l2_ratio": l2_ratio, "timestamp": datetime.now(ET).isoformat()})

        return trade_id

    def log_exit(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        quantity: int,
        reason: str,
        pnl: float,
        exit_order_id: int | None = None,
    ) -> None:
        """Log trade exit to event store and send notification."""

        trade_id = self._open_trade_ids.pop(symbol, None)

        # Close in PostgreSQL event store
        if self.event_store and trade_id:
            try:
                self.event_store.close_trade(
                    trade_id=trade_id,
                    exit_order_id=int(exit_order_id) if exit_order_id is not None else 0,
                    exit_price=exit_price,
                    exit_qty=quantity,
                    exit_reason=reason,
                    commission=0.0,
                    signal_price=exit_price,
                )
                logger.info(f"Trade closed in event store: {trade_id}, PnL=${pnl:.2f}")
            except Exception as e:
                logger.error(f"Failed to log exit to event store: {e}")

        # Send NTFY notification
        if self.notifier:
            try:
                self.notifier.trade_exit(
                    symbol=symbol,
                    pnl=pnl,
                    reason=reason,
                    system="l2-vwap-reversion"
                )
            except Exception as e:
                logger.warning(f"NTFY notification failed: {e}")

        # Audit log - use TRADE_CLOSE for reconciliation
        if self.audit:
            self.audit.trade_close(
                symbol=symbol,
                direction=side,
                qty=quantity,
                price=exit_price,
                pnl=pnl,
                trade_id=trade_id,
            )

        # Local fallback
        self._write_local({"event": "EXIT", "symbol": symbol, "side": side,
                          "entry_price": entry_price, "exit_price": exit_price,
                          "quantity": quantity, "reason": reason, "pnl": pnl,
                          "timestamp": datetime.now(ET).isoformat()})

    def log_service_start(self, symbols: list[str]) -> None:
        """Log service startup."""
        if self.audit:
            self.audit.log_event(
                event_type=EventType.SERVICE_START,
                message=f"L2 VWAP Reversion started with {len(symbols)} symbols",
                context={"symbols": symbols},
            )

    def log_service_stop(self, reason: str = "normal") -> None:
        """Log service shutdown."""
        if self.audit:
            self.audit.log_event(
                event_type=EventType.SERVICE_STOP,
                message=f"L2 VWAP Reversion stopped: {reason}",
                context={"reason": reason},
            )

    def log_error(self, message: str, context: dict | None = None) -> None:
        """Log error event."""
        if self.audit:
            self.audit.log_event(
                event_type=EventType.SERVICE_ERROR,
                message=message,
                severity=Severity.ERROR,
                context=context or {},
            )

    def _write_local(self, entry: dict) -> None:
        """Write to local JSONL file."""
        date_str = datetime.now(ET).strftime("%Y-%m-%d")
        journal_file = self.log_dir / f"trades_{date_str}.jsonl"
        try:
            with open(journal_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            logger.error(f"Failed to write local journal: {e}")
