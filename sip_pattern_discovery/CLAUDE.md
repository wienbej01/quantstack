# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SIP Pattern Discovery is a **statistical pattern discovery system** for intraday equity trading. It finds statistically significant trading rules by:
1. Loading SIP-filtered 1-minute bar data from Gold data
2. Computing high-alpha features (relative strength, volume-price divergence, session range)
3. Running event-based pattern discovery with t-statistic ranking
4. Applying AAA (Anti-Overfitting, Actionable, Adaptable) filters
5. Validating patterns across 3 temporal periods (scan, validation, OOS)

**Key innovation:** Patterns are discovered **separately for each market regime** (bull/bear × high/low volatility) rather than averaged across conditions.

## Common Commands

### Run Pattern Discovery (t-stat ranking)
```bash
cd ~/quantstack/sip_pattern_discovery
python3 run_long_short_discovery.py
```

### Run AAA Discovery (with overfitting filters + 3-period validation)
```bash
python3 run_aaa_discovery_wrapper.py --start-date 2024-06-01 --end-date 2024-08-31
```

### Run Discovery Directly
```bash
python3 discover.py \
  --start-date 2024-06-01 \
  --end-date 2024-07-31 \
  --horizons 30,60,90,180 \
  --min-t-stat 3.0 \
  --min-expectancy 0.01 \
  --min-trades 50 \
  --output-dir output_tstat
```

### Run Tests
```bash
cd ~/quantstack  # Tests require parent directory pythonpath
pytest -q sip_pattern_discovery/test_aaa_quick.py
```

### Run Specific Test
```bash
pytest -q sip_pattern_discovery/test_aaa_quick.py::test_feature_computation
```

## Architecture

### Data Pipeline
```
Gold 1m bars (/home/jacobw/gcs-mount/gold/stocks/1m/)
    ↓ SIP universe filter (from intraday_stack/data/daily_sip/)
    ↓ Load with lookback for feature warmup
    ↓ Compute features (parallel, cached)
    ↓ Generate forward return targets
    ↓ Regime segmentation (bull/bear × vol)
    ↓ Pattern discovery (t-stat ranking)
    ↓ AAA filters (overfit, event, regime)
    ↓ 3-period validation (scan/val/OOS)
    ↓ Output: patterns_*.csv, llm_analysis_*.md
```

### Source Modules (`src/`)

| Module | Purpose |
|--------|---------|
| `data_loader.py` | Load SIP-filtered Gold data with streaming write to avoid memory explosion |
| `features.py` | Compute high-alpha features (momentum, VWAP, volume, ATR, session, relative strength, SPY regime) |
| `targets.py` | Generate forward return targets (30m, 60m, 90m, 120m, 180m) |
| `pattern_engine.py` | Discover patterns via discretization + t-stat ranking (memory-optimized) |
| `overfitting_filter.py` | Reject patterns with extreme metrics (WR > 65%, Sharpe > 3.0) |
| `event_filter.py` | Require event-based patterns (time-constrained vs persistent states) |
| `regime_filter.py` | Detect market regime (bull/bear × vol) from SPY |
| `temporal_split.py` | Split data into scan/validation/OOS periods |
| `validation_gate.py` | Check pattern degradation between periods |
| `validation_backtest.py` | Validate patterns on holdout data |
| `aaa_scorer.py` | Composite ranking favoring moderate metrics over extremes |
| `llm_analysis.py` | Generate LLM analysis of discovered patterns |

### Entry Points

| Script | Purpose |
|--------|---------|
| `discover.py` | Basic pattern discovery with t-stat ranking |
| `run_long_short_discovery.py` | Wrapper for discover.py with default parameters |
| `discover_aaa.py` | AAA discovery with overfitting filters + 3-period validation |
| `run_aaa_discovery_wrapper.py` | Wrapper for discover_aaa.py |

### Configuration

Configuration is YAML-based in `config/aaa_config.yaml`:
- `aaa_criteria`: Overfitting thresholds (max_win_rate, max_sharpe, max_expectancy)
- `temporal_periods`: Data split (scan_months, validation_months, oos_months)
- `validation_gates`: Degradation limits between periods
- `regime_detection`: SPY regime parameters (SMA period, vol threshold)
- `deployment`: Production limits (max_strategies, position sizing)

### High-Alpha Features (Actionable Entry Signals)

**Cross-ticker relative strength** (HIGHEST alpha):
- `rel_underperform_extreme`: Stock underperforming SPY by >1%
- `rel_outperform_extreme`: Stock outperforming SPY by >1%

**Volume-price divergence** (HIGH alpha):
- `price_up_vol_weak`: Price up but volume weak = bearish divergence
- `price_down_vol_weak`: Price down but volume weak = bullish divergence
- `price_up_vol_strong`: Price up on strong volume = bullish confirmation
- `price_down_vol_strong`: Price down on strong volume = bearish confirmation

**Session range** (MEDIUM alpha):
- `at_session_high`: At session high = potential mean reversion
- `at_session_low`: At session low = potential mean reversion
- `new_session_high`: Breaking session high = continuation
- `new_session_low`: Breaking session low = continuation

**VWAP crosses** (MEDIUM alpha):
- `vwap_cross_up`, `vwap_cross_down`: 30-period VWAP crosses
- `avwap_cross_up`, `avwap_cross_down`: Session AVWAP crosses

**State features** (for context, discretized into bins):
- `ret_60m`: Recent momentum
- `rel_strength_60m`: Relative strength vs SPY
- `session_range_pct`: Position in session range
- `rvol`: Relative volume (time-of-day normalized)
- `atr_14`: Volatility
- `price_vs_vwap_pct`: Distance from VWAP

### Memory Optimization

The system is optimized for 36GB systems:
- **Streaming write:** Data loaded day-by-day, written to temp files, then concatenated
- **Descriptor-based rules:** Rule generation returns descriptors, not boolean Series
- **On-the-fly masks:** Boolean masks created during evaluation, discarded immediately
- **Temporal split to disk:** Validation/OOS data written to disk, loaded per regime
- **Default n_workers=1:** Parallel workers disabled by default to avoid memory duplication

### Caching Strategy

Three cache files in output directory:
- `cached_data.parquet`: Raw SIP-filtered data
- `cached_features.parquet`: Computed features
- `cached_targets.parquet`: Forward returns
- `cached_spy_data.parquet`: SPY data for regime features
- `cached_metadata.json`: Metadata and symbol dates

Delete cache files to force recomputation:
```bash
rm output_tstat/cached_*.parquet output_tstat/cached_metadata.json
```

### Regime-Segmented Discovery

Patterns are discovered separately for 4 regimes:
- `bull_low_vol`: Trending up, calm markets
- `bull_high_vol`: Trending up, volatile markets
- `bear_low_vol`: Trending down, calm markets
- `bear_high_vol`: Trending down, volatile markets

**Regime definition:**
- **Bull:** SPY above 20-period SMA
- **Bear:** SPY below 20-period SMA
- **High Vol:** SPY ATR in top 30th percentile (rolling 252 days)
- **Low Vol:** SPY ATR below 70th percentile

**Why this matters:** A pattern with t-stat 3.0 overall might be t-stat 5.0 in bull, t-stat 0.5 in bear. Regime segmentation prevents averaging across incompatible conditions.

### Ranking Metrics

**Primary:** t-statistic (statistical significance)
- t-stat ≥ 3.0 = 99% confidence that mean return ≠ 0

**Secondary:**
- `expectancy`: Mean return per trade (%)
- `win_rate`: Percentage of profitable trades
- `profit_factor`: Gross profit / gross loss
- `sharpe`: Annualized Sharpe ratio
- `n_samples`: Bar-level observations

**AAA Score** (alternative ranking):
- Composite score favoring moderate metrics over extremes
- Penalizes overfit patterns (WR > 65%, Sharpe > 3.0)
- Rewards large sample sizes
- Regime match bonus

### Output Files

**Pattern CSVs** (one per direction, horizon, regime):
- `patterns_long_30m_bull_low_vol.csv`
- `patterns_short_60m_bear_high_vol.csv`
- `patterns_all_aaa.csv`: Consolidated, ranked by t-stat or AAA score

**Analysis:**
- `llm_analysis_aaa.md`: LLM analysis of top patterns
- `llm_analysis_consolidated.md`: Single themed report (preferred)
- `discovery_metadata.json`: Run parameters and results

## Data Paths

- **SIP universe:** `/home/jacobw/intraday_stack/data/daily_sip/`
- **Gold data:** `/home/jacobw/gcs-mount/gold/stocks/1m/`
- **Project root:** `/home/jacobw/quantstack/sip_pattern_discovery`

## Key Constraints

1. **No synthetic/mock data** for performance reporting - use real Gold data only
2. **Minimum 6 months** of data for regime-segmented discovery (100+ samples per regime)
3. **Event-based patterns only** - no persistent state conditions as entry signals
4. **Memory cap:** System optimized for 36GB, uses ~15GB during discovery
5. **Regime-aware:** Patterns discovered separately per regime, not averaged

## Python Path

Tests require adding parent directory to pythonpath:
```bash
cd ~/quantstack
pytest -q sip_pattern_discovery/tests/
```

The `pytest.ini` in the project root sets:
```
[pytest]
testpaths = tests
pythonpath = /home/jacobw/quantstack
```
