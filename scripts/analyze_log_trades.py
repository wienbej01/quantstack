#!/usr/bin/env python3
"""Extract trade statistics from systemd logs when database logging fails."""

import re
import sys
from datetime import datetime
from collections import defaultdict

def parse_log_trades(date_str):
    """Parse filled orders from journalctl logs."""
    import subprocess
    from datetime import datetime, timedelta
    
    # Parse date and get next day for until parameter
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    next_day = (dt + timedelta(days=1)).strftime('%Y-%m-%d')
    
    # Get logs for the trading day (22:00 to 06:00 next day Manila time)
    cmd = [
        'journalctl', '-u', 'l2-scalping',
        '--since', f'{date_str} 22:00:00',
        '--until', f'{next_day} 06:00:00',
        '--no-pager'
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    fills = []
    trades = []
    
    for line in result.stdout.split('\n'):
        # Match filled orders - extract from Execution object
        if "status='Filled'" in line and 'execution=Execution(' in line:
            # Extract from Execution object
            symbol_match = re.search(r"symbol='(\w+)'", line)
            side_match = re.search(r"side='(BOT|SLD)'", line)
            shares_match = re.search(r"shares=([\d.]+)", line)
            price_match = re.search(r"avgFillPrice=([\d.]+)", line)
            
            if all([symbol_match, side_match, shares_match, price_match]):
                fills.append({
                    'symbol': symbol_match.group(1),
                    'side': side_match.group(1),
                    'shares': float(shares_match.group(1)),
                    'price': float(price_match.group(1))
                })
        
        # Match trade signals
        if 'TRADE [' in line and '] ' in line:
            strategy_match = re.search(r'TRADE \[([^\]]+)\]: (\w+) (BUY|SELL)', line)
            if strategy_match:
                trades.append({
                    'strategy': strategy_match.group(1),
                    'symbol': strategy_match.group(2),
                    'direction': strategy_match.group(3)
                })
    
    return fills, trades

def analyze_fills(fills):
    """Analyze fill statistics."""
    if not fills:
        return None
    
    by_symbol = defaultdict(lambda: {'buys': 0, 'sells': 0, 'buy_qty': 0, 'sell_qty': 0, 'buy_value': 0, 'sell_value': 0})
    
    for fill in fills:
        symbol = fill['symbol']
        qty = fill['shares']
        value = qty * fill['price']
        
        if fill['side'] == 'BOT':
            by_symbol[symbol]['buys'] += 1
            by_symbol[symbol]['buy_qty'] += qty
            by_symbol[symbol]['buy_value'] += value
        else:
            by_symbol[symbol]['sells'] += 1
            by_symbol[symbol]['sell_qty'] += qty
            by_symbol[symbol]['sell_value'] += value
    
    return by_symbol

def main():
    if len(sys.argv) < 2:
        print("Usage: analyze_log_trades.py YYYY-MM-DD")
        sys.exit(1)
    
    date_str = sys.argv[1]
    
    print(f"Analyzing l2-scalping logs for {date_str}...")
    print("=" * 100)
    
    fills, trades = parse_log_trades(date_str)
    
    print(f"\nTotal Fills: {len(fills)}")
    print(f"Total Trade Signals: {len(trades)}")
    
    if not fills:
        print("\nNo fills found in logs.")
        return
    
    # Analyze by symbol
    by_symbol = analyze_fills(fills)
    
    print("\n" + "=" * 100)
    print("FILLS BY SYMBOL")
    print("=" * 100)
    print(f"{'Symbol':<10} {'Buys':<8} {'Buy Qty':<10} {'Buy $':<12} {'Sells':<8} {'Sell Qty':<10} {'Sell $':<12} {'Net Qty':<10}")
    print("-" * 100)
    
    for symbol in sorted(by_symbol.keys()):
        data = by_symbol[symbol]
        net_qty = data['buy_qty'] - data['sell_qty']
        print(f"{symbol:<10} {data['buys']:<8} {data['buy_qty']:<10.0f} ${data['buy_value']:<11,.2f} "
              f"{data['sells']:<8} {data['sell_qty']:<10.0f} ${data['sell_value']:<11,.2f} {net_qty:<10.0f}")
    
    # Strategy breakdown
    if trades:
        strategy_counts = defaultdict(int)
        for trade in trades:
            strategy_counts[trade['strategy']] += 1
        
        print("\n" + "=" * 100)
        print("TRADE SIGNALS BY STRATEGY")
        print("=" * 100)
        for strategy, count in sorted(strategy_counts.items(), key=lambda x: -x[1]):
            print(f"{strategy:<40} {count:>6} signals")
    
    # Summary
    total_buys = sum(d['buys'] for d in by_symbol.values())
    total_sells = sum(d['sells'] for d in by_symbol.values())
    total_buy_value = sum(d['buy_value'] for d in by_symbol.values())
    total_sell_value = sum(d['sell_value'] for d in by_symbol.values())
    
    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    print(f"Total Buy Fills:  {total_buys:>6}  ${total_buy_value:>12,.2f}")
    print(f"Total Sell Fills: {total_sells:>6}  ${total_sell_value:>12,.2f}")
    print(f"Gross Turnover:   ${(total_buy_value + total_sell_value):>12,.2f}")
    print(f"\nWARNING: Database logging failure - only {len(fills)} fills found in logs")
    print(f"         Actual P&L calculation requires matching entry/exit pairs")

if __name__ == '__main__':
    main()
