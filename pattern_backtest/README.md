# T-Stat Pattern Backtest - January 2025

## Overview
Backtest 5 EVENT-based t-statistic ranked patterns from SIP pattern discovery on January 2025 data with segregated reporting and proper exit horizons.

## Top 5 EVENT-Based Strategies
1. **First_Hour_Momentum_180m**: `ret_60m_bin == 4.0 AND is_first_hour_bin == True` (180min exit)
2. **Volume_Price_Divergence_First_Hour_90m**: `price_up_vol_weak_bin == True AND is_first_hour_bin == True` (90min exit)
3. **VWAP_Extreme_First_Hour_90m**: `price_vs_vwap_pct_bin == 4 AND is_first_hour_bin == True` (90min exit)
4. **Extreme_Outperform_Low_Range_180m**: `rel_outperform_extreme_bin == True AND session_range_pct_bin == 0` (180min exit)
5. **Power_Hour_Short_30m**: `is_power_hour_bin == True` (30min exit)

## Key Features
- **EVENT-based patterns**: Time-constrained (first hour, power hour) not persistent states
- **Per-strategy exit horizons**: 30/90/180 minutes based on discovery analysis
- **Position limits**: Max 5 positions per strategy, max 2 new entries per day per strategy
- **Segregated reporting**: Individual performance tracking per strategy
- **Expected volume**: ~10 trades per day (5 strategies × 2 entries/day)

## Usage

### 1. Generate Feature Cache
```bash
cd /home/jacobw/quantstack/pattern_backtest
python3 generate_cache_jan2025.py
```

### 2. Run Backtest
```bash
python3 run_tstat_backtest_jan2025.py
```

## Output Files
- `output/trades_tstat_jan2025.csv` - All trades combined
- `output/trades_{strategy_name}.csv` - Individual strategy trades (5 files)
- `output/summary_tstat_jan2025.json` - Performance summary with correct holding periods

## Configuration
- **Period**: January 1-31, 2025
- **Position Size**: 100 shares per trade
- **Exit Horizons**: 30min (Power Hour), 90min (Volume/VWAP), 180min (Momentum/Extreme)
- **Commission**: $2 per round-turn
- **Position Limits**: 5 concurrent + 2 daily entries per strategy
- **Data Sources**: GCS gold data + SPY regime features + SIP daily lists

## Expected Results
- **Total Trades**: ~230 for the month (10/day × 23 trading days)
- **Holding Periods**: 30/90/180 minutes (not 350+ minutes)
- **Trade Distribution**: Time-constrained events, not persistent state patterns
