#!/usr/bin/env python3
"""Daily SIP universe selection - EXACT original methodology."""

import sys
from pathlib import Path

# Add paths FIRST
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root / "qx-data" / "src"))

import logging
import os
import time
from datetime import datetime

from qx_data.live.polygon_sip import PolygonSIPSelector


def run_daily_sip_selection():
    """Run daily SIP selection - EXACT original methodology."""

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler("logs/daily_sip.log"), logging.StreamHandler()],
    )
    logger = logging.getLogger(__name__)

    logger.info("=== DAILY SIP SELECTION - EXACT ORIGINAL METHODOLOGY ===")

    # Check API key
    if not os.getenv("POLYGON_API_KEY"):
        raise RuntimeError("POLYGON_API_KEY not set")

    # Initialize SIP selector
    sip_selector = PolygonSIPSelector()

    # Get NYSE SIP universe using EXACT original parameters
    start_time = time.time()
    sip_universe = sip_selector.get_sip_universe(top_k=40, score_floor=0.0)

    # Get top 3 NYSE symbols for L2 collection (IBKR LIMIT)
    # IBKR account limitation: Error 309 above 3 concurrent L2 depth subscriptions
    l2_symbols = sip_selector.get_nyse_symbols(sip_universe, max_symbols=3)

    elapsed = time.time() - start_time

    # Save results
    date_str = datetime.now().strftime("%Y-%m-%d")
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
        from l2_symbol_selector import get_l2_symbols, get_rotation_pool, log_symbol_selection
        
        # Generate rotation pool and detailed logging
        rotation_pool = get_rotation_pool(sip_universe, pool_size=15)
        log_symbol_selection(l2_symbols, sip_universe, rotation_pool)
        
        logger.info(f"L2 rotation pool: {len(rotation_pool)} symbols")
    except ImportError:
        logger.warning("L2 symbol selector not available - basic L2 file saved only")

    logger.info(f"ORIGINAL SIP methodology complete in {elapsed:.1f}s")
    logger.info(f"NYSE SIP universe: {len(sip_universe)} symbols")
    logger.info(f"L2 symbols: {len(l2_symbols)} symbols")
    logger.info(f"Results saved to {results_dir}")

    return sip_universe, l2_symbols


def load_daily_sip_results(date_str: str = None):
    """Load daily SIP results - NO FALLBACKS."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    results_dir = Path("data/daily_sip")

    # Load SIP universe
    sip_file = results_dir / f"sip_universe_{date_str}.txt"
    if not sip_file.exists():
        return None, None

    with open(sip_file, "r") as f:
        sip_universe = [line.strip() for line in f if line.strip()]

    # Load L2 symbols
    l2_file = results_dir / f"l2_symbols_{date_str}.txt"
    if not l2_file.exists():
        return None, None

    with open(l2_file, "r") as f:
        l2_symbols = [line.strip() for line in f if line.strip()]

    return sip_universe, l2_symbols


if __name__ == "__main__":
    sip_universe, l2_symbols = run_daily_sip_selection()

    if sip_universe:
        print(f"✅ NYSE SIP Universe ({len(sip_universe)}): {sip_universe[:5]}...")
        print(f"✅ L2 Symbols ({len(l2_symbols)}): {l2_symbols}")
    else:
        print("❌ Daily SIP selection failed")
        sys.exit(1)
