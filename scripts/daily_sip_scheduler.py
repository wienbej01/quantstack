#!/usr/bin/env python3
"""Daily SIP universe selection scheduler - ALL NYSE symbols."""

import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add paths
sys.path.insert(0, "qx-data")

from qx_data.live.polygon_sip import PolygonSIPSelector


def run_daily_sip_selection():
    """Run daily SIP selection and save results."""
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/daily_sip.log'),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger(__name__)
    
    logger.info("=== DAILY SIP SELECTION START ===")
    
    # Check API key
    if not os.getenv('POLYGON_API_KEY'):
        logger.error("POLYGON_API_KEY not set")
        return None, None
    
    try:
        # Initialize SIP selector
        sip_selector = PolygonSIPSelector()
        
        # Get ALL NYSE symbols that pass SIP scoring
        start_time = time.time()
        sip_universe = sip_selector.get_sip_universe(min_score=0.01)  # Use correct parameter
        
        # Get top 6 NYSE symbols for L2 collection
        l2_symbols = sip_selector.get_nyse_symbols(sip_universe)
        
        elapsed = time.time() - start_time
        
        # Save results
        date_str = datetime.now().strftime('%Y-%m-%d')
        results_dir = Path('data/daily_sip')
        results_dir.mkdir(parents=True, exist_ok=True)
        
        # Save SIP universe (ALL NYSE symbols)
        sip_file = results_dir / f'sip_universe_{date_str}.txt'
        with open(sip_file, 'w') as f:
            f.write('\n'.join(sip_universe))
        
        # Save L2 symbols (top 6)
        l2_file = results_dir / f'l2_symbols_{date_str}.txt'
        with open(l2_file, 'w') as f:
            f.write('\n'.join(l2_symbols))
        
        logger.info(f"SIP selection complete in {elapsed:.1f}s")
        logger.info(f"NYSE SIP universe: {len(sip_universe)} symbols")
        logger.info(f"L2 symbols: {len(l2_symbols)} symbols")
        logger.info(f"Results saved to {results_dir}")
        
        return sip_universe, l2_symbols
        
    except Exception as e:
        logger.error(f"Daily SIP selection failed: {e}")
        return None, None


def load_daily_sip_results(date_str: str = None):
    """Load daily SIP results from file."""
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')
    
    results_dir = Path('data/daily_sip')
    
    try:
        # Load SIP universe
        sip_file = results_dir / f'sip_universe_{date_str}.txt'
        with open(sip_file, 'r') as f:
            sip_universe = [line.strip() for line in f if line.strip()]
        
        # Load L2 symbols
        l2_file = results_dir / f'l2_symbols_{date_str}.txt'
        with open(l2_file, 'r') as f:
            l2_symbols = [line.strip() for line in f if line.strip()]
        
        return sip_universe, l2_symbols
        
    except FileNotFoundError:
        return None, None


if __name__ == "__main__":
    sip_universe, l2_symbols = run_daily_sip_selection()
    
    if sip_universe:
        print(f"✅ NYSE SIP Universe ({len(sip_universe)}): {sip_universe[:5]}...")
        print(f"✅ L2 Symbols ({len(l2_symbols)}): {l2_symbols}")
    else:
        print("❌ Daily SIP selection failed")
        sys.exit(1)
