#!/usr/bin/env python3
"""Test stale signal validation logic."""

from datetime import datetime, timezone, timedelta
import sys
from pathlib import Path

# Mock ranked candidate
class MockRankedCandidate:
    def __init__(self, timestamp_str, symbol="TEST"):
        self.timestamp = timestamp_str
        self.symbol = symbol
        self.entry_price = 100.0
        self.direction = "long"

def test_signal_age_validation(rc, max_age_seconds=300):
    """Test the signal age validation logic from paper_trade.py."""
    try:
        # Parse timestamp
        signal_time = datetime.fromisoformat(rc.timestamp.replace('Z', '+00:00'))
        if signal_time.tzinfo is None:
            signal_time = signal_time.replace(tzinfo=timezone.utc)
        
        # Calculate age
        signal_age_seconds = (datetime.now(timezone.utc) - signal_time).total_seconds()
        
        # Check if stale
        if signal_age_seconds > max_age_seconds:
            print(f"❌ REJECTED: {rc.symbol} age={signal_age_seconds:.0f}s (max={max_age_seconds}s) timestamp={rc.timestamp}")
            return False
        elif signal_age_seconds > 60:
            print(f"⚠️  WARNING: {rc.symbol} age={signal_age_seconds:.0f}s old")
            return True
        else:
            print(f"✅ ACCEPTED: {rc.symbol} age={signal_age_seconds:.0f}s old")
            return True
    except Exception as e:
        print(f"❌ ERROR: Failed to parse timestamp {rc.timestamp}: {e}")
        return False

if __name__ == "__main__":
    print("Testing Stale Signal Validation\n" + "="*50)
    
    now = datetime.now(timezone.utc)
    
    # Test 1: Fresh signal (30 seconds old)
    print("\n1. Fresh signal (30 seconds old):")
    fresh = now - timedelta(seconds=30)
    rc1 = MockRankedCandidate(fresh.isoformat())
    test_signal_age_validation(rc1)
    
    # Test 2: Recent signal (2 minutes old)
    print("\n2. Recent signal (2 minutes old):")
    recent = now - timedelta(minutes=2)
    rc2 = MockRankedCandidate(recent.isoformat())
    test_signal_age_validation(rc2)
    
    # Test 3: Stale signal (6 minutes old) - should be rejected
    print("\n3. Stale signal (6 minutes old) - SHOULD BE REJECTED:")
    stale = now - timedelta(minutes=6)
    rc3 = MockRankedCandidate(stale.isoformat())
    test_signal_age_validation(rc3)
    
    # Test 4: Very stale signal (19 hours old) - UNG scenario
    print("\n4. Very stale signal (19 hours old) - UNG SCENARIO:")
    very_stale = now - timedelta(hours=19)
    rc4 = MockRankedCandidate(very_stale.isoformat(), symbol="UNG")
    test_signal_age_validation(rc4)
    
    # Test 5: Pandas Timestamp format (from bar data)
    print("\n5. Pandas Timestamp format (2026-01-21 14:28:00-05:00):")
    rc5 = MockRankedCandidate("2026-01-21 14:28:00-05:00", symbol="UNG")
    test_signal_age_validation(rc5)
    
    print("\n" + "="*50)
    print("Test complete. Stale signals (>5 min) should be rejected.")
