#!/usr/bin/env python3
"""Test IBKR Platform functionality."""
import sys
import time

from cpapi.platform_client import IBKRPlatformClient


def test_platform():
    """Test platform client."""
    client = IBKRPlatformClient("test-service", "Platform Test")

    try:
        # Test platform health
        print("Testing platform health...")
        if not client.is_healthy():
            print("❌ Platform not healthy")
            return False
        print("✅ Platform healthy")

        # Test service registration
        print("Testing service registration...")
        if not client.register(["market-data", "orders"]):
            print("❌ Registration failed")
            return False
        print("✅ Service registered")

        # Test heartbeat
        print("Testing heartbeat...")
        if not client.heartbeat():
            print("❌ Heartbeat failed")
            return False
        print("✅ Heartbeat successful")

        # Test auth status
        print("Testing auth status...")
        authenticated = client.check_auth_status()
        print(f"✅ Auth status: {authenticated}")

        # Test accounts (if authenticated)
        if authenticated:
            print("Testing accounts...")
            accounts = client.get_accounts()
            print(f"✅ Accounts: {accounts}")

        # Test unregistration
        print("Testing unregistration...")
        if not client.unregister():
            print("❌ Unregistration failed")
            return False
        print("✅ Service unregistered")

        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


if __name__ == "__main__":
    success = test_platform()
    sys.exit(0 if success else 1)
