from datetime import date, datetime, time

import pytz
from qx_l2.scheduler import L2Scheduler


def test_next_window_start_handles_month_rollover(monkeypatch):
    tz = pytz.timezone("America/New_York")
    cfg = {
        "schedule": {
            "timezone": "America/New_York",
            "windows": ["09:30-10:30"],
            "skip_weekends": False,
        }
    }
    scheduler = L2Scheduler(cfg)

    now = tz.localize(datetime(2025, 1, 31, 16, 30, 0))
    monkeypatch.setattr(scheduler, "now_local", lambda: now)

    next_start = scheduler.next_window_start()
    assert next_start.date() == date(2025, 2, 1)
    assert next_start.time() == time(9, 30)


def test_next_window_start_skips_weekends(monkeypatch):
    tz = pytz.timezone("America/New_York")
    cfg = {
        "schedule": {
            "timezone": "America/New_York",
            "windows": ["09:30-10:30"],
            "skip_weekends": True,
        }
    }
    scheduler = L2Scheduler(cfg)

    now = tz.localize(datetime(2025, 1, 3, 16, 30, 0))  # Friday
    monkeypatch.setattr(scheduler, "now_local", lambda: now)

    next_start = scheduler.next_window_start()
    assert next_start.weekday() == 0
    assert next_start.time() == time(9, 30)
