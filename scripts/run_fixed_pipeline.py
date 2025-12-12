#!/usr/bin/env python3
"""Run complete fixed pipeline: Phase 1-4 implementation."""

import logging
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

def run_script(script_name, description):
    """Run a script and return success status."""
    logging.info(f"\n{'='*60}")
    logging.info(f"PHASE: {description}")
    logging.info(f"{'='*60}")
    
    script_path = Path("scripts") / script_name
    if not script_path.exists():
        logging.error(f"Script not found: {script_path}")
        return False
    
    try:
        result = subprocess.run([sys.executable, str(script_path)], 
                              capture_output=False, text=True, check=True)
        logging.info(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ {description} failed with exit code {e.returncode}")
        return False
    except Exception as e:
        logging.error(f"❌ {description} failed: {e}")
        return False

def main():
    logging.info("=" * 80)
    logging.info("FIXED PIPELINE: Implementing Phases 1-4")
    logging.info("=" * 80)
    logging.info("Phase 1: Timezone normalization + clean features")
    logging.info("Phase 2: Raw price feature removal (included in Phase 1)")
    logging.info("Phase 3: Time-stratified models + morning focus")
    logging.info("Phase 4: Enhanced ICT features (included in Phase 1)")
    
    # Phase 1: Build fixed features (includes Phase 2 & 4)
    success = run_script("build_intraday_features_fixed.py", 
                        "Phase 1: Build timezone-normalized clean features")
    if not success:
        logging.error("Pipeline failed at Phase 1")
        return False
    
    # Validation
    success = run_script("validate_fixed_features.py", 
                        "Validation: Check feature quality")
    if not success:
        logging.error("Pipeline failed at validation")
        return False
    
    # Phase 3: Time-stratified training
    success = run_script("rolling_train_fixed.py", 
                        "Phase 3: Time-stratified training with morning focus")
    if not success:
        logging.error("Pipeline failed at Phase 3")
        return False
    
    logging.info("\n" + "=" * 80)
    logging.info("🎉 FIXED PIPELINE COMPLETED SUCCESSFULLY")
    logging.info("=" * 80)
    logging.info("Results available in:")
    logging.info("  - run/intraday_features_fixed/features.parquet")
    logging.info("  - run/rolling_results_fixed/metrics.csv")
    logging.info("  - run/rolling_results_fixed/trades.csv")
    
    return True

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
