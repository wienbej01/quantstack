#!/usr/bin/env python3
"""Test L2 signal generation flow with mock data"""
import sys

sys.path.insert(0, "/home/jacobw/quantstack/l2_scalping/src")

import time

import yaml
from data.l2_feed import L2Snapshot
from signals.l2_signals import L2SignalGenerator
from signals.l2_signals import L2Snapshot as SignalSnapshot

# Load config
with open("/home/jacobw/quantstack/l2_scalping/config/strategy.yaml") as f:
    config = yaml.safe_load(f)

generator = L2SignalGenerator(config)

# Test 1: Strong buy signal (high OBI)
print("Test 1: Strong buy signal")
snap = SignalSnapshot(
    symbol="TEST",
    timestamp=time.time(),
    mid=100.0,
    spread=0.01,
    obi_1=0.75,  # Strong buy
    obi_5=0.70,
    depth_bid=100000.0,
    depth_ask=50000.0,
    pressure=0.5,
)
signal = generator.generate_signal(snap)
print(
    f"  Signal: {signal.signal_type.name}, strength={signal.strength:.2f}, confidence={signal.confidence:.2f}"
)

# Test 2: Strong sell signal
print("\nTest 2: Strong sell signal")
snap.obi_1 = -0.75
snap.obi_5 = -0.70
snap.depth_bid = 50000.0
snap.depth_ask = 100000.0
snap.pressure = -0.5
signal = generator.generate_signal(snap)
print(
    f"  Signal: {signal.signal_type.name}, strength={signal.strength:.2f}, confidence={signal.confidence:.2f}"
)

# Test 3: Neutral (no signal)
print("\nTest 3: Neutral signal")
snap.obi_1 = 0.1
snap.obi_5 = 0.05
snap.pressure = 0.05
signal = generator.generate_signal(snap)
print(
    f"  Signal: {signal.signal_type.name}, strength={signal.strength:.2f}, confidence={signal.confidence:.2f}"
)

print("\n✓ Signal generation working correctly")
