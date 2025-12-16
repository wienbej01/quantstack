#!/usr/bin/env python3
"""Environment validator for historical + live data integrations.

This script does not change trading logic. It performs lightweight checks that:
1) Historical gold data is mounted and accessible for training.
2) Daily SIP outputs are being persisted under data/daily_sip for reuse.
3) Live Polygon + IBKR endpoints are reachable (opt-in flags to avoid unwanted calls).
"""

import argparse
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


GCS_GOLD_PATH = Path("/home/jacobw/gcs-mount/gold/stocks/1m/")
DAILY_SIP_DIR = Path("data/daily_sip")


def check_gold_data() -> bool:
    """Verify historical gold data is mounted and non-empty."""
    if not GCS_GOLD_PATH.exists():
        print(f"❌ Gold path missing: {GCS_GOLD_PATH}")
        return False
    dirs = [p for p in GCS_GOLD_PATH.iterdir() if p.is_dir() and p.name != "1m"]
    if not dirs:
        print(f"❌ No symbol directories found under {GCS_GOLD_PATH}")
        return False
    print(f"✅ Gold data mounted ({len(dirs)} symbols found)")
    return True


def check_daily_sip(date_str: Optional[str] = None) -> bool:
    """Ensure daily SIP outputs exist for the requested date."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    sip_file = DAILY_SIP_DIR / f"sip_universe_{date_str}.txt"
    l2_file = DAILY_SIP_DIR / f"l2_symbols_{date_str}.txt"
    ok = True
    if sip_file.exists():
        count = len([ln for ln in sip_file.read_text().splitlines() if ln.strip()])
        print(f"✅ SIP universe present for {date_str}: {sip_file} ({count} symbols)")
    else:
        print(f"⚠️  SIP universe missing for {date_str}: {sip_file} (run daily_sip_scheduler.py)")
        ok = False
    if l2_file.exists():
        count = len([ln for ln in l2_file.read_text().splitlines() if ln.strip()])
        print(f"✅ L2 symbols present for {date_str}: {l2_file} ({count} symbols)")
    else:
        print(f"⚠️  L2 symbols missing for {date_str}: {l2_file} (run daily_sip_scheduler.py)")
        ok = False
    return ok


def check_polygon_live() -> bool:
    """Optionally verify Polygon connectivity using the AAPL prev endpoint."""
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        print("❌ POLYGON_API_KEY not set")
        return False
    try:
        import requests

        url = "https://api.polygon.io/v2/aggs/ticker/AAPL/prev"
        resp = requests.get(url, params={"apikey": api_key}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "OK":
            print("✅ Polygon live check: success (AAPL prev)")
            return True
        print(f"⚠️  Polygon responded but not OK: {data}")
        return False
    except Exception as exc:  # pragma: no cover - diagnostic only
        print(f"❌ Polygon live check failed: {exc}")
        return False


def check_ibkr_live() -> bool:
    """Optionally verify IBKR connectivity to TWS/Gateway."""
    try:
        from ib_insync import IB

        ib = IB()
        ib.connect("127.0.0.1", 7497, clientId=999, readonly=True, timeout=5)
        if ib.isConnected():
            print("✅ IBKR live check: connected to 127.0.0.1:7497")
            ib.disconnect()
            return True
        print("⚠️  IBKR live check: connect call returned but not connected")
        return False
    except Exception as exc:  # pragma: no cover - diagnostic only
        print(f"❌ IBKR live check failed: {exc}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Validate data integrations (gold, Polygon, IBKR).")
    parser.add_argument("--date", help="Date (YYYY-MM-DD) to check for SIP outputs; defaults to today.")
    parser.add_argument(
        "--check-polygon",
        action="store_true",
        help="Perform live Polygon connectivity check (AAPL prev endpoint).",
    )
    parser.add_argument(
        "--check-ibkr",
        action="store_true",
        help="Perform live IBKR connectivity check to 127.0.0.1:7497.",
    )
    args = parser.parse_args()

    all_ok = True

    all_ok &= check_gold_data()
    all_ok &= check_daily_sip(args.date)

    if args.check_polygon:
        all_ok &= check_polygon_live()
    else:
        print("ℹ️  Skipping Polygon live check (pass --check-polygon to run).")

    if args.check_ibkr:
        all_ok &= check_ibkr_live()
    else:
        print("ℹ️  Skipping IBKR live check (pass --check-ibkr to run).")

    raise SystemExit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
