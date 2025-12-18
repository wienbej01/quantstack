# Complete Universe Data Update Plan
# Generated: 2025-12-17 21:26:19

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
