#!/usr/bin/env python3
"""L2 Scalping Health Monitor - Auto-recovery for zombie depth subscriptions."""

import subprocess
import sys
import time
from datetime import datetime

import pytz

MONITOR_INTERVAL = 60  # Check every 60 seconds
MAX_RECOVERY_ATTEMPTS = 3
RECOVERY_COOLDOWN = 300  # 5 minutes between recovery attempts


def log(msg: str) -> None:
    """Log with timestamp."""
    et_tz = pytz.timezone("America/New_York")
    timestamp = datetime.now(et_tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"[{timestamp}] {msg}", flush=True)


def check_l2_health() -> tuple[bool, str]:
    """Check L2 scalping health from journalctl.
    
    Returns:
        (is_healthy, reason)
    """
    try:
        # Get last 5 system health messages
        result = subprocess.run(
            [
                "journalctl",
                "-u",
                "l2-scalping",
                "-n",
                "100",
                "--no-pager",
                "--since",
                "5 minutes ago",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )

        logs = result.stdout

        # Check for Error 309 (max depth reached)
        if "Error 309" in logs and "market depth requests has been reached" in logs:
            return False, "Error 309: Max depth subscriptions reached (zombie connections)"

        # Check for Data: False in recent health checks
        health_lines = [line for line in logs.split("\n") if "System Health" in line]
        if health_lines:
            last_health = health_lines[-1]
            if "Data: False" in last_health or "Fresh: 0/3" in last_health:
                return False, "No L2 data flowing (Data: False or Fresh: 0/3)"

        # Check for client ID conflicts
        if "Error 326" in logs and "client id is already in use" in logs:
            return False, "Error 326: Client ID conflict"

        return True, "OK"

    except Exception as e:
        log(f"Error checking health: {e}")
        return True, "Health check failed (assuming healthy)"


def recover_l2_scalping() -> bool:
    """Recover L2 scalping by clearing subscriptions and restarting.
    
    Returns:
        True if recovery successful
    """
    try:
        log("Starting recovery procedure...")

        # Stop l2-scalping
        log("Stopping l2-scalping service...")
        subprocess.run(
            ["sudo", "systemctl", "stop", "l2-scalping"],
            check=True,
            timeout=30,
        )
        time.sleep(2)

        # Clear zombie subscriptions
        log("Clearing zombie depth subscriptions...")
        subprocess.run(
            ["python3", "/home/jacobw/quantstack/scripts/clear_ibkr_depth_subscriptions.py"],
            check=True,
            timeout=30,
        )
        time.sleep(2)

        # Restart l2-scalping
        log("Restarting l2-scalping service...")
        subprocess.run(
            ["sudo", "systemctl", "start", "l2-scalping"],
            check=True,
            timeout=30,
        )

        # Wait for service to stabilize
        time.sleep(10)

        # Verify recovery
        is_healthy, reason = check_l2_health()
        if is_healthy:
            log("Recovery successful!")
            return True
        else:
            log(f"Recovery failed: {reason}")
            return False

    except subprocess.TimeoutExpired:
        log("Recovery timed out")
        return False
    except subprocess.CalledProcessError as e:
        log(f"Recovery command failed: {e}")
        return False
    except Exception as e:
        log(f"Recovery error: {e}")
        return False


def main():
    """Main monitoring loop."""
    log("L2 Scalping Health Monitor started")
    log(f"Check interval: {MONITOR_INTERVAL}s")
    log(f"Max recovery attempts: {MAX_RECOVERY_ATTEMPTS}")

    recovery_count = 0
    last_recovery_time = 0

    while True:
        try:
            # Check health
            is_healthy, reason = check_l2_health()

            if not is_healthy:
                log(f"UNHEALTHY: {reason}")

                # Check cooldown
                time_since_recovery = time.time() - last_recovery_time
                if time_since_recovery < RECOVERY_COOLDOWN:
                    log(f"Recovery cooldown active ({RECOVERY_COOLDOWN - time_since_recovery:.0f}s remaining)")
                    time.sleep(MONITOR_INTERVAL)
                    continue

                # Check max attempts
                if recovery_count >= MAX_RECOVERY_ATTEMPTS:
                    log(f"Max recovery attempts ({MAX_RECOVERY_ATTEMPTS}) reached - manual intervention required")
                    time.sleep(MONITOR_INTERVAL)
                    continue

                # Attempt recovery
                recovery_count += 1
                log(f"Attempting recovery ({recovery_count}/{MAX_RECOVERY_ATTEMPTS})...")

                if recover_l2_scalping():
                    last_recovery_time = time.time()
                    log("Recovery completed successfully")
                else:
                    log("Recovery failed")

            else:
                # Reset recovery count on sustained health
                if recovery_count > 0:
                    log(f"System healthy - resetting recovery count (was {recovery_count})")
                    recovery_count = 0

            time.sleep(MONITOR_INTERVAL)

        except KeyboardInterrupt:
            log("Monitor stopped by user")
            sys.exit(0)
        except Exception as e:
            log(f"Monitor error: {e}")
            time.sleep(MONITOR_INTERVAL)


if __name__ == "__main__":
    main()
