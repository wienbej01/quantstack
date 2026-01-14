#!/usr/bin/env python3
"""
Pre-Flight System Validation

Runs before SIP generation (09:00 ET) to validate critical infrastructure.
Checks: Gateway process, Platform authentication, Polygon API
"""

import os
import subprocess
import sys
from datetime import datetime

ERRORS = []


def send_ntfy(title: str, message: str, priority: str = "high", tags: str = "warning"):
    """Send NTFY notification."""
    import urllib.request

    try:
        safe_title = title.encode("ascii", "ignore").decode("ascii") or "Pre-Flight"
        req = urllib.request.Request(
            "https://ntfy.sh/jacobw-trading-alerts",
            data=message.encode("utf-8"),
            headers={"Title": safe_title, "Priority": priority, "Tags": tags},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"NTFY failed: {e}")


def test(name: str, func) -> bool:
    """Run test and track errors."""
    try:
        func()
        return True
    except Exception as e:
        ERRORS.append(f"{name}: {e}")
        return False


def check_gateway_process():
    """Check if Client Portal Gateway is running."""
    result = subprocess.run(
        ["pgrep", "-f", "clientportal"], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError("Gateway process not running")


def check_platform_auth():
    """Check if IBKR Platform is authenticated."""
    import urllib.request
    import json

    try:
        req = urllib.request.Request("http://127.0.0.1:8000/health", timeout=5)
        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read())
            if not data.get("authenticated"):
                raise RuntimeError("Platform not authenticated")
    except Exception as e:
        raise RuntimeError(f"Platform check failed: {e}")


def check_polygon():
    """Check Polygon API connectivity."""
    import urllib.request

    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("POLYGON_API_KEY not set")

    url = f"https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/2023-01-01/2023-01-02?apiKey={api_key}"
    req = urllib.request.Request(url, timeout=10)
    with urllib.request.urlopen(req) as response:
        if response.status != 200:
            raise RuntimeError(f"Polygon API returned {response.status}")


def main():
    print(f"Pre-flight validation: {datetime.now().isoformat()}")

    # Critical infrastructure checks only
    tests = [
        ("Gateway process", check_gateway_process),
        ("Platform authenticated", check_platform_auth),
        ("Polygon API", check_polygon),
    ]

    for name, func in tests:
        if test(name, func):
            print(f"  ✅ {name}")
        else:
            print(f"  ❌ {name}")

    if ERRORS:
        msg = (
            f"Pre-flight FAILED at {datetime.now().strftime('%H:%M ET')}:\n"
            + "\n".join(ERRORS[:5])
        )
        send_ntfy("⚠️ Pre-Flight FAILED", msg, priority="urgent", tags="rotating_light")
        print(f"\n❌ {len(ERRORS)} ERRORS - NTFY alert sent")
        return 1
    else:
        print(f"\n✅ All pre-flight checks passed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
