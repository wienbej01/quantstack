#!/usr/bin/env python3
"""Check IBKR connection status and provide setup instructions."""

import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path.home() / "transalpha" / "l2"))


def check_ibkr_status():
    """Check IBKR connection and provide instructions."""
    print("🔍 Checking IBKR Connection Status...")

    try:
        from ib_insync import IB

        ib = IB()

        # Test connection
        ib.connect("127.0.0.1", 7497, clientId=999, readonly=True, timeout=5)

        if ib.isConnected():
            accounts = ib.managedAccounts()
            print("✅ IBKR Connection: SUCCESS")
            print(f"   Account: {accounts}")
            print(f"   Port: 7497 (Paper Trading)")
            ib.disconnect()
            return True
        else:
            print("❌ IBKR Connection: FAILED")
            return False

    except Exception as e:
        print("❌ IBKR Connection: FAILED")
        print(f"   Error: {e}")
        print()
        print("📋 IBKR Setup Instructions:")
        print("1. Start TWS or IB Gateway")
        print("2. Login to paper trading account")
        print("3. Configure API settings:")
        print("   - Enable API connections")
        print("   - Set API port to 7497")
        print("   - Allow connections from 127.0.0.1")
        print("4. Restart TWS/Gateway after changes")
        print()
        print("🔧 Quick Test:")
        print("   python3 scripts/check_ibkr_status.py")
        return False


if __name__ == "__main__":
    success = check_ibkr_status()
    sys.exit(0 if success else 1)
