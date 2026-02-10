#!/usr/bin/env python3
"""Query vitals database for crash reconstruction."""
import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path


DB_PATH = Path.home() / "quantstack" / "data" / "vitals.db"


def query_timerange(start_time, end_time):
    """Query vitals within time range."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        """
        SELECT timestamp, cpu_percent, mem_percent, disk_read_mb, disk_write_mb, processes
        FROM vitals
        WHERE timestamp BETWEEN ? AND ?
        ORDER BY timestamp
    """,
        (start_time, end_time),
    )
    return cursor.fetchall()


def query_before_crash(crash_time, minutes_before=30):
    """Query vitals leading up to a crash."""
    crash_dt = datetime.fromisoformat(crash_time)
    start_dt = crash_dt - timedelta(minutes=minutes_before)
    return query_timerange(start_dt.isoformat(), crash_time)


def print_vitals(rows):
    """Print vitals in readable format."""
    if not rows:
        print("No records found")
        return

    print(f"{'Timestamp':<28} {'CPU%':>6} {'Mem%':>6} {'DiskR(MB)':>12} {'DiskW(MB)':>12} Processes")
    print("-" * 100)

    for row in rows:
        ts, cpu, mem, disk_r, disk_w, procs_json = row
        procs = json.loads(procs_json)
        proc_summary = ", ".join(f"{k}:{v['cpu']:.1f}%" for k, v in procs.items()) if procs else "none"
        print(f"{ts:<28} {cpu:>6.1f} {mem:>6.1f} {disk_r:>12.1f} {disk_w:>12.1f} {proc_summary}")


def main():
    """CLI for querying vitals."""
    parser = argparse.ArgumentParser(description="Query system vitals database")
    parser.add_argument("--crash-time", help="ISO timestamp of crash (query 30min before)")
    parser.add_argument("--start", help="Start time (ISO format)")
    parser.add_argument("--end", help="End time (ISO format)")
    parser.add_argument("--last-hours", type=int, help="Show last N hours")
    parser.add_argument("--minutes-before", type=int, default=30, help="Minutes before crash to show")

    args = parser.parse_args()

    if args.crash_time:
        rows = query_before_crash(args.crash_time, args.minutes_before)
    elif args.start and args.end:
        rows = query_timerange(args.start, args.end)
    elif args.last_hours:
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(hours=args.last_hours)
        rows = query_timerange(start_dt.isoformat(), end_dt.isoformat())
    else:
        parser.print_help()
        return

    print_vitals(rows)


if __name__ == "__main__":
    main()
