# T-Stat Pattern Backtest - January 2025

## Overview
Backtest the top 5 t-statistic ranked patterns from SIP pattern discovery on January 2025 data with segregated reporting.

## Top 5 Strategies
1. **Low_Volatility_180m**: `atr_14_bin == 0` (t-stat: 49.03, expectancy: 1.78%)
2. **Session_Range_High_180m**: `session_range_pct_bin == 4` (t-stat: 38.75, expectancy: 2.15%)  
3. **Low_Volume_180m**: `rvol_bin == 0` (t-stat: 38.66, expectancy: 1.81%)
4. **Relative_Strength_Session_Range_180m**: `rel_strength_60m_bin == 0.0 AND session_range_pct_bin == 4` (t-stat: 35.86, expectancy: 4.11%)
5. **Extreme_Outperform_Low_Range_180m**: `rel_outperform_extreme_bin == True AND session_range_pct_bin == 0` (t-stat: 35.56, expectancy: 31.59%)

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
- `output/trades_{strategy_name}.csv` - Individual strategy trades
- `output/summary_tstat_jan2025.json` - Performance summary
- `output/metrics_{strategy_name}.json` - Individual strategy metrics

## Configuration
- **Period**: January 1-31, 2025
- **Position Size**: 100 shares per trade
- **Exit Horizon**: 180 minutes (3 hours)
- **Commission**: $2 per round-turn
- **Data Sources**: GCS gold data + SIP daily lists
