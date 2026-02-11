#!/usr/bin/env python3
"""
Enhanced Gateway Health Monitor with Recovery Notifications

Monitors:
- IBKR Gateway health and authentication
- Service status and recovery (only during scheduled hours)
- Connection re-establishment after outages
- Distinguishes between scheduled startup and recovery from failure
"""

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, time

import requests

# Set timezone BEFORE any datetime operations
os.environ["TZ"] = "America/New_York"
import time as time_module

time_module.tzset()

from qx_broker.ibkr import IBKRConnectionConfig, IBKRSession, IBKRSessionConfig

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Monitoring window (ET)
MONITOR_START = time(7, 0)  # 07:00 ET
MONITOR_END = time(16, 30)  # 16:30 ET

# Startup window: services starting within this window after scheduled start time
# are considered "starting" not "recovering"
STARTUP_WINDOW_MINUTES = 5

# Services to monitor with their expected active hours (ET)
SERVICE_SCHEDULES = {
    "ibkr-gateway": {"start": time(6, 0), "end": time(23, 59)},  # Always running
    "l2-collector": {"start": time(9, 26), "end": time(16, 0)},
    "l2-scalping": {"start": time(9, 26), "end": time(16, 1)},
    "intraday-paper": {"start": time(9, 28), "end": time(16, 2)},
}

# NTFY channels
NTFY_ALERTS = "https://ntfy.sh/jacobw-trading-alerts"
NTFY_STATUS = "https://ntfy.sh/jacobw-trading-status"


def load_state() -> dict:
    """Load previous state."""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {"platform_healthy": True, "services": {}, "last_check": None}


def save_state(state: dict):
    """Save current state."""
    try:
        state["last_check"] = datetime.now().isoformat()
        with open(STATE_FILE, "w") as f:
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


def is_within_startup_window(service: str, current_time: time) -> bool:
    """Check if current time is within the startup window for a service."""
    schedule = SERVICE_SCHEDULES.get(service)
    if not schedule:
        return False

    # Calculate seconds since scheduled start time
    start_seconds = schedule["start"].hour * 3600 + schedule["start"].minute * 60
    current_seconds = (
        current_time.hour * 3600 + current_time.minute * 60 + current_time.second
    )

    diff_seconds = current_seconds - start_seconds
    return 0 <= diff_seconds <= (STARTUP_WINDOW_MINUTES * 60)


def check_gateway_health() -> dict:
    """Check IBKR Gateway health and account availability."""
    host = os.environ.get("IBKR_GATEWAY_HOST", "127.0.0.1")
    port = int(os.environ.get("IBKR_GATEWAY_PORT", "7494"))
    client_id = int(os.environ.get("IBKR_HEALTH_CLIENT_ID", "998"))

    connection = IBKRConnectionConfig(
        host=host,
        port=port,
        client_id=client_id,
        readonly=True,
        connect_timeout=5,
        request_timeout=5,
        reconnect_attempts=0,
        allow_client_id_fallback=False,
    )
    session_cfg = IBKRSessionConfig(system_name="HEALTH_MONITOR", connection=connection)
    session = IBKRSession(session_cfg)

    try:
        if not session.connect():
            return {"status": "unreachable", "error": "Cannot connect to gateway"}

        current_time_ok = session.check_connection()
        accounts = session.call(session.ib.managedAccounts, timeout=5) or []
        accounts_available = len(accounts) > 0

        status = "healthy" if current_time_ok else "error"
        return {
            "status": status,
            "current_time_ok": current_time_ok,
            "accounts_available": accounts_available,
            "account_count": len(accounts),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
    finally:
        session.disconnect()


def check_service_status(service: str) -> bool:
    """Check if systemd service is active."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def send_ntfy(
    channel: str, title: str, message: str, priority: int = 3, tags: str = "info"
):
    """Send NTFY notification with UTF-8 encoding."""
    try:
        requests.post(
            channel,
            data=message.encode("utf-8"),
            headers={
                "Title": title.encode("utf-8").decode("utf-8"),
                "Priority": str(priority),
                "Tags": tags,
                "Content-Type": "text/plain; charset=utf-8",
            },
            timeout=10,
        )
        logger.info(f"NTFY sent to {channel.split('/')[-1]}: {title}")
    except Exception as e:
        logger.error(f"NTFY failed: {e}")


def main():
    """Main health check with startup vs recovery detection."""
    STATE_FILE = "/tmp/platform_health_state.json"

    if not is_monitoring_hours():
        logger.info("Outside monitoring hours - skipping")
        return 0

    now = datetime.now()
    now_et = now.strftime("%H:%M:%S ET")
    current_time = now.time()
    prev_state = load_state()
    current_state = {"platform_healthy": True, "services": {}}

    issues = []
    startups = []
    recoveries = []

    # Check gateway health
    health = check_gateway_health()
    gateway_healthy = (
        health.get("status") == "healthy"
        and health.get("current_time_ok")
        and health.get("accounts_available", False)
    )
    current_state["platform_healthy"] = gateway_healthy

    if not gateway_healthy:
        if health.get("status") == "unreachable":
            issues.append("🔴 Gateway unreachable - service may be down")
        elif not health.get("current_time_ok"):
            issues.append("🔑 Gateway API timeout - Retrying")
        elif not health.get("accounts_available"):
            issues.append(
                "💳 No IBKR accounts available - check Gateway authentication"
            )
        else:
            issues.append(f"⚠️ Gateway unhealthy: {health}")
    elif not prev_state.get("platform_healthy", True):
        # Gateway recovered - check if this is startup or recovery
        # Gateway should always be running, so if it was down it's a recovery
        recoveries.append("✅ Gateway Reconnected and authenticated")

    # Check services (only if within their scheduled hours)
    for service, schedule in SERVICE_SCHEDULES.items():
        service_active = check_service_status(service)
        current_state["services"][service] = service_active
        prev_active = prev_state.get("services", {}).get(service, True)
        should_be_running = schedule["start"] <= current_time <= schedule["end"]

        if not service_active and should_be_running:
            issues.append(f"🔴 Service down: {service}")
        elif service_active and not should_be_running:
            # Service running outside scheduled hours - warning only
            logger.warning(f"{service} running outside scheduled hours")
        elif service_active and not prev_active and should_be_running:
            # Service transitioned from inactive to active
            # Distinguish between scheduled startup and recovery
            if is_within_startup_window(service, current_time):
                # This is expected startup
                startups.append(f"✅ {service} Starting")
            else:
                # This is recovery from unexpected failure
                recoveries.append(f"✅ {service} Recovered")

    # Send notifications
    if issues:
        message = f"Time: {now_et}\n\n" + "\n".join(issues)

        # Critical gateway issues get max priority
        if not gateway_healthy:
            send_ntfy(
                NTFY_ALERTS,
                "🚨 CRITICAL: IBKR Gateway Down",
                message,
                priority=5,
                tags="rotating_light",
            )
        else:
            send_ntfy(
                NTFY_ALERTS, "Trading System Alert", message, priority=4, tags="warning"
            )

        logger.warning(f"Issues found: {issues}")

    # Send startup notifications
    if startups:
        message = f"Time: {now_et}\n\n" + "\n".join(startups)
        for service_msg in startups:
            service_name = service_msg.split()[1]  # Extract service name
            send_ntfy(
                NTFY_STATUS,
                f"{service_name} Starting",
                f"Time: {now_et}\n\n{service_name} is starting for the trading session",
                priority=3,
                tags="white_check_mark",
            )
        logger.info(f"Startups detected: {startups}")

    # Send recovery notifications
    if recoveries:
        message = f"Time: {now_et}\n\n" + "\n".join(recoveries)
        for recovery_msg in recoveries:
            if "Gateway" in recovery_msg:
                send_ntfy(
                    NTFY_ALERTS,
                    "Gateway Reconnected",
                    f"Time: {now_et}\n\n{recovery_msg}",
                    priority=4,
                    tags="warning",
                )
            else:
                service_name = recovery_msg.split()[1]  # Extract service name
                send_ntfy(
                    NTFY_STATUS,
                    f"{service_name} Recovered",
                    f"Time: {now_et}\n\n{service_name} has recovered from unexpected failure",
                    priority=4,
                    tags="rotating_light",
                )
        logger.info(f"Recoveries detected: {recoveries}")

    if not issues and not startups and not recoveries:
        logger.info("All systems healthy")

    # Save current state
    save_state(current_state)

    return 0


if __name__ == "__main__":
    sys.exit(main())
