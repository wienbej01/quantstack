#!/usr/bin/env python3
"""L2 collector heartbeat monitor."""

import subprocess
import time
from datetime import datetime
from pathlib import Path


def check_l2_status():
    """Check if L2 collector is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "run_collector"], capture_output=True, text=True
        )
        return result.returncode == 0
    except:
        return False


def log_heartbeat():
    """Log heartbeat with timestamp."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_running = check_l2_status()
    status = "RUNNING" if is_running else "STOPPED"

    # Count recent L2 files
    data_dir = Path("data/l2")
    recent_files = 0
    if data_dir.exists():
        for file in data_dir.rglob("*.parquet"):
            if (
                datetime.now() - datetime.fromtimestamp(file.stat().st_mtime)
            ).seconds < 3600:
                recent_files += 1

    message = f"{timestamp} - L2 Collector: {status} | Recent files: {recent_files}"
    print(message)

    # Log to file
    with open("l2_heartbeat.log", "a") as f:
        f.write(f"{message}\n")

    return is_running


if __name__ == "__main__":
    print("=== L2 HEARTBEAT MONITOR ===")

    while True:
        is_running = log_heartbeat()

        if not is_running:
            print("⚠ L2 collector not running - restart with:")
            print(
                "cd qx-l2 && python scripts/run_collector.py --config configs/dual_system.yaml &"
            )
            break

        time.sleep(300)  # 5-minute intervals
