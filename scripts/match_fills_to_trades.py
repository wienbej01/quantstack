"""Match individual fills into completed round-trip trades."""
import pandas as pd
import numpy as np
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s | %(message)s')
logger = logging.getLogger(__name__)


def match_fills_to_trades(fills_df: pd.DataFrame) -> pd.DataFrame:
    """Match entry and exit fills into completed trades."""
    fills_df = fills_df.sort_values(['symbol', 'timestamp']).reset_index(drop=True)
    
    trades = []
    positions = {}  # symbol -> list of open positions
    
    for idx, fill in fills_df.iterrows():
        symbol = fill['symbol']
        side = fill['side']
        qty = fill['quantity']
        price = fill['price']
        timestamp = fill['timestamp']
        
        if symbol not in positions:
            positions[symbol] = []
        
        # Determine if this is entry or exit
        if side == 'BUY':
            # Could be opening long or closing short
            if len(positions[symbol]) > 0 and positions[symbol][0]['side'] == 'SELL':
                # Closing short position
                entry = positions[symbol].pop(0)
                pnl = (entry['price'] - price) * qty - entry['commission'] - fill['commission']
                
                trades.append({
                    'symbol': symbol,
                    'entry_time': entry['timestamp'],
                    'exit_time': timestamp,
                    'side': 'SHORT',
                    'entry_price': entry['price'],
                    'exit_price': price,
                    'quantity': qty,
                    'pnl': pnl,
                    'duration_minutes': (pd.to_datetime(timestamp) - pd.to_datetime(entry['timestamp'])).total_seconds() / 60,
                    'entry_order_id': entry['order_id'],
                    'exit_order_id': fill['order_id'],
                })
            else:
                # Opening long position
                positions[symbol].append({
                    'side': 'BUY',
                    'price': price,
                    'quantity': qty,
                    'timestamp': timestamp,
                    'commission': fill['commission'],
                    'order_id': fill['order_id'],
                })
        
        elif side == 'SELL':
            # Could be opening short or closing long
            if len(positions[symbol]) > 0 and positions[symbol][0]['side'] == 'BUY':
                # Closing long position
                entry = positions[symbol].pop(0)
                pnl = (price - entry['price']) * qty - entry['commission'] - fill['commission']
                
                trades.append({
                    'symbol': symbol,
                    'entry_time': entry['timestamp'],
                    'exit_time': timestamp,
                    'side': 'LONG',
                    'entry_price': entry['price'],
                    'exit_price': price,
                    'quantity': qty,
                    'pnl': pnl,
                    'duration_minutes': (pd.to_datetime(timestamp) - pd.to_datetime(entry['timestamp'])).total_seconds() / 60,
                    'entry_order_id': entry['order_id'],
                    'exit_order_id': fill['order_id'],
                })
            else:
                # Opening short position
                positions[symbol].append({
                    'side': 'SELL',
                    'price': price,
                    'quantity': qty,
                    'timestamp': timestamp,
                    'commission': fill['commission'],
                    'order_id': fill['order_id'],
                })
    
    # Report unclosed positions
    unclosed = sum(len(pos) for pos in positions.values())
    if unclosed > 0:
        logger.warning(f"{unclosed} positions remain unclosed")
    
    trades_df = pd.DataFrame(trades)
    
    if not trades_df.empty:
        # Calculate win rate and statistics
        trades_df['is_win'] = trades_df['pnl'] > 0
        logger.info(f"Matched {len(trades_df)} completed trades")
        logger.info(f"  Win rate: {trades_df['is_win'].mean():.1%}")
        logger.info(f"  Avg PnL: ${trades_df['pnl'].mean():.2f}")
        logger.info(f"  Total PnL: ${trades_df['pnl'].sum():.2f}")
    
    return trades_df


if __name__ == "__main__":
    # Test on existing fills
    fills_path = Path("artefacts/extensions/intraday_ml/phaseA_full_sip/fills.parquet")
    
    if not fills_path.exists():
        logger.error(f"Fills file not found: {fills_path}")
        exit(1)
    
    logger.info(f"Loading fills from {fills_path}")
    fills = pd.read_parquet(fills_path)
    logger.info(f"  {len(fills)} fills loaded")
    
    trades = match_fills_to_trades(fills)
    
    if not trades.empty:
        output_path = fills_path.parent / "matched_trades.parquet"
        trades.to_parquet(output_path, index=False)
        logger.info(f"✅ Saved matched trades to {output_path}")
        
        print("\nSample trades:")
        print(trades[['symbol', 'side', 'entry_price', 'exit_price', 'pnl', 'duration_minutes']].head(10))
    else:
        logger.warning("No completed trades found")
