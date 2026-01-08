#!/usr/bin/env python3
"""Inspect SIP membership from shared daily_sip JSON artifacts."""

import argparse
import json
import logging
import os
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def _sip_daily_root() -> Path:
    return Path(
        os.environ.get("SIP_DAILY_ROOT", "/home/jacobw/intraday_stack/data/daily_sip")
    )


def _latest_sip_date(root: Path) -> str | None:
    date_dirs = sorted(root.glob("date=*"))
    if not date_dirs:
        return None
    return date_dirs[-1].name.split("date=")[-1]


def main():
    parser = argparse.ArgumentParser(
        description="Inspect SIP membership from daily_sip JSON"
    )
    parser.add_argument("--date", help="Date YYYY-MM-DD (default: latest)")
    args = parser.parse_args()

    root = _sip_daily_root()
    date_str = (
        args.date or _latest_sip_date(root) or datetime.now().strftime("%Y-%m-%d")
    )
    sip_file = root / f"date={date_str}" / "sip_universe.json"

    logging.info("=" * 80)
    logging.info("LOADING SIP MEMBERSHIP FROM DAILY_SIP JSON")
    logging.info("=" * 80)
    logging.info(f"File: {sip_file}")

    if not sip_file.exists():
        raise SystemExit(f"SIP file not found: {sip_file}")

    with open(sip_file) as f:
        data = json.load(f)

    symbols = data.get("symbols", []) if isinstance(data, dict) else data
    scores = data.get("scores", {}) if isinstance(data, dict) else {}

    logging.info(f"Selected {len(symbols)} symbols:")
    for i, symbol in enumerate(symbols[:10], start=1):
        score = scores.get(symbol)
        if score is not None:
            logging.info(f"  {i:2d}. {symbol}: {score:.4f}")
        else:
            logging.info(f"  {i:2d}. {symbol}")

    if len(symbols) > 10:
        logging.info(f"  ... and {len(symbols) - 10} more")


if __name__ == "__main__":
    main()
