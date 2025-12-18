#!/usr/bin/env python3
"""Clean up 2025-only data and prepare for complete universe downloads."""

import os
import shutil
import pandas as pd
from pathlib import Path
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def load_action_lists():
    """Load the action lists from the universe analysis."""
    universe_dir = Path("/home/jacobw/quantstack/universe_data")
    
    action_files = {
        'remove_2025_only': universe_dir / 'action_remove_2025_only.csv',
        'download_missing': universe_dir / 'action_download_missing.csv',
        'download_historical': universe_dir / 'action_download_historical.csv',
        'keep_good': universe_dir / 'action_keep_good.csv'
    }
    
    actions = {}
    for action, file_path in action_files.items():
        if file_path.exists():
            df = pd.read_csv(file_path)
            actions[action] = set(df['ticker'].astype(str).str.strip().str.upper())
            logger.info(f"Loaded {len(actions[action])} tickers for: {action}")
        else:
            logger.warning(f"Action file not found: {file_path}")
            actions[action] = set()
    
    return actions

def remove_2025_only_data(tickers_to_remove, dry_run=True):
    """Remove 2025-only ticker directories."""
    logger.info(f"{'DRY RUN: ' if dry_run else ''}Removing 2025-only data...")
    
    gold_root = Path("/home/jacobw/gcs-mount/gold/stocks/1m")
    
    if not gold_root.exists():
        logger.error(f"Gold root not found: {gold_root}")
        return
    
    removed_count = 0
    space_freed = 0
    
    for ticker in tickers_to_remove:
        ticker_path = gold_root / ticker
        
        if ticker_path.exists() and ticker_path.is_dir():
            # Check if it really only has 2025 data
            year_dirs = [d for d in ticker_path.iterdir() if d.is_dir() and d.name.isdigit()]
            years = [int(d.name) for d in year_dirs]
            
            if years == [2025]:
                # Calculate size before removal
                try:
                    size = sum(f.stat().st_size for f in ticker_path.rglob('*') if f.is_file())
                    space_freed += size
                    
                    if not dry_run:
                        shutil.rmtree(ticker_path)
                        logger.debug(f"Removed: {ticker}")
                    else:
                        logger.debug(f"Would remove: {ticker} ({size/1024/1024:.1f} MB)")
                    
                    removed_count += 1
                    
                except Exception as e:
                    logger.error(f"Error processing {ticker}: {e}")
            else:
                logger.warning(f"Ticker {ticker} has years {years}, not removing")
    
    space_freed_gb = space_freed / (1024**3)
    logger.info(f"{'Would remove' if dry_run else 'Removed'} {removed_count} directories")
    logger.info(f"Space {'would be' if dry_run else ''} freed: {space_freed_gb:.2f} GB")
    
    return removed_count, space_freed

def create_download_lists():
    """Create prioritized download lists for the data_download system."""
    logger.info("Creating download lists for data_download system...")
    
    universe_dir = Path("/home/jacobw/quantstack/universe_data")
    download_dir = Path("/home/jacobw/data_download/universe_lists")
    download_dir.mkdir(exist_ok=True)
    
    # Load the action lists
    actions = load_action_lists()
    
    # Priority 1: Completely missing tickers (highest priority)
    priority_1 = actions['download_missing']
    
    # Priority 2: Tickers needing historical data
    priority_2 = actions['download_historical']
    
    # Combined download list
    all_downloads = priority_1 | priority_2
    
    # Save download lists in format expected by data_download system
    pd.DataFrame({'Ticker': sorted(priority_1)}).to_csv(
        download_dir / 'priority_1_missing_tickers.csv', index=False)
    
    pd.DataFrame({'Ticker': sorted(priority_2)}).to_csv(
        download_dir / 'priority_2_historical_tickers.csv', index=False)
    
    pd.DataFrame({'Ticker': sorted(all_downloads)}).to_csv(
        download_dir / 'all_needed_downloads.csv', index=False)
    
    # Create universe file for data_download (R2K format)
    complete_universe = pd.read_csv(universe_dir / 'complete_universe.csv')
    complete_universe.columns = ['Ticker']  # Rename to match R2K format
    complete_universe.to_csv(download_dir / 'complete_universe_r2k_format.csv', index=False)
    
    logger.info(f"Download lists saved to: {download_dir}")
    logger.info(f"Priority 1 (missing): {len(priority_1)} tickers")
    logger.info(f"Priority 2 (historical): {len(priority_2)} tickers")
    logger.info(f"Total downloads needed: {len(all_downloads)} tickers")
    
    return len(all_downloads)

def update_data_download_config():
    """Update the data_download configuration to remove price filters."""
    logger.info("Updating data_download configuration...")
    
    config_path = Path("/home/jacobw/data_download/configs/config.yaml")
    backup_path = Path("/home/jacobw/data_download/configs/config_backup_with_price_filter.yaml")
    
    # Backup original config
    if config_path.exists():
        shutil.copy2(config_path, backup_path)
        logger.info(f"Backed up original config to: {backup_path}")
    
    # Create new config without price filters
    new_config = """# Updated Configuration - No Price Filters
# Full R2K + S&P 500 Universe
lookback_years: 4                    # Download from 2021-01
prefilter_frac_min: 0.0             # REMOVED: No price filtering
month_chunk: "1M"
concurrency: 8

http:
  timeout_sec: 30
  max_retries: 6
  backoff_base_sec: 1.5

paths:
  universe_dir: "/home/jacobw/data_download/universe_lists"
  prefilter_dir: "artefacts/prefilter"
  checkpoints_dir: "artefacts/checkpoints"
  bronze_root: "/home/jacobw/gcs-mount/bronze/stocks/1m"
  silver_root: "/home/jacobw/gcs-mount/silver/stocks/1m"
  gold_root: "/home/jacobw/gcs-mount/gold/stocks/1m"

calendar: "XNYS"
price_band: [0.01, 100000.0]        # REMOVED: Effectively no price limits

polygon:
  api_key_env: "POLYGON_API_KEY"
"""
    
    with open(config_path, 'w') as f:
        f.write(new_config)
    
    logger.info(f"Updated config saved to: {config_path}")

def create_execution_plan():
    """Create execution plan for the complete data update."""
    plan_content = f"""# Complete Universe Data Update Plan
# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Summary
- Total Universe: 2,449 tickers (503 S&P 500 + 1,946 Russell 2000)
- Current Coverage: 44.3% (1,084 tickers with good historical data)
- Downloads Needed: 1,365 tickers
- 2025-only to Remove: 660 directories

## Execution Steps

### Step 1: Clean up 2025-only data
```bash
cd /home/jacobw/quantstack
python3 cleanup_and_prepare_downloads.py --remove-2025-only --confirm
```

### Step 2: Update data_download configuration
- Configuration already updated to remove price filters
- Universe lists created in /home/jacobw/data_download/universe_lists/

### Step 3: Download missing data (Priority 1 - Missing tickers)
```bash
cd /home/jacobw/data_download
# Use priority_1_missing_tickers.csv (705 tickers)
python3 update_r2k_data.py --universe-file universe_lists/priority_1_missing_tickers.csv
```

### Step 4: Download historical data (Priority 2 - Existing tickers)
```bash
cd /home/jacobw/data_download
# Use priority_2_historical_tickers.csv (660 tickers)
python3 update_r2k_data.py --universe-file universe_lists/priority_2_historical_tickers.csv
```

### Step 5: Verify complete coverage
```bash
cd /home/jacobw/quantstack
python3 create_complete_universe.py  # Re-run to verify
```

## Files Created
- /home/jacobw/quantstack/universe_data/: Analysis and universe files
- /home/jacobw/data_download/universe_lists/: Download lists for data_download
- /home/jacobw/data_download/configs/config.yaml: Updated config (no price filters)

## Expected Results
- Complete coverage of R2K + S&P 500 from 2021-01 onwards
- No price filtering restrictions
- Consistent timezone format (ET, no timezone info)
- Proper [ticker]/[yyyy]/[yyyy-mm].parquet structure
"""
    
    plan_path = Path("/home/jacobw/quantstack/EXECUTION_PLAN.md")
    with open(plan_path, 'w') as f:
        f.write(plan_content)
    
    logger.info(f"Execution plan saved to: {plan_path}")

def main():
    """Main execution function."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Clean up and prepare for complete universe downloads')
    parser.add_argument('--remove-2025-only', action='store_true', 
                       help='Remove 2025-only ticker directories')
    parser.add_argument('--confirm', action='store_true',
                       help='Confirm removal (without this, runs in dry-run mode)')
    parser.add_argument('--prepare-only', action='store_true',
                       help='Only prepare download lists, do not remove data')
    
    args = parser.parse_args()
    
    logger.info("Starting cleanup and preparation for complete universe...")
    
    # Load action lists
    actions = load_action_lists()
    
    if args.remove_2025_only and not args.prepare_only:
        # Remove 2025-only data
        dry_run = not args.confirm
        if dry_run:
            logger.info("DRY RUN MODE - Use --confirm to actually remove data")
        
        removed_count, space_freed = remove_2025_only_data(
            actions['remove_2025_only'], dry_run=dry_run)
        
        if dry_run:
            logger.info("Run with --confirm to actually remove the data")
            return
    
    # Create download lists
    total_downloads = create_download_lists()
    
    # Update configuration
    update_data_download_config()
    
    # Create execution plan
    create_execution_plan()
    
    logger.info(f"\n=== PREPARATION COMPLETE ===")
    logger.info(f"Download lists created for {total_downloads} tickers")
    logger.info(f"Configuration updated (price filters removed)")
    logger.info(f"Ready to execute downloads using data_download system")
    logger.info(f"See EXECUTION_PLAN.md for detailed steps")

if __name__ == "__main__":
    main()
