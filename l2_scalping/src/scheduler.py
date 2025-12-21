"""Market Hours Scheduler for L2 Scalping System

Automatically starts/stops trading based on market hours.
"""

import logging
import time
from datetime import datetime
from datetime import time as dt_time
from typing import Callable

import pytz

logger = logging.getLogger(__name__)


class MarketScheduler:
    """Handles market hours and automatic trading schedule"""

    def __init__(self, config: dict):
        self.config = config
        self.et_tz = pytz.timezone("US/Eastern")

        # Market hours (ET)
        self.market_open = dt_time(9, 30)  # 9:30 AM
        self.market_close = dt_time(16, 0)  # 4:00 PM

        # Trading schedule
        schedule_config = config.get("schedule", {})
        self.auto_start = schedule_config.get("auto_start", True)
        self.pre_market_buffer = schedule_config.get("pre_market_buffer_minutes", 5)
        self.post_market_buffer = schedule_config.get("post_market_buffer_minutes", 5)

        logger.info(f"Market scheduler initialized - auto_start: {self.auto_start}")

    def get_et_time(self) -> datetime:
        """Get current Eastern Time"""
        return datetime.now(self.et_tz)

    def is_market_day(self) -> bool:
        """Check if today is a trading day (Monday-Friday)"""
        et_now = self.get_et_time()
        return et_now.weekday() < 5  # Monday=0, Friday=4

    def is_market_hours(self) -> bool:
        """Check if currently in market hours"""
        if not self.is_market_day():
            return False

        et_now = self.get_et_time()
        current_time = et_now.time()

        return self.market_open <= current_time <= self.market_close

    def is_trading_time(self) -> bool:
        """Check if system should be trading (includes buffers)"""
        if not self.is_market_day():
            return False

        et_now = self.get_et_time()
        current_time = et_now.time()

        # Add buffers
        start_time = dt_time(
            self.market_open.hour,
            max(0, self.market_open.minute - self.pre_market_buffer),
        )
        end_time = dt_time(
            self.market_close.hour,
            min(59, self.market_close.minute + self.post_market_buffer),
        )

        return start_time <= current_time <= end_time

    def wait_for_market_open(self) -> None:
        """Wait until market opens"""
        while not self.is_trading_time():
            et_now = self.get_et_time()

            if not self.is_market_day():
                # Wait until next weekday
                next_check = et_now.replace(hour=8, minute=0, second=0, microsecond=0)
                if et_now.time() >= dt_time(17, 0):  # After 5 PM, wait until tomorrow
                    next_check = next_check.replace(day=next_check.day + 1)

                wait_seconds = (next_check - et_now).total_seconds()
                logger.info(
                    f"Market closed. Waiting {wait_seconds/3600:.1f} hours until next check"
                )
                time.sleep(min(3600, wait_seconds))  # Check every hour max
            else:
                # Market day but not trading time yet
                logger.info(
                    f"Waiting for trading time. Current ET: {et_now.strftime('%H:%M:%S')}"
                )
                time.sleep(60)  # Check every minute

    def run_with_schedule(self, trading_function: Callable) -> None:
        """Run trading function with automatic scheduling"""
        logger.info("Starting scheduled trading system")

        while True:
            try:
                if self.auto_start:
                    # Wait for market open
                    self.wait_for_market_open()

                    if self.is_trading_time():
                        logger.info("Market open - starting trading")
                        trading_function()
                        logger.info("Trading session ended")

                    # Wait until next day
                    logger.info("Waiting for next trading day")
                    time.sleep(3600)  # Check every hour
                else:
                    # Manual mode - just run once
                    trading_function()
                    break

            except KeyboardInterrupt:
                logger.info("Scheduler stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in scheduler: {e}")
                time.sleep(300)  # Wait 5 minutes before retry
