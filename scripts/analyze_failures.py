#!/usr/bin/env python3
"""
Analyze audit logs for failures and generate reports.

Usage:
    analyze_failures.py --date 2026-01-14
    analyze_failures.py --last 7d
"""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pytz

MANILA = pytz.timezone("Asia/Manila")


def parse_args():
    parser = argparse.ArgumentParser(description="Analyze audit log failures")
    parser.add_argument("--date", help="Date to analyze (YYYY-MM-DD)")
    parser.add_argument("--last", help="Last N days (e.g., 7d)")
    return parser.parse_args()


def load_audit_logs(dates: list[str]) -> list[dict]:
    """Load audit logs for multiple dates."""
    log_dir = Path.home() / "quantstack" / "logs" / "audit"
    events = []

    for date_str in dates:
        log_file = log_dir / f"audit_{date_str}.jsonl"
        if not log_file.exists():
            continue

        with open(log_file) as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    return events


def analyze_failures(events: list[dict]) -> dict:
    """Analyze failure patterns."""
    failures = [e for e in events if e.get("severity") in ["ERROR", "CRITICAL"]]

    # Group by service
    by_service = defaultdict(list)
    for failure in failures:
        by_service[failure["service"]].append(failure)

    # Group by event type
    by_event_type = defaultdict(int)
    for failure in failures:
        by_event_type[failure["event_type"]] += 1

    # Find exit code patterns
    exit_codes = defaultdict(int)
    for failure in failures:
        if "context" in failure and "exit_code" in failure.get("context", {}):
            exit_codes[failure["context"]["exit_code"]] += 1

    return {
        "total_failures": len(failures),
        "by_service": dict(by_service),
        "by_event_type": dict(by_event_type),
        "exit_codes": dict(exit_codes),
    }


def print_report(analysis: dict, events: list[dict]):
    """Print failure analysis report."""
    print("\n" + "=" * 80)
    print("AUDIT LOG FAILURE ANALYSIS")
    print("=" * 80 + "\n")

    print(f"Total Events: {len(events)}")
    print(f"Total Failures: {analysis['total_failures']}")
    print(f"Failure Rate: {analysis['total_failures']/len(events)*100:.1f}%\n")

    print("Failures by Service:")
    print("-" * 40)
    for service, failures in sorted(
        analysis["by_service"].items(), key=lambda x: len(x[1]), reverse=True
    ):
        print(f"  {service}: {len(failures)} failures")

        # Show most recent failure
        if failures:
            recent = failures[-1]
            mnl_time = datetime.fromisoformat(recent["timestamp_mnl"]).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            print(f"    Last: {mnl_time} MNL - {recent['message']}")

    print("\nFailures by Event Type:")
    print("-" * 40)
    for event_type, count in sorted(
        analysis["by_event_type"].items(), key=lambda x: x[1], reverse=True
    ):
        print(f"  {event_type}: {count}")

    if analysis["exit_codes"]:
        print("\nExit Code Distribution:")
        print("-" * 40)
        for code, count in sorted(
            analysis["exit_codes"].items(), key=lambda x: x[1], reverse=True
        ):
            code_name = {
                0: "SUCCESS",
                1: "GENERAL_ERROR",
                130: "SIGINT (Ctrl+C)",
                137: "SIGKILL",
                143: "SIGTERM",
            }.get(code, f"CODE_{code}")
            print(f"  {code_name}: {count}")

    print("\n" + "=" * 80 + "\n")


def main():
    args = parse_args()

    # Determine dates to analyze
    if args.last:
        days = int(args.last.rstrip("d"))
        dates = [
            (datetime.now(MANILA) - timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(days)
        ]
    elif args.date:
        dates = [args.date]
    else:
        dates = [datetime.now(MANILA).strftime("%Y-%m-%d")]

    # Load and analyze
    events = load_audit_logs(dates)

    if not events:
        print("No audit logs found for specified dates")
        return

    analysis = analyze_failures(events)
    print_report(analysis, events)


if __name__ == "__main__":
    main()
