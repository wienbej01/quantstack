#!/usr/bin/env python3
"""Monitor live trading system status."""

import json
import os
from datetime import datetime
from pathlib import Path


def check_system_status():
    """Check live trading system status."""
    print("🔍 Live Trading System Status")
    print("=" * 50)

    # Check daily SIP results
    date_str = datetime.now().strftime("%Y-%m-%d")
    sip_dir = Path(
        os.environ.get("SIP_DAILY_ROOT", "/home/jacobw/intraday_stack/data/daily_sip")
    )
    sip_file = sip_dir / f"date={date_str}" / "sip_universe.json"

    if sip_file.exists():
        with open(sip_file) as f:
            data = json.load(f)
        symbols = data.get("symbols", []) if isinstance(data, dict) else data
        l2_symbols = symbols[:3]
        print(f"✅ Daily SIP: {len(symbols)} symbols selected")
        print(f"✅ L2 Symbols: {l2_symbols}")
    else:
        print("❌ No daily SIP results found")
        print(
            "   Run: python /home/jacobw/intraday_stack/scripts/generate_daily_sip_universe.py"
        )

    # Check L2 data collection
    l2_dir = Path("data/live_l2")
    if l2_dir.exists():
        l2_runs = list(l2_dir.glob("run_id=*"))
        if l2_runs:
            latest_run = max(l2_runs, key=lambda x: x.stat().st_mtime)
            raw_dirs = list(latest_run.glob("raw/date=*/symbol=*"))
            print(
                f"✅ L2 Data: {len(raw_dirs)} symbol collections in {latest_run.name}"
            )
        else:
            print("⚠️  No L2 data collected yet")
    else:
        print("⚠️  L2 data directory not found")

    # Check logs
    log_dir = Path("logs")
    if log_dir.exists():
        log_files = list(log_dir.glob("*.log"))
        if log_files:
            latest_log = max(log_files, key=lambda x: x.stat().st_mtime)
            size_mb = latest_log.stat().st_size / 1024 / 1024
            print(f"✅ Latest Log: {latest_log.name} ({size_mb:.1f} MB)")
        else:
            print("⚠️  No log files found")

    # Check API keys
    if os.getenv("POLYGON_API_KEY"):
        key_preview = os.getenv("POLYGON_API_KEY")[:10] + "..."
        print(f"✅ Polygon API: {key_preview}")
    else:
        print("❌ POLYGON_API_KEY not set")

    # Check cron job
    import subprocess

    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
        if "daily_sip_scheduler.py" in result.stdout:
            print("✅ Daily SIP cron job active")
        else:
            print("⚠️  Daily SIP cron job not found")
            print("   Run: make setup-cron")
    except:
        print("⚠️  Could not check cron jobs")

    print("\n📋 Quick Commands:")
    print("   make daily-sip     - Run daily SIP selection")
    print("   make start-live    - Start live trading system")
    print("   make setup-cron    - Setup daily SIP cron job")
    print("   tail -f logs/live_trading.log - Monitor live system")


if __name__ == "__main__":
    check_system_status()
