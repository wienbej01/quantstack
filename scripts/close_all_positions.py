#!/usr/bin/env python3
"""Close all open positions via IBKR TWS API."""

import sys
from ib_insync import IB, MarketOrder


def main():
    ib = IB()
    
    try:
        ib.connect('127.0.0.1', 7494, clientId=999)
        print("Connected to IBKR Gateway")
        
        positions = ib.positions()
        if not positions:
            print("No open positions")
            return 0
        
        print(f"\nFound {len(positions)} positions:")
        for pos in positions:
            print(f"  {pos.contract.symbol}: {pos.position} shares")
        
        print(f"\nClosing all positions...")
        for pos in positions:
            if pos.position == 0:
                continue
            
            action = "SELL" if pos.position > 0 else "BUY"
            order = MarketOrder(action, abs(pos.position))
            trade = ib.placeOrder(pos.contract, order)
            print(f"  {action} {abs(pos.position)} {pos.contract.symbol}")
        
        ib.sleep(2)
        print("\nAll closing orders submitted")
        
    finally:
        ib.disconnect()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
