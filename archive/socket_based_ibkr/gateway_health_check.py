#!/usr/bin/env python3
"""
IBKR Gateway API Health Check

Proactively checks if Gateway API is responsive and restarts if needed.
Runs every 2 minutes during market hours.
"""

import os
import socket
import subprocess
import sys
from datetime import datetime, time

import pytz

ET = pytz.timezone("America/New_York")

MARKET_START = time(9, 20)
MARKET_END = time(16, 10)


def is_market_hours():
    now = datetime.now(ET)
    if now.weekday() > 4:
        return False
    return MARKET_START <= now.time() <= MARKET_END


def check_port():
    """Check if port 7497 is listening."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(("127.0.0.1", 7497))
        sock.close()
        return result == 0
    except:
        return False


def check_api_responsive():
    """Try actual API connection with timeout."""
    try:
        result = subprocess.run(
            [
                "/home/jacobw/intraday_stack/.venv/bin/python",
                "-c",
                """
import sys
sys.path.insert(0, '/home/jacobw/intraday_stack/src')
from ib_insync import IB
ib = IB()
ib.connect('127.0.0.1', 7497, clientId=997, timeout=10)
ib.disconnect()
print('OK')
""",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return "OK" in result.stdout
    except:
        return False


def send_alert(msg):
    """Send NTFY alert."""
    try:
        subprocess.run(
            [
                "curl",
                "-s",
                "-X",
                "POST",
                "https://ntfy.sh/jacobw-trading-alerts",
                "-H",
                "Title: Gateway Health Check",
                "-H",
                "Priority: high",
                "-d",
                msg,
            ],
            timeout=10,
        )
    except:
        pass


def restart_gateway():
    """Restart Gateway service."""
    subprocess.run(["sudo", "systemctl", "restart", "ibkr-gateway"], timeout=60)


def main():
    if not is_market_hours():
        print("Outside market hours")
        return 0

    now = datetime.now().strftime("%H:%M ET")

    # Check 1: Port listening
    if not check_port():
        print(f"{now}: Port 7497 not listening - restarting Gateway")
        send_alert(f"Gateway port down at {now} - restarting")
        restart_gateway()
        return 1

    # Check 2: API responsive
    if not check_api_responsive():
        print(f"{now}: Gateway API unresponsive - restarting")
        send_alert(f"Gateway API frozen at {now} - restarting")
        restart_gateway()
        return 1

    print(f"{now}: Gateway healthy")
    return 0


if __name__ == "__main__":
    sys.exit(main())
