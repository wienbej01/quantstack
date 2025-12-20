"""Independent scheduling for L2 collection."""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import time as dt_time
from typing import Callable, Optional

import pytz

logger = logging.getLogger(__name__)


@dataclass
class TimeWindow:
    """Collection time window."""

    start: dt_time
    end: dt_time

    def contains(self, t: dt_time) -> bool:
        return self.start <= t <= self.end


class L2Scheduler:
    """Independent L2 collection scheduler."""

    def __init__(self, config: dict):
        schedule_cfg = config.get("schedule", {})
        self.timezone = pytz.timezone(schedule_cfg.get("timezone", "America/New_York"))
        self.skip_weekends = schedule_cfg.get("skip_weekends", True)
        self.skip_holidays = schedule_cfg.get("skip_holidays", False)
        self.holidays = set(schedule_cfg.get("holidays", []))
        self.windows = self._parse_windows(schedule_cfg.get("windows", []))

    def _parse_windows(self, window_strs: list[str]) -> list[TimeWindow]:
        """Parse time window strings like '09:30-10:30'."""
        windows = []
        for ws in window_strs:
            try:
                start_str, end_str = ws.split("-")
                start = dt_time(*map(int, start_str.split(":")))
                end = dt_time(*map(int, end_str.split(":")))
                windows.append(TimeWindow(start, end))
            except Exception as e:
                logger.warning(f"Invalid window '{ws}': {e}")
        return windows

    def now_local(self) -> datetime:
        """Get current time in configured timezone."""
        return datetime.now(self.timezone)

    def is_collection_time(self) -> bool:
        """Check if current time is within collection windows."""
        now = self.now_local()
        date_str = now.strftime("%Y-%m-%d")

        # Skip weekends
        if self.skip_weekends and now.weekday() >= 5:
            return False
        if self.skip_holidays and date_str in self.holidays:
            return False

        # Check windows
        current_time = now.time()
        return any(w.contains(current_time) for w in self.windows)

    def current_window(self) -> Optional[TimeWindow]:
        """Get current active window, if any."""
        if not self.is_collection_time():
            return None

        current_time = self.now_local().time()
        for w in self.windows:
            if w.contains(current_time):
                return w
        return None

    def next_window_start(self) -> Optional[datetime]:
        """Get next collection window start time."""
        now = self.now_local()
        current_time = now.time()

        # Find next window today
        for w in sorted(self.windows, key=lambda x: x.start):
            if w.start > current_time:
                return now.replace(
                    hour=w.start.hour, minute=w.start.minute, second=0, microsecond=0
                )

        # Next window is tomorrow (first window)
        if self.windows:
            tomorrow = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            first_window = min(self.windows, key=lambda x: x.start)
            while True:
                date_str = tomorrow.strftime("%Y-%m-%d")
                if self.skip_weekends and tomorrow.weekday() >= 5:
                    tomorrow += timedelta(days=1)
                    continue
                if self.skip_holidays and date_str in self.holidays:
                    tomorrow += timedelta(days=1)
                    continue
                return tomorrow.replace(
                    hour=first_window.start.hour, minute=first_window.start.minute
                )

        return None

    def seconds_until_next_window(self) -> int:
        """Get seconds until next collection window."""
        next_start = self.next_window_start()
        if next_start:
            delta = next_start - self.now_local()
            return max(0, int(delta.total_seconds()))
        return 0

    def run_daemon(
        self, on_window_start: Callable, on_window_end: Callable, poll_interval: int = 5
    ):
        """Run as daemon, calling callbacks on window transitions."""
        logger.info(f"Starting scheduler daemon with {len(self.windows)} windows")
        was_in_window = False

        try:
            while True:
                in_window = self.is_collection_time()

                if in_window and not was_in_window:
                    # Window started
                    window = self.current_window()
                    logger.info(f"Collection window started: {window}")
                    on_window_start()

                elif not in_window and was_in_window:
                    # Window ended
                    logger.info("Collection window ended")
                    on_window_end()

                was_in_window = in_window
                time.sleep(poll_interval)

        except KeyboardInterrupt:
            logger.info("Scheduler daemon stopped")
            if was_in_window:
                on_window_end()
