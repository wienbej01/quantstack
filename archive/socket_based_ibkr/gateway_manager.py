#!/usr/bin/env python3
"""
IBKR Gateway Manager - Robust Background Daemon

Responsibilities:
- Start Gateway before market (08:30 ET)
- Monitor health during market hours
- Reset Gateway on critical errors
- Restart dependent services after Gateway reset
- Stop Gateway after market (16:30 ET)
- Send NTFY alerts for all events
"""

import logging
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from datetime import time as dtime
from enum import Enum
from typing import Optional

import pytz

# Configuration
ET = pytz.timezone("America/New_York")
GATEWAY_PORT = 7497
GATEWAY_HOST = "127.0.0.1"

# Schedule (ET)
GATEWAY_START_TIME = dtime(8, 30)  # Start Gateway
MARKET_OPEN_TIME = dtime(9, 25)  # Services start
MARKET_CLOSE_TIME = dtime(16, 5)  # Services stop
GATEWAY_STOP_TIME = dtime(16, 30)  # Stop Gateway

# Health check intervals
HEALTH_CHECK_INTERVAL = 60  # seconds during market hours
PRE_MARKET_CHECK_INTERVAL = 120  # seconds before market
POST_MARKET_CHECK_INTERVAL = 300  # seconds after market

# Thresholds
MAX_CONSECUTIVE_FAILURES = 3
API_TIMEOUT = 15

# NTFY
NTFY_ALERTS = "https://ntfy.sh/jacobw-trading-alerts"
NTFY_STATUS = "https://ntfy.sh/jacobw-trading-status"

# Dependent services
TRADING_SERVICES = ["l2-collector", "l2-scalping", "intraday-paper"]

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/home/jacobw/quantstack/logs/gateway_manager.log"),
    ],
)
logger = logging.getLogger("gateway-manager")


class GatewayState(Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    UNHEALTHY = "unhealthy"
    STOPPING = "stopping"


class GatewayManager:
    def __init__(self):
        self.state = GatewayState.STOPPED
        self.consecutive_failures = 0
        self.last_health_check = None
        self.running = True
        self.gateway_started_today = False
        self.last_reset_time = None

        # Signal handlers
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        logger.info("Gateway Manager initialized")

    def _handle_signal(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def send_ntfy(
        self,
        channel: str,
        title: str,
        message: str,
        priority: str = "default",
        tags: str = "",
    ):
        """Send NTFY notification."""
        try:
            cmd = [
                "curl",
                "-s",
                "-X",
                "POST",
                channel,
                "-H",
                f"Title: {title}",
                "-H",
                f"Priority: {priority}",
            ]
            if tags:
                cmd.extend(["-H", f"Tags: {tags}"])
            cmd.extend(["-d", message])

            subprocess.run(cmd, timeout=10, capture_output=True)
            logger.info(f"NTFY sent: {title}")
        except Exception as e:
            logger.error(f"NTFY failed: {e}")

    def alert(self, title: str, message: str, priority: str = "high"):
        """Send alert notification."""
        self.send_ntfy(NTFY_ALERTS, title, message, priority, "warning")

    def status(self, title: str, message: str):
        """Send status notification."""
        self.send_ntfy(NTFY_STATUS, title, message, "default", "white_check_mark")

    def get_et_now(self) -> datetime:
        """Get current time in ET."""
        return datetime.now(ET)

    def is_weekday(self) -> bool:
        """Check if today is a weekday."""
        return self.get_et_now().weekday() < 5

    def should_gateway_be_running(self) -> bool:
        """Check if Gateway should be running based on schedule."""
        if not self.is_weekday():
            return False
        now = self.get_et_now().time()
        return GATEWAY_START_TIME <= now <= GATEWAY_STOP_TIME

    def is_market_hours(self) -> bool:
        """Check if within market hours."""
        if not self.is_weekday():
            return False
        now = self.get_et_now().time()
        return MARKET_OPEN_TIME <= now <= MARKET_CLOSE_TIME

    def check_port_listening(self) -> bool:
        """Check if Gateway port is listening."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((GATEWAY_HOST, GATEWAY_PORT))
            sock.close()
            return result == 0
        except Exception:
            return False

    def check_gateway_service(self) -> bool:
        """Check if Gateway systemd service is active."""
        try:
            result = subprocess.run(
                ["systemctl", "is-active", "ibkr-gateway"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip() == "active"
        except Exception:
            return False

    def check_api_responsive(self) -> bool:
        """Check if Gateway API is actually responsive."""
        try:
            # Use a simple connection test with ib_insync
            result = subprocess.run(
                [
                    "/home/jacobw/quantstack/.venv/bin/python",
                    "-c",
                    f"""
import sys
from ib_insync import IB
ib = IB()
try:
    ib.connect('{GATEWAY_HOST}', {GATEWAY_PORT}, clientId=999, timeout={API_TIMEOUT})
    ib.disconnect()
    print('OK')
except:
    print('FAIL')
""",
                ],
                capture_output=True,
                text=True,
                timeout=API_TIMEOUT + 5,
            )
            return "OK" in result.stdout
        except Exception as e:
            logger.debug(f"API check failed: {e}")
            return False

    def health_check(self) -> bool:
        """Perform comprehensive health check."""
        # Check 1: Service running
        if not self.check_gateway_service():
            logger.warning("Gateway service not active")
            return False

        # Check 2: Port listening
        if not self.check_port_listening():
            logger.warning("Gateway port not listening")
            return False

        # Check 3: API responsive (only during market hours to avoid unnecessary load)
        if self.is_market_hours():
            if not self.check_api_responsive():
                logger.warning("Gateway API not responsive")
                return False

        return True

    def start_gateway(self) -> bool:
        """Start the Gateway service."""
        logger.info("Starting Gateway...")
        self.state = GatewayState.STARTING

        try:
            # Ensure Xvfb is running first
            subprocess.run(["sudo", "systemctl", "start", "xvfb"], timeout=10)
            time.sleep(2)

            # Start Gateway
            subprocess.run(["sudo", "systemctl", "start", "ibkr-gateway"], timeout=30)

            # Wait for Gateway to be ready (up to 60 seconds)
            for i in range(12):
                time.sleep(5)
                if self.check_port_listening():
                    logger.info("Gateway port is listening")
                    # Give it a few more seconds to fully initialize
                    time.sleep(10)
                    if self.health_check():
                        self.state = GatewayState.RUNNING
                        self.consecutive_failures = 0
                        self.gateway_started_today = True
                        logger.info("Gateway started successfully")
                        self.status(
                            "Gateway Started",
                            f"IBKR Gateway started at {self.get_et_now().strftime('%H:%M ET')}",
                        )
                        return True

            logger.error("Gateway failed to start within timeout")
            self.state = GatewayState.STOPPED
            self.alert(
                "Gateway Start Failed",
                "Gateway did not become healthy within 60 seconds",
            )
            return False

        except Exception as e:
            logger.error(f"Failed to start Gateway: {e}")
            self.state = GatewayState.STOPPED
            self.alert("Gateway Start Error", str(e))
            return False

    def stop_gateway(self) -> bool:
        """Stop the Gateway service."""
        logger.info("Stopping Gateway...")
        self.state = GatewayState.STOPPING

        try:
            # Stop dependent services first
            for svc in TRADING_SERVICES:
                subprocess.run(
                    ["sudo", "systemctl", "stop", svc], timeout=30, capture_output=True
                )

            time.sleep(2)

            # Stop Gateway
            subprocess.run(["sudo", "systemctl", "stop", "ibkr-gateway"], timeout=60)

            self.state = GatewayState.STOPPED
            self.gateway_started_today = False
            logger.info("Gateway stopped successfully")
            self.status(
                "Gateway Stopped",
                f"IBKR Gateway stopped at {self.get_et_now().strftime('%H:%M ET')}",
            )
            return True

        except Exception as e:
            logger.error(f"Failed to stop Gateway: {e}")
            self.alert("Gateway Stop Error", str(e))
            return False

    def reset_gateway(self, reason: str) -> bool:
        """Reset Gateway and restart dependent services."""
        now = self.get_et_now()

        # Rate limit resets (max 1 per 5 minutes)
        if self.last_reset_time:
            time_since_reset = (now - self.last_reset_time).total_seconds()
            if time_since_reset < 300:
                logger.warning(
                    f"Reset rate limited, last reset was {time_since_reset:.0f}s ago"
                )
                return False

        logger.warning(f"Resetting Gateway: {reason}")
        self.alert(
            "Gateway Reset",
            f"Resetting Gateway: {reason}\nTime: {now.strftime('%H:%M ET')}",
            priority="high",
        )

        self.last_reset_time = now

        try:
            # Stop dependent services
            logger.info("Stopping dependent services...")
            for svc in TRADING_SERVICES:
                subprocess.run(
                    ["sudo", "systemctl", "stop", svc], timeout=30, capture_output=True
                )

            time.sleep(2)

            # Restart Gateway
            logger.info("Restarting Gateway service...")
            subprocess.run(["sudo", "systemctl", "restart", "ibkr-gateway"], timeout=60)

            # Wait for Gateway to be ready
            logger.info("Waiting for Gateway to be ready...")
            for i in range(12):
                time.sleep(5)
                if self.check_port_listening() and self.check_gateway_service():
                    time.sleep(10)  # Extra time for full initialization
                    break

            if not self.health_check():
                logger.error("Gateway not healthy after reset")
                self.alert("Gateway Reset Failed", "Gateway not healthy after reset")
                return False

            # Restart dependent services
            logger.info("Restarting dependent services...")
            time.sleep(5)
            for svc in TRADING_SERVICES:
                subprocess.run(
                    ["sudo", "systemctl", "start", svc], timeout=30, capture_output=True
                )
                time.sleep(3)  # Stagger service starts

            self.state = GatewayState.RUNNING
            self.consecutive_failures = 0
            logger.info("Gateway reset completed successfully")
            self.status(
                "Gateway Reset Complete",
                f"Gateway and services restarted at {now.strftime('%H:%M ET')}",
            )
            return True

        except Exception as e:
            logger.error(f"Gateway reset failed: {e}")
            self.alert("Gateway Reset Error", str(e), priority="urgent")
            return False

    def start_trading_services(self):
        """Start all trading services."""
        logger.info("Starting trading services...")
        for svc in TRADING_SERVICES:
            try:
                subprocess.run(
                    ["sudo", "systemctl", "start", svc], timeout=30, capture_output=True
                )
                logger.info(f"Started {svc}")
                time.sleep(3)  # Stagger starts
            except Exception as e:
                logger.error(f"Failed to start {svc}: {e}")

        self.status(
            "Trading Services Started", f"Started: {', '.join(TRADING_SERVICES)}"
        )

    def stop_trading_services(self):
        """Stop all trading services."""
        logger.info("Stopping trading services...")
        for svc in TRADING_SERVICES:
            try:
                subprocess.run(
                    ["sudo", "systemctl", "stop", svc], timeout=30, capture_output=True
                )
                logger.info(f"Stopped {svc}")
            except Exception as e:
                logger.error(f"Failed to stop {svc}: {e}")

        self.status(
            "Trading Services Stopped", f"Stopped: {', '.join(TRADING_SERVICES)}"
        )

    def run(self):
        """Main daemon loop."""
        logger.info("Gateway Manager daemon starting...")
        self.status("Gateway Manager Started", "Daemon is now monitoring Gateway")

        last_date = None
        services_started_today = False
        services_stopped_today = False

        while self.running:
            try:
                now = self.get_et_now()
                current_time = now.time()
                current_date = now.date()

                # Reset daily flags at midnight
                if last_date != current_date:
                    last_date = current_date
                    self.gateway_started_today = False
                    services_started_today = False
                    services_stopped_today = False
                    logger.info(f"New trading day: {current_date}")

                # Skip weekends
                if not self.is_weekday():
                    time.sleep(300)
                    continue

                # === GATEWAY LIFECYCLE ===

                # Start Gateway before market
                if (
                    current_time >= GATEWAY_START_TIME
                    and not self.gateway_started_today
                ):
                    if self.state == GatewayState.STOPPED:
                        self.start_gateway()

                # Stop Gateway after market
                if current_time >= GATEWAY_STOP_TIME and self.gateway_started_today:
                    if self.state in [GatewayState.RUNNING, GatewayState.UNHEALTHY]:
                        if not services_stopped_today:
                            self.stop_trading_services()
                            services_stopped_today = True
                        self.stop_gateway()

                # === TRADING SERVICES LIFECYCLE ===

                # Start trading services at market open
                if current_time >= MARKET_OPEN_TIME and not services_started_today:
                    if self.state == GatewayState.RUNNING:
                        self.start_trading_services()
                        services_started_today = True

                # Stop trading services at market close
                if (
                    current_time >= MARKET_CLOSE_TIME
                    and services_started_today
                    and not services_stopped_today
                ):
                    self.stop_trading_services()
                    services_stopped_today = True

                # === HEALTH MONITORING ===

                if self.state == GatewayState.RUNNING:
                    if not self.health_check():
                        self.consecutive_failures += 1
                        logger.warning(
                            f"Health check failed ({self.consecutive_failures}/{MAX_CONSECUTIVE_FAILURES})"
                        )

                        if self.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                            self.state = GatewayState.UNHEALTHY
                            if self.is_market_hours():
                                self.reset_gateway(
                                    f"Failed {MAX_CONSECUTIVE_FAILURES} consecutive health checks"
                                )
                            else:
                                self.alert(
                                    "Gateway Unhealthy",
                                    f"Gateway failed {MAX_CONSECUTIVE_FAILURES} health checks (outside market hours, not resetting)",
                                )
                    else:
                        if self.consecutive_failures > 0:
                            logger.info("Health check passed, resetting failure count")
                        self.consecutive_failures = 0

                # Determine sleep interval
                if self.is_market_hours():
                    sleep_time = HEALTH_CHECK_INTERVAL
                elif self.should_gateway_be_running():
                    sleep_time = PRE_MARKET_CHECK_INTERVAL
                else:
                    sleep_time = POST_MARKET_CHECK_INTERVAL

                time.sleep(sleep_time)

            except Exception as e:
                logger.error(f"Main loop error: {e}")
                time.sleep(60)

        logger.info("Gateway Manager daemon shutting down...")
        self.status("Gateway Manager Stopped", "Daemon has stopped")


def main():
    # Ensure log directory exists
    os.makedirs("/home/jacobw/quantstack/logs", exist_ok=True)

    manager = GatewayManager()
    manager.run()


if __name__ == "__main__":
    main()
