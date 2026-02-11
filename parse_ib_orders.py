#!/usr/bin/env python3
import re

# Parse first order: BUY NVDA at 187.39 IOC
# <- [3;16246;4815747;NVDA;STK;;0.0;;;NYSE;NASDAQ;USD;NVDA;NMS;;;BUY;5;LMT;187.39;;IOC

orders = []
with open("/home/jacobw/api-exported-logs.txt", "r") as f:
    for line in f:
        if "<- [3;" in line and "IOC" in line:
            match = re.search(
                r"(\d{2}:\d{2}:\d{2}:\d{3}).*<- \[3;(\d+);.*?;([A-Z]+);.*?;(BUY|SELL);(\d+);(LMT|MKT);([\d.]+)",
                line,
            )
            if match:
                time, order_id, symbol, action, qty, order_type, price = match.groups()
                orders.append(
                    {
                        "time": time,
                        "order_id": order_id,
                        "symbol": symbol,
                        "action": action,
                        "qty": qty,
                        "type": order_type,
                        "price": float(price),
                    }
                )

print(f"Found {len(orders)} IOC orders")
print("\nFirst 10 orders:")
for o in orders[:10]:
    print(
        f"  {o['time']} | {o['action']:4} {o['symbol']:6} @ ${o['price']:.2f} | Order #{o['order_id']}"
    )

# Group by symbol
from collections import defaultdict

by_symbol = defaultdict(list)
for o in orders:
    by_symbol[o["symbol"]].append(o)

print(f"\nOrders by symbol:")
for sym, ords in sorted(by_symbol.items()):
    print(f"  {sym}: {len(ords)} orders")

# Check price ranges for NVDA
if "NVDA" in by_symbol:
    nvda = by_symbol["NVDA"]
    buy_prices = [o["price"] for o in nvda if o["action"] == "BUY"]
    sell_prices = [o["price"] for o in nvda if o["action"] == "SELL"]

    print(f"\nNVDA price analysis:")
    if buy_prices:
        print(
            f"  BUY orders: {len(buy_prices)}, range ${min(buy_prices):.2f} - ${max(buy_prices):.2f}"
        )
    if sell_prices:
        print(
            f"  SELL orders: {len(sell_prices)}, range ${min(sell_prices):.2f} - ${max(sell_prices):.2f}"
        )
