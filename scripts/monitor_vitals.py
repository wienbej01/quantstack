#!/usr/bin/env python3
"""System vitals monitor for overnight trading operations."""
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

DB_PATH = Path.home() / "quantstack" / "data" / "vitals.db"
INTERVAL_SECONDS = 10
TRADING_PROCESSES = ["l2-scalping", "l2-vwap-reversal", "intraday-paper", "ibgateway"]

# Patterns to match in Python process cmdline (not process name)
CMDLINE_PATTERNS = [
    "l2_scalping",
    "l2_vwap_reversion",
    "start_paper_trading",
    "intraday_paper",
    "platform.py",
    "monitor_vitals",
]

# CPU spike detection thresholds
CPU_SPIKE_SYSTEM_PCT = 90.0
CPU_SPIKE_PROCESS_PCT = 80.0
CPU_SPIKE_CONSECUTIVE = 3  # readings before alert (30s at 10s interval)


def init_db():
    """Initialize SQLite database with WAL mode."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vitals (
            timestamp TEXT PRIMARY KEY,
            cpu_percent REAL,
            mem_percent REAL,
            disk_read_mb REAL,
            disk_write_mb REAL,
            processes TEXT
        )
    """
    )
    conn.commit()
    return conn


def get_process_stats():
    """Get stats for trading processes by matching cmdline, not process name."""
    stats = {}
    for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            # First check process name for non-Python processes (ibgateway)
            name = proc.info["name"] or ""
            if any(tp in name.lower() for tp in TRADING_PROCESSES):
                stats[name] = {
                    "pid": proc.info["pid"],
                    "cpu": proc.info["cpu_percent"],
                    "mem": proc.info["memory_percent"],
                }
                continue

            # For Python processes, check cmdline
            if "python" not in name.lower():
                continue

            cmdline = proc.cmdline()
            cmdline_str = " ".join(cmdline).lower()
            for pattern in CMDLINE_PATTERNS:
                if pattern in cmdline_str:
                    label = pattern.replace("_", "-")
                    stats[label] = {
                        "pid": proc.info["pid"],
                        "cpu": proc.info["cpu_percent"],
                        "mem": proc.info["memory_percent"],
                        "cmdline": cmdline_str[:200],
                    }
                    break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return stats


def record_vitals(conn):
    """Record system vitals to database."""
    ts = datetime.now(timezone.utc).isoformat()
    cpu = psutil.cpu_percent(interval=1)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_io_counters()
    disk_read_mb = disk.read_bytes / (1024 * 1024) if disk else 0
    disk_write_mb = disk.write_bytes / (1024 * 1024) if disk else 0
    procs = get_process_stats()

    conn.execute(
        """
        INSERT INTO vitals (timestamp, cpu_percent, mem_percent, disk_read_mb, disk_write_mb, processes)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (ts, cpu, mem, disk_read_mb, disk_write_mb, json.dumps(procs)),
    )
    conn.commit()


def cleanup_old_records(conn, days=30):
    """Remove records older than specified days."""
    conn.execute(
        "DELETE FROM vitals WHERE timestamp < datetime('now', '-' || ? || ' days')",
        (days,),
    )
    conn.commit()


class CPUSpikeDetector:
    """Tracks consecutive high CPU readings and fires alerts."""

    def __init__(
        self,
        system_threshold: float = CPU_SPIKE_SYSTEM_PCT,
        process_threshold: float = CPU_SPIKE_PROCESS_PCT,
        consecutive: int = CPU_SPIKE_CONSECUTIVE,
        alert_fn=None,
    ):
        self.system_threshold = system_threshold
        self.process_threshold = process_threshold
        self.consecutive = consecutive
        self.alert_fn = alert_fn
        self._system_high_count = 0
        self._process_high_counts: dict[str, int] = {}

    def check(self, system_cpu: float, process_stats: dict) -> None:
        """Check CPU readings and fire alerts if thresholds exceeded."""
        # System-wide check
        if system_cpu >= self.system_threshold:
            self._system_high_count += 1
            if self._system_high_count >= self.consecutive and self.alert_fn:
                self.alert_fn(
                    system_cpu,
                    self._system_high_count * INTERVAL_SECONDS,
                    "system-wide",
                )
                self._system_high_count = 0  # Reset after alert
        else:
            self._system_high_count = 0

        # Per-process check
        active = set()
        for name, stats in process_stats.items():
            active.add(name)
            cpu = stats.get("cpu", 0) or 0
            if cpu >= self.process_threshold:
                self._process_high_counts[name] = (
                    self._process_high_counts.get(name, 0) + 1
                )
                if (
                    self._process_high_counts[name] >= self.consecutive
                    and self.alert_fn
                ):
                    self.alert_fn(
                        cpu, self._process_high_counts[name] * INTERVAL_SECONDS, name
                    )
                    self._process_high_counts[name] = 0
            else:
                self._process_high_counts[name] = 0

        # Clear stale entries
        for name in list(self._process_high_counts):
            if name not in active:
                del self._process_high_counts[name]


def main():
    """Run vitals monitor loop."""
    conn = init_db()
    print(f"Vitals monitor started. Writing to {DB_PATH}")

    # CPU spike alerting
    try:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from cpapi.emergency_alerts import EmergencyAlerts

        alerts = EmergencyAlerts()
        spike_detector = CPUSpikeDetector(alert_fn=alerts.cpu_spike)
        print("CPU spike alerting enabled")
    except Exception as e:
        print(f"CPU spike alerting disabled: {e}")
        spike_detector = None

    try:
        while True:
            record_vitals(conn)
            if spike_detector:
                cpu = psutil.cpu_percent(interval=0)
                procs = get_process_stats()
                spike_detector.check(cpu, procs)
            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nVitals monitor stopped")
    finally:
        # Cleanup on exit
        cleanup_old_records(conn)
        conn.close()


if __name__ == "__main__":
    main()
