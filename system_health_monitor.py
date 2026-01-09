#!/usr/bin/env python3
"""
System Health Monitor - Market Hours Only

Only runs during US market hours and only sends alerts for:
1. Service failures
2. Error spikes in logs
3. Gateway disconnections

NO routine "all healthy" spam.
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, time
from pathlib import Path

import pytz

# Set timezone
os.environ['TZ'] = 'America/New_York'

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

ET = pytz.timezone('America/New_York')

# Market hours (ET)
MARKET_OPEN = time(9, 25)   # 5 min before open
MARKET_CLOSE = time(16, 5)  # 5 min after close


def is_market_hours() -> bool:
    """Check if within market hours (ET)."""
    now = datetime.now(ET)
    # Weekday check (Mon=0, Fri=4)
    if now.weekday() > 4:
        return False
    return MARKET_OPEN <= now.time() <= MARKET_CLOSE


def send_alert(title: str, message: str, priority: str = "high"):
    """Send NTFY alert - alerts channel only."""
    import urllib.request
    try:
        req = urllib.request.Request(
            "https://ntfy.sh/jacobw-trading-alerts",
            data=message.encode(),
            headers={"Title": title, "Priority": priority, "Tags": "warning"}
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info(f"Alert sent: {title}")
    except Exception as e:
        logger.error(f"Failed to send alert: {e}")


def check_service(name: str) -> tuple[bool, str]:
    """Check if service is active."""
    result = subprocess.run(
        ['systemctl', 'is-active', name],
        capture_output=True, text=True
    )
    status = result.stdout.strip()
    return status == 'active', status


def check_recent_errors(service: str, minutes: int = 5) -> int:
    """Count errors in recent logs."""
    result = subprocess.run(
        ['journalctl', '-u', service, '--since', f'{minutes} minutes ago', '--no-pager'],
        capture_output=True, text=True
    )
    error_count = result.stdout.lower().count('error')
    return error_count


def check_gateway() -> bool:
    """Check if IBKR Gateway is accessible."""
    import socket
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(('127.0.0.1', 7497))
        sock.close()
        return result == 0
    except:
        return False


def main():
    # Skip if outside market hours
    if not is_market_hours():
        logger.info("Outside market hours - skipping health check")
        return 0
    
    now = datetime.now(ET)
    logger.info(f"Health check at {now.strftime('%H:%M ET')}")
    
    issues = []
    
    # Check critical services
    services = ['l2-collector', 'l2-scalping', 'l2-watchdog']
    for svc in services:
        active, status = check_service(svc)
        if not active:
            issues.append(f"🔴 {svc}: {status}")
            logger.error(f"{svc} not active: {status}")
    
    # Check for error spikes (only if services running)
    if not issues:
        for svc in ['l2-scalping', 'l2-collector']:
            errors = check_recent_errors(svc, minutes=5)
            if errors > 10:  # Threshold for "spike"
                issues.append(f"⚠️ {svc}: {errors} errors in 5min")
                logger.warning(f"{svc} error spike: {errors}")
    
    # Check gateway during market hours
    if MARKET_OPEN <= now.time() <= MARKET_CLOSE:
        if not check_gateway():
            issues.append("🔴 IBKR Gateway: not accessible")
            logger.error("IBKR Gateway not accessible")
    
    # Only send alert if there are issues
    if issues:
        msg = f"Health check {now.strftime('%H:%M ET')}:\n" + "\n".join(issues)
        send_alert("⚠️ System Issues Detected", msg, priority="high")
        return 1
    
    logger.info("All systems healthy - no alert needed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
