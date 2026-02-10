"""
Position Monitor Main Entry Point.

Runs the position monitor with periodic updates and graceful shutdown.
"""

import asyncio
import logging
import os
import signal
import sys

from position_monitor.monitor import PositionMonitor

# Configure logging (stdout goes to journal via systemd)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# Configuration
IBKR_HOST = os.environ.get("IBKR_GATEWAY_HOST", "127.0.0.1")
IBKR_PORT = int(os.environ.get("IBKR_GATEWAY_PORT", "7494"))
IBKR_CLIENT_ID = int(os.environ.get("IBKR_POSITION_CLIENT_ID", "900"))
IBKR_ACCOUNT_ID = os.environ.get("IBKR_ACCOUNT_ID")
OUTPUT_FILE = "/tmp/positions.json"
REFRESH_INTERVAL = 60  # seconds


class PositionMonitorApp:
    """Main application for position monitoring."""

    def __init__(self):
        self.monitor = PositionMonitor(
            host=IBKR_HOST,
            port=IBKR_PORT,
            client_id=IBKR_CLIENT_ID,
            account_id=IBKR_ACCOUNT_ID,
            output_file=OUTPUT_FILE,
        )
        self.running = False
        self._stop_event = asyncio.Event()

    async def run(self):
        """Run the position monitor with periodic updates."""
        logger.info("Starting Position Monitor")

        # Connect to IBKR Gateway
        if not self.monitor.connect():
            logger.error("Failed to connect to IBKR Gateway")
            return 1

        self.running = True

        # Initial update
        logger.info("Performing initial update")
        self.monitor.update()

        # Main loop
        try:
            while not self._stop_event.is_set():
                try:
                    # Wait for refresh interval or stop event
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=REFRESH_INTERVAL,
                    )

                    # If stop event was set, break
                    if self._stop_event.is_set():
                        break

                except asyncio.TimeoutError:
                    # Refresh interval elapsed, perform update
                    pass

                # Perform update
                logger.info("Performing scheduled update")
                success = self.monitor.update()

                if not success:
                    logger.warning("Update failed, will retry on next interval")

        except Exception as e:
            logger.error(f"Main loop error: {e}", exc_info=True)
        finally:
            self.monitor.disconnect()
            logger.info("Position Monitor stopped")

        return 0

    def stop(self):
        """Signal the application to stop gracefully."""
        if self.running:
            logger.info("Received stop signal")
            self._stop_event.set()
            self.running = False


def signal_handler(app: PositionMonitorApp):
    """Create signal handler for graceful shutdown."""

    def handler(signum, frame):
        logger.info(f"Received signal {signum}")
        app.stop()

    return handler


async def main():
    """Main entry point."""
    app = PositionMonitorApp()

    # Setup signal handlers
    sig_handler = signal_handler(app)
    signal.signal(signal.SIGTERM, sig_handler)
    signal.signal(signal.SIGINT, sig_handler)

    # Run the application
    return await app.run()


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
