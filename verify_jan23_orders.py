#!/usr/bin/env python3
"""
Verify Jan 23 orders against actual L2 market data.
Check if market really moved >$0.01 for ALL orders.
"""
import sys
from pathlib import Path
import pandas as pd
import sqlite3
from datetime import datetime

# Find L2 data
l2_data_path = Path("/home/jacobw/quantstack/data/l2/l2_maximum/features")
journal_db = Path("/home/jacobw/intraday_stack/data/journal/events.db")

def find_l2_files():
    """Find L2 data files for Jan 23"""
    date_str = "2026-01-23"
    files = list(l2_data_path.glob(f"*{date_str}*.parquet"))
    print(f"Found {len(files)} L2 data files for {date_str}")
    return files

def get_orders():
    """Get orders from journal database"""
    if not journal_db.exists():
        print(f"Journal DB not found: {journal_db}")
        return pd.DataFrame()
    
    conn = sqlite3.connect(str(journal_db))
    
    # Get all orders for Jan 23
    query = """
        SELECT 
            timestamp,
            order_id,
            symbol,
            action,
            quantity,
            order_type,
            entry_price,
            status,
            system_name,
            order_ref
        FROM orders 
        WHERE date(timestamp) = '2026-01-23'
        ORDER BY timestamp
    """
    
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    print(f"Found {len(df)} orders in database")
    return df

def load_l2_data(symbol, date_str="2026-01-23"):
    """Load L2 data for a symbol"""
    files = list(l2_data_path.glob(f"*{symbol}*{date_str}*.parquet"))
    if not files:
        return pd.DataFrame()
    
    dfs = []
    for f in files:
        try:
            df = pd.read_parquet(f)
            dfs.append(df)
        except Exception as e:
            print(f"Error reading {f}: {e}")
    
    if not dfs:
        return pd.DataFrame()
    
    combined = pd.concat(dfs, ignore_index=True)
    if 'timestamp' in combined.columns:
        combined['timestamp'] = pd.to_datetime(combined['timestamp'])
        combined = combined.sort_values('timestamp')
    
    return combined

def check_order_vs_market(order, l2_data):
    """Check if order should have filled based on market data"""
    order_time = pd.to_datetime(order['timestamp'])
    
    # Find L2 snapshot closest to order time
    if l2_data.empty or 'timestamp' not in l2_data.columns:
        return None, "No L2 data"
    
    # Get snapshot within 1 second of order
    time_diff = (l2_data['timestamp'] - order_time).abs()
    closest_idx = time_diff.idxmin()
    
    if time_diff[closest_idx] > pd.Timedelta(seconds=1):
        return None, f"No L2 data within 1s (closest: {time_diff[closest_idx]})"
    
    snapshot = l2_data.loc[closest_idx]
    
    # Check if order should have filled
    order_price = order['entry_price']
    action = order['action']
    
    if 'bid' not in snapshot or 'ask' not in snapshot:
        return None, "Missing bid/ask in L2 data"
    
    bid = snapshot['bid']
    ask = snapshot['ask']
    
    result = {
        'order_time': order_time,
        'market_time': snapshot['timestamp'],
        'time_diff_ms': time_diff[closest_idx].total_seconds() * 1000,
        'order_price': order_price,
        'market_bid': bid,
        'market_ask': ask,
        'action': action,
    }
    
    if action == 'BUY':
        # BUY order should fill if price >= ask
        result['should_fill'] = order_price >= ask
        result['price_vs_ask'] = order_price - ask
        result['reason'] = f"Order @ {order_price:.2f}, Ask @ {ask:.2f}, Diff: {result['price_vs_ask']:.3f}"
    else:  # SELL
        # SELL order should fill if price <= bid
        result['should_fill'] = order_price <= bid
        result['price_vs_bid'] = order_price - bid
        result['reason'] = f"Order @ {order_price:.2f}, Bid @ {bid:.2f}, Diff: {result['price_vs_bid']:.3f}"
    
    return result, None

def main():
    print("=" * 80)
    print("VERIFYING JAN 23 ORDERS AGAINST L2 MARKET DATA")
    print("=" * 80)
    
    # Get orders
    orders = get_orders()
    
    if orders.empty:
        print("\n❌ NO ORDERS FOUND IN DATABASE")
        print("This explains zero fills - no orders were placed!")
        print("\nPossible reasons:")
        print("1. Orders not logged to database")
        print("2. Service didn't actually run")
        print("3. All signals rejected before order placement")
        return
    
    print(f"\n✓ Found {len(orders)} orders")
    print(f"  Systems: {orders['system_name'].value_counts().to_dict()}")
    print(f"  Symbols: {orders['symbol'].value_counts().to_dict()}")
    
    # Check L2 data availability
    l2_files = find_l2_files()
    if not l2_files:
        print("\n❌ NO L2 DATA FOUND")
        print("Cannot verify orders without market data")
        return
    
    # Analyze each order
    results = []
    symbols_checked = set()
    
    for idx, order in orders.iterrows():
        symbol = order['symbol']
        
        # Load L2 data for this symbol (cache it)
        if symbol not in symbols_checked:
            print(f"\nLoading L2 data for {symbol}...")
            symbols_checked.add(symbol)
        
        l2_data = load_l2_data(symbol)
        
        if l2_data.empty:
            print(f"  ⚠ No L2 data for {symbol}")
            continue
        
        result, error = check_order_vs_market(order, l2_data)
        
        if error:
            print(f"  ⚠ Order {order['order_id']}: {error}")
            continue
        
        results.append(result)
    
    if not results:
        print("\n❌ COULD NOT VERIFY ANY ORDERS")
        print("No matching L2 data found")
        return
    
    # Summary
    print("\n" + "=" * 80)
    print("VERIFICATION RESULTS")
    print("=" * 80)
    
    df_results = pd.DataFrame(results)
    
    should_fill = df_results['should_fill'].sum()
    should_not_fill = (~df_results['should_fill']).sum()
    
    print(f"\nTotal orders verified: {len(df_results)}")
    print(f"  Should have filled: {should_fill}")
    print(f"  Should NOT have filled: {should_not_fill}")
    
    if should_fill > 0:
        print(f"\n⚠️  {should_fill} orders SHOULD have filled but didn't!")
        print("This indicates a bug in order execution, not just buffer size")
        print("\nOrders that should have filled:")
        print(df_results[df_results['should_fill']][['order_time', 'action', 'order_price', 'market_bid', 'market_ask', 'reason']])
    
    if should_not_fill == len(df_results):
        print("\n✓ All orders correctly did NOT fill")
        print("Market had moved beyond buffer for all orders")
        
        # Show price differences
        if 'price_vs_ask' in df_results.columns:
            buy_orders = df_results[df_results['action'] == 'BUY']
            if not buy_orders.empty:
                print(f"\nBUY orders - price vs ask:")
                print(f"  Mean: {buy_orders['price_vs_ask'].mean():.3f}")
                print(f"  Min: {buy_orders['price_vs_ask'].min():.3f}")
                print(f"  Max: {buy_orders['price_vs_ask'].max():.3f}")
        
        if 'price_vs_bid' in df_results.columns:
            sell_orders = df_results[df_results['action'] == 'SELL']
            if not sell_orders.empty:
                print(f"\nSELL orders - price vs bid:")
                print(f"  Mean: {sell_orders['price_vs_bid'].mean():.3f}")
                print(f"  Min: {sell_orders['price_vs_bid'].min():.3f}")
                print(f"  Max: {sell_orders['price_vs_bid'].max():.3f}")

if __name__ == "__main__":
    main()
