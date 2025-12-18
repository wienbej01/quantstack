#!/usr/bin/env python3
"""Monitor L2 collector systemd service status and data collection."""

import subprocess
from datetime import datetime
from pathlib import Path


def get_systemd_status():
    """Get L2 collector timer and service status."""
    try:
        # Timer status
        timer_result = subprocess.run(
            ["systemctl", "is-active", "l2-collector.timer"],
            capture_output=True,
            text=True,
            check=False,
        )
        timer_status = timer_result.stdout.strip()

        # Service status
        service_result = subprocess.run(
            ["systemctl", "is-active", "l2-collector.service"],
            capture_output=True,
            text=True,
            check=False,
        )
        service_status = service_result.stdout.strip()

        # Next run time
        next_run = subprocess.run(
            ["systemctl", "list-timers", "l2-collector.timer", "--no-pager"],
            capture_output=True,
            text=True,
            check=False,
        )

        return {
            "timer_status": timer_status,
            "service_status": service_status,
            "next_run_info": next_run.stdout,
        }
    except Exception as e:
        return {"error": str(e)}


def get_l2_data_stats():
    """Get L2 data collection statistics."""
    data_dir = Path("qx-l2/data/l2_dual")
    if not data_dir.exists():
        return {"error": "L2 data directory not found"}

    stats = {
        "total_files": 0,
        "total_size_mb": 0,
        "latest_file": None,
        "files_today": 0,
    }

    today = datetime.now().date()

    for file_path in data_dir.rglob("*.parquet"):
        stats["total_files"] += 1
        stats["total_size_mb"] += file_path.stat().st_size / (1024 * 1024)

        # Check if file is from today
        file_date = datetime.fromtimestamp(file_path.stat().st_mtime).date()
        if file_date == today:
            stats["files_today"] += 1

        # Track latest file
        if (
            stats["latest_file"] is None
            or file_path.stat().st_mtime > stats["latest_file"]["mtime"]
        ):
            stats["latest_file"] = {
                "path": str(file_path),
                "mtime": file_path.stat().st_mtime,
                "size_mb": file_path.stat().st_size / (1024 * 1024),
            }

    stats["total_size_mb"] = round(stats["total_size_mb"], 2)
    if stats["latest_file"]:
        stats["latest_file"]["size_mb"] = round(stats["latest_file"]["size_mb"], 2)
        stats["latest_file"]["timestamp"] = datetime.fromtimestamp(
            stats["latest_file"]["mtime"]
        ).isoformat()

    return stats


def main():
    """Main monitoring function."""
    print("=" * 60)
    print("L2 COLLECTOR SYSTEMD MONITOR")
    print("=" * 60)

    # Systemd status
    systemd_status = get_systemd_status()
    if "error" in systemd_status:
        print(f"❌ Systemd Error: {systemd_status['error']}")
    else:
        timer_emoji = "✅" if systemd_status["timer_status"] == "active" else "❌"
        service_emoji = (
            "✅" if systemd_status["service_status"] in ["active", "inactive"] else "❌"
        )

        print(f"{timer_emoji} Timer Status: {systemd_status['timer_status']}")
        print(f"{service_emoji} Service Status: {systemd_status['service_status']}")
        print("\nNext Run Schedule:")
        print(systemd_status["next_run_info"])

    print("-" * 60)

    # Data collection stats
    l2_stats = get_l2_data_stats()
    if "error" in l2_stats:
        print(f"❌ Data Error: {l2_stats['error']}")
    else:
        print(f"📊 Total L2 Files: {l2_stats['total_files']}")
        print(f"💾 Total Size: {l2_stats['total_size_mb']} MB")
        print(f"📅 Files Today: {l2_stats['files_today']}")

        if l2_stats["latest_file"]:
            print(f"🕐 Latest File: {l2_stats['latest_file']['timestamp']}")
            print(f"📁 Latest Path: {l2_stats['latest_file']['path']}")
        else:
            print("❌ No L2 files found")

    print("=" * 60)
    print("Commands:")
    print("  sudo journalctl -u l2-collector.service -f  # Live logs")
    print("  sudo systemctl status l2-collector.timer    # Timer status")
    print("  sudo systemctl start l2-collector.service   # Manual run")


if __name__ == "__main__":
    main()
