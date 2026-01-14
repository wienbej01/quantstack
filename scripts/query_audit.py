#!/usr/bin/env python3
"""
Query audit logs for debugging and analysis.

Usage:
    query_audit.py --date 2026-01-14
    query_audit.py --service intraday-sip --last 24h
    query_audit.py --severity ERROR
    query_audit.py --event-type SERVICE_ERROR
"""

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytz

MANILA = pytz.timezone("Asia/Manila")
ET = pytz.timezone("America/New_York")


def parse_args():
    parser = argparse.ArgumentParser(description="Query audit logs")
    parser.add_argument("--date", help="Date to query (YYYY-MM-DD)")
    parser.add_argument("--service", help="Filter by service name")
    parser.add_argument("--severity", help="Filter by severity (INFO/WARNING/ERROR)")
    parser.add_argument("--event-type", help="Filter by event type")
    parser.add_argument("--last", help="Last N hours (e.g., 24h)")
    parser.add_argument("--limit", type=int, default=100, help="Max results")
    parser.add_argument("--format", choices=["json", "human"], default="human")
    return parser.parse_args()


def load_audit_log(date_str: str) -> list[dict]:
    """Load audit log for a specific date."""
    log_dir = Path.home() / "quantstack" / "logs" / "audit"
    log_file = log_dir / f"audit_{date_str}.jsonl"

    if not log_file.exists():
        return []

    events = []
    with open(log_file) as f:
        for line in f:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return events


def filter_events(events: list[dict], args) -> list[dict]:
    """Filter events based on criteria."""
    filtered = events

    if args.service:
        filtered = [e for e in filtered if e.get("service") == args.service]

    if args.severity:
        filtered = [e for e in filtered if e.get("severity") == args.severity]

    if args.event_type:
        filtered = [e for e in filtered if e.get("event_type") == args.event_type]

    if args.last:
        # Parse "24h" format
        hours = int(args.last.rstrip("h"))
        cutoff = datetime.now(pytz.UTC) - timedelta(hours=hours)
        filtered = [
            e for e in filtered if datetime.fromisoformat(e["timestamp_utc"]) > cutoff
        ]

    return filtered[: args.limit]


def format_human(events: list[dict]):
    """Format events in human-readable format."""
    if not events:
        print("No events found")
        return

    print(f"\n{'='*80}")
    print(f"Found {len(events)} events")
    print(f"{'='*80}\n")

    for event in events:
        mnl_time = datetime.fromisoformat(event["timestamp_mnl"]).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        et_time = datetime.fromisoformat(event["timestamp_et"]).strftime("%H:%M:%S")

        severity = event["severity"]
        service = event["service"]
        event_type = event["event_type"]
        message = event["message"]

        # Color code severity
        color = ""
        if severity == "ERROR":
            color = "\033[91m"  # Red
        elif severity == "WARNING":
            color = "\033[93m"  # Yellow
        reset = "\033[0m" if color else ""

        print(f"{color}[{mnl_time} MNL / {et_time} ET] [{severity}]{reset}")
        print(f"  Service: {service}")
        print(f"  Event: {event_type}")
        print(f"  Message: {message}")

        if "context" in event and event["context"]:
            print(f"  Context: {json.dumps(event['context'], indent=2)}")

        if "metrics" in event and event["metrics"]:
            print(f"  Metrics: {json.dumps(event['metrics'], indent=2)}")

        print()


def format_json(events: list[dict]):
    """Format events as JSON."""
    print(json.dumps(events, indent=2))


def main():
    args = parse_args()

    # Determine date to query
    date_str = args.date or datetime.now(MANILA).strftime("%Y-%m-%d")

    # Load events
    events = load_audit_log(date_str)

    # Filter events
    filtered = filter_events(events, args)

    # Format output
    if args.format == "json":
        format_json(filtered)
    else:
        format_human(filtered)


if __name__ == "__main__":
    main()
