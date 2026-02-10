"""Integration layer for Trade Database V2 with trading systems."""

import logging
import os
from typing import Any, Callable, Optional
from ib_insync import IB
from cpapi.unified_fill_processor import UnifiedFillProcessor
from cpapi.trade_database import TradeDatabase
from cpapi.position_tracker import PositionTracker

logger = logging.getLogger(__name__)

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
        wal_dir: str = "/home/jacobw/quantstack/logs/wal",
        ib_call: Callable[..., Any] | None = None,
    ):
        self.ib = ib
        self.system_name = system_name
        self.db_config = db_config or DEFAULT_DB_CONFIG
        self.db = TradeDatabase(self.db_config)
        self.positions = PositionTracker(self.db, ib)
        self.fill_processor = UnifiedFillProcessor(ib, self.db_config, wal_dir, ib_call=ib_call)
        
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
        from datetime import datetime
        metadata = metadata or {}
        # Normalize direction to lowercase for DB constraint
        direction_normalized = direction.lower()
        return self.db.open_trade(
            symbol=symbol,
            system=self.system_name,
            direction=direction_normalized,
            signal_price=signal_price,
            signal_time=datetime.now(),
            strategy=metadata.get('rule') or metadata.get('strategy'),
            substrategy=metadata.get('substrategy'),
            initial_stop=stop_loss,
            initial_target=take_profit,
            signal_data=metadata
        )
        
    def link_order(self, trade_id: str, order_id: int, is_entry: bool = True):
        """Link IBKR order to trade by order_id."""
        self.db.link_order_to_trade(
            trade_id=trade_id,
            ibkr_order_id=order_id,
            is_entry=is_entry,
            system=self.system_name,
        )
        
    def get_open_trades(self):
        """Get all open trades."""
        return self.db.get_open_trades()
        
    def update_stop(self, trade_id: int, new_stop: float, reason: str):
        """Update stop loss for trade."""
        self.db.update_stop(trade_id, new_stop, reason)
        
    def reconcile_positions(self):
        """Reconcile positions with IBKR."""
        return self.positions.reconcile_with_ibkr()
