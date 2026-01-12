#!/usr/bin/env python3
"""Quick gateway connectivity check."""
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://localhost:5000/v1/api"


def check():
    try:
        # Check if gateway is responding
        r = requests.post(
            f"{BASE}/iserver/auth/status", json={}, verify=False, timeout=5
        )
        print(f"Gateway status: HTTP {r.status_code}")

        if r.status_code == 200:
            data = r.json()
            print(f"  authenticated: {data.get('authenticated')}")
            print(f"  connected: {data.get('connected')}")
            print(f"  competing: {data.get('competing')}")
            return data.get("authenticated", False)
        elif r.status_code == 401:
            print("  ⚠️  Not authenticated - browser login required")
            print(f"\n  Open https://localhost:5000 in browser to login")
            return False
        else:
            print(f"  Response: {r.text[:200]}")
            return False
    except requests.exceptions.ConnectionError:
        print("❌ Gateway not running on port 5000")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    check()
