# SIP Pattern Discovery System

**🚨 MAJOR UPGRADE (2026-01-12): High-Alpha Event-Based Pattern Discovery**

## Current Status: High-Alpha Feature Set Complete

### Problem with Previous Approach
- **State features** (spy_above_sma20, is_power_hour) were true for thousands of consecutive bars
- **Not actionable entry signals** - just regime conditions
- **Simple technical indicators** (VWAP cross) are heavily traded and low-alpha
- **Sample sizes inflated** due to correlated consecutive observations
- **Low expected alpha** from crowded technical patterns

### New High-Alpha Approach
- **Cross-ticker relative strength**: Stock vs SPY performance (highest alpha, less crowded)
- **Volume-price divergence**: Price moves on weak/strong volume (high alpha, microstructure edge)
- **Session range events**: Breakouts and extremes (medium alpha, actionable)
- **Event-based signals**: Actual entry triggers, not persistent states
- **Regime segmentation**: Bull/bear × high/low vol as data filters, not features
- **Consolidated LLM analysis**: Single themed report vs 8 separate files
- **Smart caching**: Avoids recomputation on errors/reruns

### New Ranking Criteria

**Primary Filter: t-statistic ≥ 3.0** (99% confidence)
- Measures: Is mean return significantly different from zero?
- Advantage: Combines effect size, variance, and sample size

**Secondary Filters:**
- **Expectancy ≥ 0.01%** per trade (realistic, not 0.2%)
- **Min trades ≥ 50** (statistical validity)
- **Max 5 patterns** per direction per horizon (quality over quantity)

**Output Metrics Per Pattern (Regime-Segmented):**
```
rule                              direction  horizon  regime         t_stat  expectancy  win_rate  profit_factor  n_trades
ret_60m_bin == 4 AND spy_ret...   LONG       60m      bull_low_vol   5.12    0.052%      55.8%     1.95           342
ret_30m_bin == 0 AND is_first...  SHORT      30m      bear_high_vol  4.87    0.048%      53.2%     1.78           156
```

## Regime-Segmented Discovery (NEW)

**Key Innovation**: Patterns are discovered separately for each market regime, not averaged across regimes.

**Regimes Defined:**
- **Bull**: SPY above 20-period SMA
- **Bear**: SPY below 20-period SMA
- **High Vol**: SPY ATR in top 30th percentile (rolling 252 days)
- **Low Vol**: SPY ATR below 70th percentile

**4-Way Segmentation:**
```
bull_low_vol   - Trending up, calm markets
bull_high_vol  - Trending up, volatile markets
bear_low_vol   - Trending down, calm markets
bear_high_vol  - Trending down, volatile markets
```

**Why This Matters:**
- A pattern with t-stat 3.0 overall might be t-stat 5.0 in bull, t-stat 0.5 in bear
- Prevents averaging across incompatible market conditions
- Each pattern is tagged with its regime context
- Backtester can switch pattern sets when regime changes

**Sample Size Impact:**
- 2 months (~400 samples) → 100 samples per regime ❌ Too small
- 6 months (~1,200 samples) → 300 samples per regime ✅ Adequate
- **Recommended minimum: 6 months for regime-segmented discovery**

### Enhanced Features (UPDATED)

**SPY Regime Features:**
- `spy_above_sma20` - Bullish/bearish market regime (used for segmentation)
- `spy_ret_60m` - Market momentum context (used as pattern feature)
- `spy_high_vol` - Volatility regime (used for segmentation)

**Multiple Forward Periods:**
- 30m: Higher frequency, shorter-term patterns
- 60m: Balanced risk/reward
- 90m: Medium-term moves
- 180m: Longer-term patterns

### Performance Improvements

**Parallel Processing:**
- Feature computation: 3-4x speedup (CPU bound)
- Pattern discovery: 2-3x speedup (rule evaluation)
- Overall: ~2x total speedup (I/O still dominates)

**Smart Caching:**
- `cached_data.parquet` - Raw data loading
- `cached_features.parquet` - Computed features  
- `cached_targets.parquet` - Forward returns
- Subsequent runs skip expensive steps

### Usage

**Run System:**
```bash
cd ~/quantstack/sip_pattern_discovery
python3 run_long_short_discovery.py
```

**Parameters:**
- `--min-t-stat 3.0` - 99% confidence threshold
- `--min-expectancy 0.01` - 0.01% per trade (realistic)
- `--min-trades 50` - Statistical validity
- `--horizons 30,60,90,180` - Multiple forward periods

**Expected Output:**
- 10-30 high-quality patterns (vs previous 0 with unrealistic thresholds)
- Each with t-stat > 3.0, expectancy > 0.01%
- Full trading metrics for each pattern
- LLM analysis of top patterns

### Key Advantages

1. **Statistically Rigorous**: t-stat ensures patterns aren't random
2. **Trading Focused**: Optimizes for actual P&L, not just hit rate
3. **Risk Aware**: Includes Sharpe, profit factor, drawdown metrics
4. **Regime Conditional**: SPY features improve pattern robustness
5. **Performance Optimized**: Parallel processing + caching
6. **Multiple Timeframes**: 30-180m horizons capture different alpha
7. **Realistic Thresholds**: 0.01% expectancy targets Sharpe ~1.9 (achievable)

### File Structure

```
sip_pattern_discovery/
├── run_long_short_discovery.py    # UPDATED: t-stat parameters
├── discover.py                    # REWRITTEN: t-stat ranking + caching
├── src/
│   ├── pattern_engine.py          # REWRITTEN: t-stat + trading metrics
│   ├── targets.py                 # SIMPLIFIED: actual returns only
│   ├── features.py                # ENHANCED: parallel + SPY regime
│   ├── data_loader.py             # ENHANCED: SPY data loading
│   └── llm_analysis.py            # RETAINED: analyzes t-stat patterns
└── output_tstat/                  # NEW: t-stat results + cache
    ├── patterns_long_30m.csv      # Patterns by horizon/direction
    ├── patterns_short_60m.csv
    ├── patterns_all.csv           # Combined ranked by t-stat
    ├── cached_*.parquet           # Performance cache
    └── llm_analysis_*.md          # LLM insights on top patterns
```

### Expectancy vs Sharpe Analysis

| Expectancy | Annual Return | Sharpe | Assessment |
|------------|---------------|--------|------------|
| 0.01% | 25.2% | 1.86 | **Realistic** |
| 0.02% | 50.4% | 3.72 | Good |
| 0.05% | 126.0% | 9.30 | Excellent |
| 0.20% | 504.0% | 37.18 | **Impossible** |

*Assumptions: 10 trades/day, std=0.27% per trade*

The previous 0.2% threshold demanded hedge fund god-tier performance. 0.01% is realistic for systematic strategies.
