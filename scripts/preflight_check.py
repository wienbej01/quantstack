#!/usr/bin/env python3
"""
Pre-Flight System Validation

Runs 1 hour before market prep to catch issues early.
Sends NTFY alert only on FAILURE.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

os.chdir("/home/jacobw/quantstack")
sys.path.insert(0, "/home/jacobw/quantstack/l2_scalping/src")

ERRORS = []


def send_ntfy(title: str, message: str, priority: str = "high", tags: str = "warning"):
    """Send NTFY notification."""
    import urllib.request

    try:
        req = urllib.request.Request(
            "https://ntfy.sh/jacobw-trading-alerts",
            data=message.encode(),
            headers={"Title": title, "Priority": priority, "Tags": tags},
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


def main():
    print(f"Pre-flight validation: {datetime.now().isoformat()}")

    # Critical tests only
    tests = [
        ("Python imports", lambda: __import__("data.l2_feed", fromlist=["L2DataFeed"])),
        (
            "SIP file exists",
            lambda: assert_true(
                Path("/home/jacobw/intraday_stack/data/daily_sip").glob("date=*")
            ),
        ),
        ("Config loads", lambda: load_config()),
        ("Services active", lambda: check_services()),
        ("Polygon API", lambda: check_polygon()),
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
        # Only send success notification if requested via env var
        if os.environ.get("PREFLIGHT_NOTIFY_SUCCESS"):
            send_ntfy(
                "✅ Pre-Flight OK",
                "System ready for trading",
                priority="low",
                tags="white_check_mark",
            )
        return 0


def assert_true(val):
    if not val or not list(val):
        raise AssertionError("Empty or False")


def load_config():
    import yaml

    config = {}
    for f in Path("l2_scalping/config").glob("*.yaml"):
        with open(f) as fp:
            config.update(yaml.safe_load(fp) or {})
    if not config.get("ibkr"):
        raise AssertionError("Missing ibkr config")


def check_services():
    for svc in ["l2-collector", "l2-scalping", "l2-watchdog"]:
        result = subprocess.run(
            ["systemctl", "is-active", svc], capture_output=True, text=True
        )
        if result.stdout.strip() != "active":
            raise AssertionError(f"{svc} not active")


def check_polygon():
    import urllib.request

    url = "https://api.polygon.io/v2/aggs/ticker/AAPL/prev?apiKey=ZBxeJYOn0_e0UcPgEYLA90CQ9S28_EfU"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())
        if data.get("status") != "OK":
            raise AssertionError(f"Polygon error: {data}")


if __name__ == "__main__":
    sys.exit(main())
