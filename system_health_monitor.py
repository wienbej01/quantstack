#!/usr/bin/env python3
"""
System Health Monitor - Resilient Version

Features:
- Market hours + pre-market monitoring
- Gateway health checks with API validation
- Service failure detection
- CRITICAL error detection in logs
- Robust NTFY notifications (encoding-safe)
- Fallback logging when NTFY fails
"""

import json
import logging
import os
import socket
import subprocess
import sys
from datetime import datetime, time
from pathlib import Path

import pytz

os.environ["TZ"] = "America/New_York"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

# Extended monitoring window (pre-market + market hours)
MONITOR_START = time(8, 0)  # Start monitoring at 08:00 ET
MONITOR_END = time(16, 30)  # End at 16:30 ET

# Critical services to monitor
CRITICAL_SERVICES = ["ibkr-gateway", "l2-collector", "l2-scalping", "intraday-paper"]
TRADING_SERVICES = ["l2-collector", "l2-scalping", "intraday-paper"]

# NTFY channels
NTFY_ALERTS = "https://ntfy.sh/jacobw-trading-alerts"
NTFY_STATUS = "https://ntfy.sh/jacobw-trading-status"


def is_monitoring_hours() -> bool:
    """Check if within monitoring hours (ET)."""
    now = datetime.now(ET)
    if now.weekday() > 4:  # Weekend
        return False
    return MONITOR_START <= now.time() <= MONITOR_END


def send_ntfy(
    channel: str,
    title: str,
    message: str,
    priority: str = "high",
    tags: str = "warning",
) -> bool:
    """Send NTFY notification with robust encoding handling."""
    import urllib.error
    import urllib.request

    try:
        # Sanitize message - remove emojis and non-ASCII for headers
        safe_title = title.encode("ascii", "replace").decode("ascii")

        # Message body can have UTF-8
        msg_bytes = message.encode("utf-8")

        req = urllib.request.Request(
            channel,
            data=msg_bytes,
            headers={
                "Title": safe_title,
                "Priority": priority,
                "Tags": tags,
                "Content-Type": "text/plain; charset=utf-8",
            },
        )
        urllib.request.urlopen(req, timeout=10)
        logger.info(f"NTFY sent: {safe_title}")
        return True
    except urllib.error.URLError as e:
        logger.error(f"NTFY network error: {e}")
        return False
    except Exception as e:
        logger.error(f"NTFY failed: {e}")
        return False


def send_alert(title: str, message: str, priority: str = "high") -> bool:
    """Send alert with fallback logging."""
    success = send_ntfy(NTFY_ALERTS, title, message, priority, "warning")
    if not success:
        # Fallback: log to file for later review
        fallback_log = Path("/home/jacobw/quantstack/logs/alert_fallback.log")
        fallback_log.parent.mkdir(exist_ok=True)
        with open(fallback_log, "a") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"TIME: {datetime.now(ET)}\n")
            f.write(f"TITLE: {title}\n")
            f.write(f"MESSAGE: {message}\n")
        logger.warning(f"Alert logged to fallback: {fallback_log}")
    return success


def check_service(name: str) -> tuple[bool, str]:
    """Check if service is active."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", name], capture_output=True, text=True, timeout=5
        )
        status = result.stdout.strip()
        return status == "active", status
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def check_gateway_port() -> bool:
    """Check if Gateway port is listening."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(("127.0.0.1", 7497))
        sock.close()
        return result == 0
    except:
        return False


def check_gateway_api() -> tuple[bool, str]:
    """Check if Gateway API is responsive (not just port)."""
    # First check port
    if not check_gateway_port():
        return False, "port not listening"

    # Check service status
    active, status = check_service("ibkr-gateway")
    if not active:
        return False, f"service {status}"

    # Check for recent connection errors in logs
    try:
        result = subprocess.run(
            [
                "journalctl",
                "-u",
                "ibkr-gateway",
                "--since",
                "2 minutes ago",
                "--no-pager",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if "API connection failed" in result.stdout or "TimeoutError" in result.stdout:
            return False, "API connection errors"
    except:
        pass

    return True, "healthy"


def check_service_errors(service: str, minutes: int = 5) -> list[str]:
    """Check for critical errors in service logs."""
    issues = []
    try:
        result = subprocess.run(
            [
                "journalctl",
                "-u",
                service,
                "--since",
                f"{minutes} minutes ago",
                "--no-pager",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        log = result.stdout

        # Check for critical patterns
        critical_patterns = [
            ("CRITICAL", "CRITICAL error"),
            ("Failed to connect", "connection failure"),
            ("API connection failed", "API failure"),
            ("TimeoutError", "timeout"),
            ("exit-code", "service crashed"),
        ]

        for pattern, desc in critical_patterns:
            if pattern in log:
                issues.append(f"{service}: {desc}")

    except subprocess.TimeoutExpired:
        issues.append(f"{service}: log check timeout")
    except Exception as e:
        logger.warning(f"Error checking {service} logs: {e}")

    return issues


def main():
    now = datetime.now(ET)

    # Skip if outside monitoring hours
    if not is_monitoring_hours():
        logger.info("Outside monitoring hours - skipping")
        return 0

    logger.info(f"Health check at {now.strftime('%H:%M ET')}")

    issues = []
    critical_issues = []

    # 1. Check Gateway (most critical)
    gw_ok, gw_status = check_gateway_api()
    if not gw_ok:
        critical_issues.append(f"GATEWAY DOWN: {gw_status}")
        logger.error(f"Gateway issue: {gw_status}")

    # 2. Check trading services (only during market hours 09:25+)
    market_time = now.time() >= time(9, 25)
    if market_time:
        for svc in TRADING_SERVICES:
            active, status = check_service(svc)
            if not active:
                issues.append(f"{svc}: {status}")
                logger.error(f"{svc} not active: {status}")

    # 3. Check for critical errors in logs
    for svc in CRITICAL_SERVICES:
        errors = check_service_errors(svc, minutes=5)
        for err in errors:
            if "CRITICAL" in err or "crashed" in err:
                critical_issues.append(err)
            else:
                issues.append(err)

    # 4. Send alerts based on severity
    if critical_issues:
        msg = f"CRITICAL at {now.strftime('%H:%M ET')}:\n" + "\n".join(critical_issues)
        if issues:
            msg += f"\n\nOther issues:\n" + "\n".join(issues)
        send_alert("CRITICAL: Trading System Failure", msg, priority="urgent")
        logger.error(f"CRITICAL alert sent: {len(critical_issues)} issues")
        return 2

    if issues:
        msg = f"Issues at {now.strftime('%H:%M ET')}:\n" + "\n".join(issues)
        send_alert("Warning: Trading System Issues", msg, priority="high")
        logger.warning(f"Warning alert sent: {len(issues)} issues")
        return 1

    logger.info("All systems healthy")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Last resort - try to send alert about monitor failure
        logger.critical(f"Health monitor crashed: {e}")
        try:
            send_alert("CRITICAL: Health Monitor Crashed", str(e), priority="urgent")
        except:
            pass
        sys.exit(3)
