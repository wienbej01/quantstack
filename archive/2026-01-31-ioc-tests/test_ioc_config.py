#!/usr/bin/env python3
"""Test IOC price improvement configuration"""

from pathlib import Path

import yaml

config_dir = Path("/home/jacobw/quantstack/l2_scalping/config")

# Load IBKR config
with open(config_dir / "ibkr.yaml") as f:
    ibkr_config = yaml.safe_load(f)

print("=== IBKR Configuration ===")
print(f"Full config: {ibkr_config}")
print()

orders_config = ibkr_config.get("orders", {})
print("=== Orders Configuration ===")
print(f"use_ioc_for_scalping: {orders_config.get('use_ioc_for_scalping')}")
print(
    f"ioc_price_improvement_ticks: {orders_config.get('ioc_price_improvement_ticks')}"
)
print(f"tick_size: {orders_config.get('tick_size')}")
print()

# Calculate improvement
use_ioc = orders_config.get("use_ioc_for_scalping", False)
improvement_ticks = orders_config.get("ioc_price_improvement_ticks", 0)
tick_size = orders_config.get("tick_size", 0.01)
price_improvement = improvement_ticks * tick_size if use_ioc else 0.0

print("=== Calculated Values ===")
print(f"use_ioc: {use_ioc}")
print(f"improvement_ticks: {improvement_ticks}")
print(f"tick_size: {tick_size}")
print(f"price_improvement: {price_improvement}")
print()

# Test with sample prices
ask = 187.39
bid = 187.38

buy_limit = ask + price_improvement
sell_limit = bid - price_improvement

print("=== Sample Order Prices ===")
print(f"Ask: {ask}")
print(f"Bid: {bid}")
print(f"BUY limit price: {buy_limit} (ask + {price_improvement})")
print(f"SELL limit price: {sell_limit} (bid - {price_improvement})")
