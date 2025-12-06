"""Utilities to manage time-of-day profile thresholds for intraday policy."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import time
from typing import Any


@dataclass(frozen=True)
class TODProfile:
    """Defines a threshold bucket for a slice of the trading day."""

    name: str
    start_time: time
    end_time: time
    thresholds: dict[str, float]

    def contains(self, current_time: time) -> bool:
        """Return True when the supplied time falls inside the profile."""
        if self.start_time <= self.end_time:
            return self.start_time <= current_time < self.end_time
        return current_time >= self.start_time or current_time < self.end_time


def _parse_time(value: str) -> time:
    if isinstance(value, time):
        return value
    if not isinstance(value, str):
        raise ValueError("tod profile times must be strings")
    parts = value.split(":")
    if len(parts) == 2:
        hour, minute = parts
        second = 0
    elif len(parts) == 3:
        hour, minute, second = parts
    else:
        raise ValueError(f"Invalid time format: {value}")
    return time(int(hour), int(minute), int(second))


def build_tod_profiles(config: dict[str, Any]) -> list[TODProfile]:
    """Construct ordered TOD profiles from the configuration."""
    raw_profiles = config.get("tod_profiles")
    if raw_profiles is None:
        return []

    items: Iterable[tuple[str, Any]]
    if isinstance(raw_profiles, dict):
        items = raw_profiles.items()
    elif isinstance(raw_profiles, list):
        items = ((str(idx), profile) for idx, profile in enumerate(raw_profiles))
    else:
        raise ValueError("tod_profiles must be a dict or list")

    profiles = []
    for name, payload in items:
        start_time = _parse_time(payload["start_time"])
        end_time = _parse_time(payload["end_time"])
        thresholds = {
            key: float(value)
            for key, value in payload.items()
            if key not in ("start_time", "end_time")
        }
        profiles.append(TODProfile(name=name, start_time=start_time, end_time=end_time, thresholds=thresholds))

    profiles.sort(key=lambda profile: profile.start_time)
    return profiles


def get_active_profile(
    profiles: Sequence[TODProfile], current_time: time
) -> TODProfile | None:
    """Return the profile whose window covers the supplied time."""
    if not profiles:
        return None
    for profile in profiles:
        if profile.contains(current_time):
            return profile
    return profiles[-1]
