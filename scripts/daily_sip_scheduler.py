#!/usr/bin/env python3
"""Daily SIP universe selection - EXACT original methodology."""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def _current_date_str() -> str:
    return datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")


def run_daily_sip_selection():
    """Run daily SIP selection using shared daily_sip JSON artifacts."""

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler("logs/daily_sip.log"), logging.StreamHandler()],
    )
    logger = logging.getLogger(__name__)

    logger.info("=== DAILY SIP SELECTION - SHARED DAILY_SIP JSON ===")

    sip_root = Path(
        os.environ.get("SIP_DAILY_ROOT", "/home/jacobw/intraday_stack/data/daily_sip")
    )
    date_str = _current_date_str()
    sip_file = sip_root / f"date={date_str}" / "sip_universe.json"

    if not sip_file.exists():
        logger.error(f"SIP universe not found: {sip_file}")
        raise RuntimeError("Daily SIP JSON not found")

    start_time = time.time()
    with open(sip_file) as f:
        data = json.load(f)
    artifact_date = data.get("date") if isinstance(data, dict) else None
    if artifact_date and artifact_date != date_str:
        logger.error(
            "SIP artifact date mismatch: file=%s expected=%s",
            artifact_date,
            date_str,
        )
        raise RuntimeError("Daily SIP date mismatch")

    sip_universe = data.get("symbols", []) if isinstance(data, dict) else data

    # Get top 3 NYSE symbols for L2 collection (IBKR LIMIT)
    # IBKR account limitation: Error 309 above 3 concurrent L2 depth subscriptions
    l2_symbols = sip_universe[:3]

    elapsed = time.time() - start_time

    # Save results
    results_dir = Path("data/daily_sip")
    results_dir.mkdir(parents=True, exist_ok=True)

    # Save SIP universe
    sip_file = results_dir / f"sip_universe_{date_str}.txt"
    with open(sip_file, "w") as f:
        f.write("\n".join(sip_universe))

    # Save L2 symbols (top-3 for IBKR limit compliance)
    l2_file = results_dir / f"l2_symbols_{date_str}.txt"
    with open(l2_file, "w") as f:
        f.write("\n".join(l2_symbols))

    # Also run L2 symbol selector for rotation pool and logging
    try:
        from l2_symbol_selector import (
            get_l2_symbols,
            get_rotation_pool,
            log_symbol_selection,
        )

        # Generate rotation pool and detailed logging
        rotation_pool = get_rotation_pool(sip_universe, pool_size=15)
        log_symbol_selection(l2_symbols, sip_universe, rotation_pool)

        logger.info(f"L2 rotation pool: {len(rotation_pool)} symbols")
    except ImportError:
        logger.warning("L2 symbol selector not available - basic L2 file saved only")

    logger.info(f"Shared SIP load complete in {elapsed:.1f}s")
    logger.info(f"NYSE SIP universe: {len(sip_universe)} symbols")
    logger.info(f"L2 symbols: {len(l2_symbols)} symbols")
    logger.info(f"Results saved to {results_dir}")

    return sip_universe, l2_symbols


def load_daily_sip_results(date_str: str = None):
    """Load daily SIP results - NO FALLBACKS."""
    if date_str is None:
        date_str = _current_date_str()
    sip_root = Path(
        os.environ.get("SIP_DAILY_ROOT", "/home/jacobw/intraday_stack/data/daily_sip")
    )
    sip_file = sip_root / f"date={date_str}" / "sip_universe.json"

    if not sip_file.exists():
        return None, None

    with open(sip_file, "r") as f:
        data = json.load(f)
    artifact_date = data.get("date") if isinstance(data, dict) else None
    if artifact_date and artifact_date != date_str:
        logging.getLogger(__name__).warning(
            "SIP artifact date mismatch: file=%s expected=%s",
            artifact_date,
            date_str,
        )
        return None, None

    sip_universe = data.get("symbols", []) if isinstance(data, dict) else data
    l2_symbols = sip_universe[:3]

    return sip_universe, l2_symbols


if __name__ == "__main__":
    sip_universe, l2_symbols = run_daily_sip_selection()

    if sip_universe:
        print(f"✅ NYSE SIP Universe ({len(sip_universe)}): {sip_universe[:5]}...")
        print(f"✅ L2 Symbols ({len(l2_symbols)}): {l2_symbols}")
    else:
        print("❌ Daily SIP selection failed")
        sys.exit(1)
