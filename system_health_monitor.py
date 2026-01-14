#!/usr/bin/env python3
"""
Enhanced Platform Health Monitor with Recovery Notifications

Monitors:
- IBKR API Platform health and authentication
- Service status and recovery
- Connection re-establishment after outages
- Comprehensive NTFY alerts
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, time

import requests

os.environ["TZ"] = "America/New_York"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Monitoring window (ET)
MONITOR_START = time(7, 0)   # 07:00 ET
MONITOR_END = time(16, 30)   # 16:30 ET

# Services to monitor
CRITICAL_SERVICES = ["ibkr-platform", "l2-collector", "l2-scalping"]

# NTFY channels
NTFY_ALERTS = "https://ntfy.sh/jacobw-trading-alerts"
NTFY_STATUS = "https://ntfy.sh/jacobw-trading-status"

# State file for tracking recovery
STATE_FILE = "/tmp/platform_health_state.json"


def load_state() -> dict:
    """Load previous state."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"platform_healthy": True, "services": {}}


def save_state(state: dict):
    """Save current state."""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception as e:
        logger.error(f"Failed to save state: {e}")


def is_monitoring_hours() -> bool:
    """Check if within monitoring hours (ET)."""
    now = datetime.now()
    current_time = now.time()
    # Skip weekends
    if now.weekday() >= 5:
        return False
    return MONITOR_START <= current_time <= MONITOR_END


def check_platform_health() -> dict:
    """Check IBKR API Platform health and account availability."""
    try:
        # Check platform health
        resp = requests.get("http://127.0.0.1:8000/health", timeout=5)
        if resp.status_code != 200:
            return {"status": "error", "http_code": resp.status_code}
        
        health = resp.json()
        
        # Check accounts availability
        accounts_resp = requests.get("http://127.0.0.1:8000/api/accounts", timeout=5)
        if accounts_resp.status_code == 200:
            accounts_data = accounts_resp.json()
            health["accounts_available"] = len(accounts_data.get("accounts", [])) > 0
            health["account_count"] = len(accounts_data.get("accounts", []))
        else:
            health["accounts_available"] = False
            health["account_count"] = 0
            
        return health
    except requests.exceptions.ConnectionError:
        return {"status": "unreachable", "error": "Cannot connect to platform"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def check_service_status(service: str) -> bool:
    """Check if systemd service is active."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def send_ntfy(channel: str, title: str, message: str, priority: int = 3, tags: str = "info"):
    """Send NTFY notification."""
    try:
        requests.post(
            channel,
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": str(priority),
                "Tags": tags
            },
            timeout=10
        )
        logger.info(f"NTFY sent to {channel.split('/')[-1]}: {title}")
    except Exception as e:
        logger.error(f"NTFY failed: {e}")


def main():
    """Main health check with recovery detection."""
    if not is_monitoring_hours():
        logger.info("Outside monitoring hours - skipping")
        return 0

    now_et = datetime.now().strftime("%H:%M ET")
    prev_state = load_state()
    current_state = {"platform_healthy": True, "services": {}}
    
    issues = []
    recoveries = []

    # Check platform health
    health = check_platform_health()
    platform_healthy = (health.get("status") == "healthy" and 
                        health.get("authenticated") and 
                        health.get("accounts_available", False))
    current_state["platform_healthy"] = platform_healthy
    
    if not platform_healthy:
        if health.get("status") == "unreachable":
            issues.append("🔴 Platform unreachable - service may be down")
        elif not health.get("authenticated"):
            issues.append("🔑 Platform not authenticated - login required at https://localhost:5000")
        elif not health.get("accounts_available"):
            issues.append(f"💳 No IBKR accounts available - check Client Portal Gateway")
        else:
            issues.append(f"⚠️ Platform unhealthy: {health}")
    elif not prev_state.get("platform_healthy", True):
        # Platform recovered
        recoveries.append("✅ Platform recovered and authenticated with accounts")

    # Check services
    for service in CRITICAL_SERVICES:
        service_active = check_service_status(service)
        current_state["services"][service] = service_active
        
        if not service_active:
            issues.append(f"🔴 Service down: {service}")
        elif not prev_state.get("services", {}).get(service, True):
            # Service recovered
            recoveries.append(f"✅ Service recovered: {service}")

    # Send notifications
    if issues:
        message = f"Time: {now_et}\n\n" + "\n".join(issues)
        
        # Critical platform issues get max priority
        if not platform_healthy:
            send_ntfy(NTFY_ALERTS, "🚨 CRITICAL: IBKR Platform Down", message, priority=5, tags="rotating_light")
        else:
            send_ntfy(NTFY_ALERTS, "Trading System Alert", message, priority=4, tags="warning")
        
        logger.warning(f"Issues found: {issues}")
    
    if recoveries:
        message = f"Time: {now_et}\n\n" + "\n".join(recoveries)
        send_ntfy(NTFY_STATUS, "System Recovery", message, priority=3, tags="white_check_mark")
        logger.info(f"Recoveries detected: {recoveries}")
    
    if not issues and not recoveries:
        logger.info("All systems healthy")

    # Save current state
    save_state(current_state)
    
    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
