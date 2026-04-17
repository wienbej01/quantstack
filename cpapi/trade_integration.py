"""Integration layer for Trade Database V2 with trading systems."""

import logging
import os
from pathlib import Path
from typing import Any, Callable, Optional
from ib_insync import IB
from cpapi.unified_fill_processor import UnifiedFillProcessor
from cpapi.trade_database import TradeDatabase
from cpapi.position_tracker import PositionTracker

logger = logging.getLogger(__name__)


def _default_wal_dir() -> str:
    """Resolve WAL storage under the quantstack-v2 repo by default."""
    return str(Path(__file__).resolve().parents[2] / "logs" / "wal")

# Default DB config from environment
DEFAULT_DB_CONFIG = {
    # Prefer Unix socket to use peer auth without password.
    'host': os.getenv('POSTGRES_HOST', '/var/run/postgresql'),
    'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'database': os.getenv('POSTGRES_DB', 'trading'),
    'user': os.getenv('POSTGRES_USER', 'jacobw'),
    'password': os.getenv('POSTGRES_PASSWORD', '')
}


class TradeIntegration:
    """Integrates Trade Database V2 with IB connection and trading systems."""
    
    def __init__(
        self,
        ib: IB,
        system_name: str,
        db_config: Optional[dict] = None,
        wal_dir: Optional[str] = None,
        ib_call: Callable[..., Any] | None = None,
    ):
        self.ib = ib
        self.system_name = system_name
        self.db_config = db_config or DEFAULT_DB_CONFIG
        self.db = TradeDatabase(self.db_config)
        self.positions = PositionTracker(self.db, ib)
        self.fill_processor = UnifiedFillProcessor(
            ib,
            self.db_config,
            wal_dir or _default_wal_dir(),
            ib_call=ib_call,
        )
        
    def start(self):
        """Start fill capture and processing."""
        self.fill_processor.start()
        logger.info(f"Trade integration started for {self.system_name}")
        
    def stop(self):
        """Stop fill capture and processing."""
        self.fill_processor.stop()
        logger.info(f"Trade integration stopped for {self.system_name}")
        
    def open_trade(
        self,
        symbol: str,
        direction: str,
        signal_price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        metadata: Optional[dict] = None
    ) -> str:
        """Open new trade and return trade_id."""
        from datetime import datetime, timezone
        metadata = metadata or {}
        # Normalize direction to lowercase for DB constraint
        direction_normalized = direction.lower()
        return self.db.open_trade(
            symbol=str(symbol),
            system=self.system_name,
            direction=direction_normalized,
            signal_price=float(signal_price),
            signal_time=datetime.now(timezone.utc),
            strategy=metadata.get('rule') or metadata.get('strategy'),
            substrategy=metadata.get('substrategy'),
            initial_stop=float(stop_loss) if stop_loss is not None else None,
            initial_target=float(take_profit) if take_profit is not None else None,
            signal_data=metadata
        )

    def record_signal(self, symbol: str, **kwargs):
        """Persist a canonical signal for this strategy."""
        return self.db.record_signal(system=self.system_name, symbol=str(symbol), **kwargs)

    def upsert_order(self, symbol: str, **kwargs):
        """Persist or update a canonical order for this strategy."""
        return self.db.upsert_order(system=self.system_name, symbol=str(symbol), **kwargs)

    def append_order_event(self, **kwargs):
        """Append a canonical order lifecycle event for this strategy."""
        return self.db.append_order_event(system=self.system_name, **kwargs)
        
    def link_order(self, trade_id: str, order_id: int, is_entry: bool = True, symbol: str = None):
        """Link IBKR order to trade by order_id."""
        self.db.link_order_to_trade(
            trade_id=trade_id,
            ibkr_order_id=order_id,
            is_entry=is_entry,
            system=self.system_name,
            symbol=symbol,
        )

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_qty: int,
        pnl: float,
        reason: str = "SIGNAL_EXIT",
        exit_order_id: int | None = None,
        gross_pnl: float | None = None,
        commission: float | None = None,
        hold_seconds: float | None = None,
    ):
        """Explicitly close a trade (fallback if auto-close from fills didn't trigger)."""
        try:
            closed = self.db.close_trade(
                trade_id=trade_id,
                exit_price=exit_price,
                exit_qty=exit_qty,
                pnl=pnl,
                reason=reason,
                exit_order_id=exit_order_id,
                gross_pnl=gross_pnl,
                commission=commission,
                hold_seconds=hold_seconds,
            )
            if closed:
                logger.info(f"Trade {trade_id} closed: pnl={pnl:.2f} reason={reason}")
        except Exception as e:
            logger.error(f"Failed to close trade {trade_id}: {e}")
        
    def get_open_trades(self):
        """Get all open trades."""
        return self.db.get_open_trades()
        
    def update_stop(self, trade_id: int, new_stop: float, reason: str):
        """Update stop loss for trade."""
        self.db.update_stop(trade_id, new_stop, reason)

    def set_initial_exits(self, trade_id: str, stop: float, target: float):
        """Set initial stop/target after fill (fill-based exits)."""
        self.db.set_initial_exits(trade_id, stop, target)
        
    def reconcile_positions(self):
        """Reconcile positions with IBKR."""
        return self.positions.reconcile_with_ibkr()
