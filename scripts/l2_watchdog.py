#!/usr/bin/env python3
"""
L2 Collector Watchdog - Real-time monitoring and auto-recovery.
Monitors logs, detects errors, and restarts service if needed.
"""

import re
import subprocess
import time
from datetime import datetime
from pathlib import Path


class L2Watchdog:
    """Monitor L2 collector and auto-recover from failures."""

    def __init__(self):
        self.service_name = "l2-collector.service"
        self.log_file = Path("logs/l2_watchdog.log")
        self.log_file.parent.mkdir(exist_ok=True)

        # Error patterns to detect
        self.fatal_patterns = [
            r"Connection refused",
            r"Connection reset",
            r"Disconnected unexpectedly",
            r"Failed to connect",
            r"API connection lost",
            r"Peer closed connection",  # Gateway crash
            r"Error 504",  # Gateway timeout
            r"Error 1100",  # Connectivity lost
            r"Error 2110",  # Connectivity restored (monitor)
        ]

        # Gateway crash indicators
        self.gateway_crash_patterns = [
            r"Error 317.*Market depth data has been RESET",
            r"Peer closed connection",
            r"Connection reset by peer",
            r"Socket connection broken",
        ]

        self.warning_patterns = [
            r"Error 10092",  # Deep market data not supported
            r"Error 200",  # No security definition
            r"Error 10167",  # Requested market data is not subscribed
        ]

        self.restart_count = 0
        self.last_restart = None
        self.max_restarts_per_hour = 5

    def check_gateway_crash(self) -> bool:
        """Check for gateway crash indicators in recent logs."""
        try:
            # Check last 50 lines of service logs
            result = subprocess.run(
                ["journalctl", "-u", self.service_name, "--lines=50", "--no-pager"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return False

            recent_logs = result.stdout

            # Check for gateway crash patterns
            for pattern in self.gateway_crash_patterns:
                if re.search(pattern, recent_logs, re.IGNORECASE):
                    self.log(f"Gateway crash detected: {pattern}", "ERROR")
                    return True

            return False

        except Exception as e:
            self.log(f"Error checking gateway crash: {e}", "WARNING")
            return False

    def check_data_flow(self) -> bool:
        """Check if L2 data is still flowing by examining recent file timestamps."""
        try:
            data_dir = Path("./data/l2_maximum/features")
            if not data_dir.exists():
                return False

            # Find most recent parquet file
            parquet_files = list(data_dir.rglob("*.parquet"))
            if not parquet_files:
                return False

            # Get most recent file
            latest_file = max(parquet_files, key=lambda p: p.stat().st_mtime)
            file_age = time.time() - latest_file.stat().st_mtime

            # If no new data in 10 minutes, consider it stale
            if file_age > 600:  # 10 minutes
                self.log(f"Data flow stale: latest file {file_age:.0f}s old", "WARNING")
                return False

            return True

        except Exception as e:
            self.log(f"Error checking data flow: {e}", "WARNING")
            return False

    def log(self, message: str, level: str = "INFO"):
        """Log to file and stdout."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_msg = f"[{timestamp}] [{level}] {message}"
        print(log_msg)
        with open(self.log_file, "a") as f:
            f.write(log_msg + "\n")

    def get_service_status(self) -> dict:
        """Get current service status."""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", self.service_name],
                capture_output=True,
                text=True,
                check=False,
            )
            is_active = result.stdout.strip() == "active"

            # Get main PID
            result = subprocess.run(
                ["systemctl", "show", self.service_name, "--property=MainPID"],
                capture_output=True,
                text=True,
                check=False,
            )
            pid = result.stdout.strip().split("=")[1]

            return {"active": is_active, "pid": pid}
        except Exception as e:
            self.log(f"Failed to get service status: {e}", "ERROR")
            return {"active": False, "pid": None}

    def get_recent_logs(self, lines: int = 50) -> str:
        """Get recent service logs."""
        try:
            result = subprocess.run(
                [
                    "journalctl",
                    "-u",
                    self.service_name,
                    "-n",
                    str(lines),
                    "--no-pager",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.stdout
        except Exception as e:
            self.log(f"Failed to get logs: {e}", "ERROR")
            return ""

    def check_for_errors(self, logs: str) -> dict:
        """Check logs for error patterns."""
        errors = {"fatal": [], "warning": []}

        for line in logs.split("\n"):
            # Check fatal errors
            for pattern in self.fatal_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    errors["fatal"].append(line)
                    break

            # Check warnings
            for pattern in self.warning_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    errors["warning"].append(line)
                    break

        return errors

    def restart_service(self) -> bool:
        """Restart the L2 collector service."""
        # Check restart rate limit
        now = time.time()
        if self.last_restart:
            time_since_last = now - self.last_restart
            if time_since_last < 3600:  # Within 1 hour
                if self.restart_count >= self.max_restarts_per_hour:
                    self.log(
                        f"Restart rate limit exceeded ({self.restart_count} restarts in last hour)",
                        "ERROR",
                    )
                    return False
            else:
                # Reset counter after 1 hour
                self.restart_count = 0

        self.log("Attempting to restart L2 collector service...", "WARNING")

        try:
            # Restart service
            subprocess.run(
                ["sudo", "systemctl", "restart", self.service_name],
                check=True,
                capture_output=True,
            )

            # Wait for service to start
            time.sleep(5)

            # Verify it started
            status = self.get_service_status()
            if status["active"]:
                self.restart_count += 1
                self.last_restart = now
                self.log(
                    f"Service restarted successfully (restart #{self.restart_count})",
                    "INFO",
                )
                return True
            else:
                self.log("Service restart failed - not active", "ERROR")
                return False

        except Exception as e:
            self.log(f"Failed to restart service: {e}", "ERROR")
            return False

    def monitor_loop(self, check_interval: int = 30):
        """Main monitoring loop."""
        self.log("L2 Watchdog started - monitoring every 30 seconds")
        self.log(f"Service: {self.service_name}")
        self.log(f"Max restarts per hour: {self.max_restarts_per_hour}")

        consecutive_errors = 0
        max_consecutive_errors = 3

        while True:
            try:
                # Check service status
                status = self.get_service_status()

                if not status["active"]:
                    self.log("Service is not active!", "ERROR")
                    if self.restart_service():
                        consecutive_errors = 0
                    else:
                        consecutive_errors += 1
                else:
                    # Service is active, check logs for errors
                    logs = self.get_recent_logs(lines=100)
                    errors = self.check_for_errors(logs)

                    if errors["fatal"]:
                        self.log(
                            f"Detected {len(errors['fatal'])} fatal errors",
                            "ERROR",
                        )
                        for error in errors["fatal"][-3:]:  # Show last 3
                            self.log(f"  {error}", "ERROR")

                        # Restart on fatal errors
                        if self.restart_service():
                            consecutive_errors = 0
                        else:
                            consecutive_errors += 1

                    elif errors["warning"]:
                        self.log(
                            f"Detected {len(errors['warning'])} warnings (non-fatal)",
                            "WARNING",
                        )
                        consecutive_errors = 0

                    else:
                        # All good
                        consecutive_errors = 0
                        if time.time() % 300 < check_interval:  # Log every 5 min
                            self.log(
                                f"Service healthy (PID: {status['pid']})",
                                "INFO",
                            )

                # Check if we're stuck in error loop
                if consecutive_errors >= max_consecutive_errors:
                    self.log(
                        f"Too many consecutive errors ({consecutive_errors}), "
                        "stopping watchdog to prevent infinite restart loop",
                        "ERROR",
                    )
                    break

                time.sleep(check_interval)

            except KeyboardInterrupt:
                self.log("Watchdog stopped by user", "INFO")
                break
            except Exception as e:
                self.log(f"Watchdog error: {e}", "ERROR")
                time.sleep(check_interval)


def main():
    """Run the watchdog."""
    watchdog = L2Watchdog()
    watchdog.monitor_loop(check_interval=30)


if __name__ == "__main__":
    main()
