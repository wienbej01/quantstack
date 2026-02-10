"""Example: Integrate Trade Database V2 with l2-scalping system."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ib_insync import IB
from cpapi.trade_integration import TradeIntegration
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'host': 'localhost',
    'port': 5432,
    'database': 'trading',
    'user': 'jacobw',
    'password': ''  # Set via environment or config file
}

def main():
    """Example integration with l2-scalping."""
    
    # Connect to IBKR
    ib = IB()
    ib.connect('127.0.0.1', 4002, clientId=100)
    
    # Initialize trade integration
    trade_int = TradeIntegration(ib, system_name="example", db_config=DB_CONFIG)
    trade_int.start()
    
    try:
        # Example: Open a trade
        trade_id = trade_int.open_trade(
            symbol='AAPL',
            direction='LONG',
            entry_reason='L2 scalping signal',
            stop_loss=150.00,
            take_profit=152.00,
            metadata={'strategy': 'l2-scalping', 'signal_score': 0.85}
        )
        logger.info(f"Opened trade {trade_id}")
        
        # Place order via your existing order manager
        # order = place_order(...)
        # trade_int.link_order(trade_id, order.orderId)
        
        # Fills are automatically captured by UnifiedFillProcessor
        # Trades and positions are automatically updated
        
        # Example: Update stop loss
        # trade_int.update_stop(trade_id, 151.00, "Trailing stop")
        
        # Example: Check open trades
        open_trades = trade_int.get_open_trades()
        logger.info(f"Open trades: {len(open_trades)}")
        
        # Example: Reconcile positions
        discrepancies = trade_int.reconcile_positions()
        if discrepancies:
            logger.warning(f"Position discrepancies: {discrepancies}")
            
    finally:
        trade_int.stop()
        ib.disconnect()

if __name__ == '__main__':
    main()
