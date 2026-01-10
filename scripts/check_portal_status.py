#!/usr/bin/env python3
"""
Quick script to check IBKR account status via API
"""

from ib_insync import IB, util
import pandas as pd
from datetime import datetime, timedelta

def check_account_status():
    ib = IB()
    
    try:
        print("Connecting to IBKR Gateway...")
        ib.connect('127.0.0.1', 7497, clientId=99, timeout=30)
        print(f"✅ Connected")
        
        # Get account summary
        print("\n=== ACCOUNT SUMMARY ===")
        account_values = ib.accountValues()
        key_metrics = ['NetLiquidation', 'TotalCashValue', 'UnrealizedPnL', 'RealizedPnL']
        
        for av in account_values:
            if av.tag in key_metrics:
                print(f"{av.tag}: {av.value} {av.currency}")
        
        # Get current positions
        print("\n=== CURRENT POSITIONS ===")
        positions = ib.positions()
        if positions:
            for pos in positions:
                pnl = pos.unrealizedPNL if pos.unrealizedPNL else 0
                print(f"{pos.contract.symbol}: {pos.position} shares @ ${pos.avgCost:.2f} | P&L: ${pnl:.2f}")
        else:
            print("No open positions")
        
        # Get recent trades (executions)
        print("\n=== RECENT EXECUTIONS ===")
        executions = ib.executions()
        
        # Filter for today and yesterday
        yesterday = datetime.now() - timedelta(days=1)
        recent_execs = [e for e in executions if e.time.date() >= yesterday.date()]
        
        if recent_execs:
            print("Time                | Symbol | Side | Qty | Price    | Order ID")
            print("-" * 65)
            for ex in recent_execs[-20:]:  # Last 20
                time_str = ex.time.strftime("%m-%d %H:%M:%S")
                print(f"{time_str} | {ex.contract.symbol:>6} | {ex.side:>4} | {ex.shares:>3} | ${ex.price:>7.2f} | {ex.orderId}")
        else:
            print("No recent executions found")
            
        # Get open orders
        print("\n=== OPEN ORDERS ===")
        open_orders = ib.openOrders()
        if open_orders:
            for order in open_orders:
                print(f"Order {order.orderId}: {order.action} {order.totalQuantity} {order.contract.symbol} @ ${order.lmtPrice}")
        else:
            print("No open orders")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        
    finally:
        if ib.isConnected():
            ib.disconnect()
            print("\n✅ Disconnected")

if __name__ == "__main__":
    check_account_status()
