# quantstack

A modular, framework-agnostic trading system with configurable universe selection, backtesting, and experiment orchestration.

## Latest: SIP Pattern Discovery & Backtest System (2026-01-11)

**✅ PATTERN DISCOVERY SYSTEM: High-quality long/short pattern identification**  
**✅ OVERNIGHT HOLD BACKTESTING: Proper 180-bar exit logic with pattern attribution**  
**✅ LONG/SHORT DISCOVERY: Finds profitable opportunities in both directions**  
**✅ QUALITY FILTERS: Min 3.0x lift, max 10 patterns per direction**  
**✅ LLM ANALYSIS: Enhanced prompts for high-quality, low-frequency patterns**  

### SIP Pattern Discovery System (NEW)

**Location:** `/home/jacobw/quantstack/sip_pattern_discovery/`

Discovers high-lift trading patterns from SIP-filtered 1-minute data using statistical analysis and LLM interpretation.

**Key Features:**
- **Dual Direction**: Finds both LONG and SHORT opportunities
- **Quality Focus**: Min 3.0x lift, highly significant patterns only
- **Pattern Attribution**: Each trade tagged with originating pattern
- **Overnight Holds**: 180-minute horizon spans overnight (power hour → next day noon)
- **LLM Analysis**: Claude/GPT analysis with Go/No-go decisions

**Usage:**
```bash
cd /home/jacobw/quantstack/sip_pattern_discovery

# High-quality long/short discovery
.venv/bin/python3 run_long_short_discovery.py

# Output: Top 10 long + 10 short patterns with >3x lift
```

### Pattern Backtest System (NEW)

**Location:** `/home/jacobw/quantstack/pattern_backtest/`

Validates discovered patterns using qx-backtest framework with proper overnight hold logic.

**Key Features:**
- **Per-Pattern Performance**: Separate metrics for each pattern
- **Consolidated Reporting**: Overall performance across all patterns
- **Overnight Validation**: Proper 180-bar exit logic (power hour → next day noon)
- **No Overtrading**: Prevents duplicate orders, tracks pending positions
- **Method Tracking**: All trades tagged with method_id for comparison

**Usage:**
```bash
cd /home/jacobw/quantstack/pattern_backtest

# Clean backtest with proper exit logic
.venv/bin/python3 test_clean_180m.py

# Output: Per-pattern + consolidated performance
```

### Manual Pattern Implementation (EXAMPLE)

**Implemented Patterns from 180m LLM Analysis:**
- **Pattern 1**: High ATR + Power Hour (5.86x lift, 2.30% support)
- **Pattern 2**: Strong 60m momentum + Power Hour (5.40x lift, 2.59% support)  
- **Pattern 15**: Elevated volume + Power Hour (4.02x lift, 3.76% support)

**All patterns are LONG ONLY** - power hour momentum continuation overnight.

**Files:**
- `src/manual_patterns.py` - Pattern definitions and evaluators
- `src/manual_pattern_policy.py` - qx-backtest Policy implementation
- `MANUAL_PATTERNS.md` - Documentation and rationale

### Discovery Quality Filters

**Statistical Criteria:**
- **Min Lift**: 3.0x (exceptional patterns only)
- **Min Support**: 1.0% (sufficient frequency)
- **Max P-value**: 0.001 (highly significant)
- **Max Patterns**: 10 per direction (top performers)

**LLM Quality Assessment:**
- Focus on quality over quantity
- Reject overtrading patterns
- Prioritize exceptional lift (>4x preferred)
- Weight alpha potential 40%
- Explicit anti-overtrading instructions

### Data Pipeline

```
Gold 1m Data (GCS Mount)
    ↓
SIP Daily Filtering (40 symbols/day)
    ↓
Feature Computation (VWAP, RVOL, ATR, momentum, session anchors)
    ↓
Pattern Discovery (Long + Short, 3.0x+ lift)
    ↓
LLM Analysis (Go/No-go decisions)
    ↓
Backtest Validation (Overnight holds, per-pattern performance)
```

### File Structure

```
quantstack/
├── sip_pattern_discovery/          # Pattern discovery system
│   ├── src/
│   │   ├── data_loader.py          # SIP-filtered gold data loading
│   │   ├── features.py             # Feature computation (VWAP, RVOL, etc.)
│   │   ├── targets.py              # Forward return targets (up/down)
│   │   ├── pattern_engine.py       # Statistical pattern discovery
│   │   └── llm_analysis.py         # LLM interpretation
│   ├── discover.py                 # Main discovery CLI
│   ├── run_long_short_discovery.py # High-quality long/short discovery
│   └── output_high_quality/        # Discovery results
│
├── pattern_backtest/               # Pattern validation system
│   ├── src/
│   │   ├── pattern_parser.py       # CSV pattern loading
│   │   ├── rule_evaluator.py       # Pattern condition evaluation
│   │   ├── feature_pipeline.py     # Feature computation + discretization
│   │   ├── manual_patterns.py      # Hand-coded pattern implementations
│   │   └── manual_pattern_policy.py # qx-backtest Policy
│   ├── test_clean_180m.py          # Clean backtest implementation
│   ├── cache/                      # Data caching for fast reload
│   └── output/                     # Backtest results
│
└── [existing systems...]          # Live trading, L2 collection, etc.
```

### Quick Start: Pattern Discovery & Validation

```bash
# 1. Discover high-quality long/short patterns (45 min)
cd /home/jacobw/quantstack/sip_pattern_discovery
.venv/bin/python3 run_long_short_discovery.py

# 2. Validate patterns with overnight holds
cd /home/jacobw/quantstack/pattern_backtest  
.venv/bin/python3 test_clean_180m.py

# 3. Review results
cat output/summary_clean_180m.json
```

### Key Insights: Overnight Hold Strategy

**Critical Discovery**: 180-minute patterns from power hour are **overnight hold strategies**:

- **Entry**: 3:00-4:00 PM (power hour)
- **Market Close**: 4:00 PM (30 minutes later)
- **Overnight Gap**: 15.5 hours
- **Exit**: Next day ~12:00 PM (180 bars from entry)
- **Total Duration**: ~20 calendar hours

**This captures:**
- End-of-day institutional positioning
- Overnight gap continuation
- Next-morning follow-through
- Multi-session momentum

**Risk Considerations:**
- Overnight gap risk
- News/earnings exposure
- Extended holding period
- Margin requirements

---

## Previous: Production SIP & Trading System (2026-01-09)

[Previous content remains unchanged...]

### Critical Fixes (2026-01-09)
- **Async Event Loop Bug**: Fixed `ib_insync` threading issue - wrapped async calls with `util.run()`
- **Timezone Hell**: All trading services now use `TZ=America/New_York` in systemd units
- **Pre-Flight Testing**: New timer at 20:00 Manila (7:00 AM ET) validates system before market prep
- **NTFY Spam Fix**: Health monitor only runs during market hours, only alerts on failures
- **E2E Validation**: Comprehensive test suite validates all 47 critical system interactions
- **Root Cause**: Jan 8 failure due to async/threading bug + timezone confusion (13-hour offset)
- **Documentation**: Added [TIMEZONE_GUIDE.md](docs/TIMEZONE_GUIDE.md) and updated forensic audit
- **Hardcoded Universe Fix**: Removed `nyse_gold_tickers.txt` - all SIP generation now uses full gold data (1796 symbols)
- **IBKR API Settings**: Documented that TWS AND Gateway both need API settings configured (see [IBKR_GATEWAY_STARTUP.md](docs/IBKR_GATEWAY_STARTUP.md))
- **Health Monitor Enhancement**: Now detects CRITICAL errors in logs, not just service status
- **Client ID Conflict Fix**: Changed preflight to use unique client ID (998)
- **Lessons Learned**: Comprehensive resilience guide at [LESSONS_LEARNED_2026-01-09.md](docs/LESSONS_LEARNED_2026-01-09.md)

### Timer Schedule (Manila Time)
| Timer | Manila | ET | Purpose | NTFY Behavior |
|-------|--------|-----|---------|---------------|
| **preflight-check** | **20:00** | **07:00 AM** | **Pre-flight validation** | **Alert on failure only** |
| trading-orchestrator | 21:00 | 08:00 AM | SIP generation | Status updates |
| intraday-sip | 21:45 | 08:45 AM | SIP refresh | - |
| l2-collector | 22:25 | 09:25 AM | Start L2 collection | - |
| intraday-paper | 22:25 | 09:25 AM | Start paper trading | - |
| system-health-monitor | Every 5min | Every 5min | Health checks | **Issues only (market hours)** |

### Validation Scripts
```bash
# Pre-flight (lightweight, runs automatically at 20:00 Manila)
python scripts/preflight_check.py

# Comprehensive validation (run manually before major changes)
python scripts/definitive_e2e_test.py

# Quick service check
python scripts/validate_all_components.py
```

### Timezone Configuration (CRITICAL)
- **System Timezone**: Manila (UTC+8) - DO NOT CHANGE
- **Service Timezone**: America/New_York (ET) - Set in systemd units
- **Market Hours in Manila**: 22:30 PM → 05:00 AM next day (winter)
- **Debugging**: Always convert Manila timestamps to ET when analyzing trading
- **See**: [docs/TIMEZONE_GUIDE.md](docs/TIMEZONE_GUIDE.md) for complete reference

### Gateway Monitoring Enhancement (2026-01-09)
- **Duplicate Detection**: Orchestrator detects multiple IBKR Gateway processes
- **Docker Conflict Resolution**: Removed conflicting `jacobw-ib-gateway-1` container
- **NTFY Alerts**: Gateway conflicts reported via `jacobw-trading-alerts`
- **Process Validation**: Ensures single gateway instance on port 7497
- **L2 Collection**: Restored after Docker container removal (BE, F, ACHR active)

### Orchestrator Validation (2026-01-09)
- **Sequence Control**: ✅ Pre-market sequence: Gateway check → SIP generation → Service monitoring → Trade/L2 status
- **Service Monitoring**: ⚠️ Monitors but doesn't start services (l2-collector, l2-scalping, intraday-paper, l2-watchdog)
- **Ongoing Monitoring**: ✅ Systemd status checks, journalctl error scanning, L2 collection stats
- **Full Audit Trail**: ✅ JSON audit logs to `logs/orchestrator_audit.log` with timestamps, operations, status
- **NTFY Reporting**: ✅ All 4 topics active (status, alerts, data, trades) - no silent failures
- **Timer Schedule**: Runs daily at 8:00 AM ET via `trading-orchestrator.timer`

### Systemd Service Fixes (2026-01-09)
- **Timezone Fix**: Added `TZ=America/New_York` to all trading services
- **API Compatibility**: Fixed deprecated `fillEvent` → `execDetailsEvent` in l2-scalping
- **Service Status**: All services now running with proper ET time detection
- **Client IDs**: l2-scalping (10,11), l2-collector (521) - no conflicts

### Systemd Services
| Service | Purpose | Status |
|---------|---------|--------|
| `trading-orchestrator.timer` | Pre-market SIP generation | 8:00 AM ET |
| `l2-collector.service` | L2 data collection | Running |
| `l2-scalping.service` | L2-based scalping trades | Running |
| `l2-watchdog.service` | Service health monitoring | Running |
| `intraday-paper.service` | Paper trading execution | Timer-triggered |

### SIP Configuration
- **Data Source**: Polygon (live delayed data)
- **Score Floor**: 0.70 (targets ~20 tickers)
- **Price Range**: $2-200
- **Min Dollar Volume**: $5M
- **Output**: `/home/jacobw/intraday_stack/data/daily_sip/date=YYYY-MM-DD/sip_universe.json`

### Quick Start
```bash
# Check all services
systemctl status l2-collector l2-scalping l2-watchdog intraday-paper

# View orchestrator logs
tail -f logs/orchestrator.log

# View audit trail
tail -f logs/orchestrator_audit.log

# Manual SIP generation
python bulletproof_orchestrator.py

# Check today's SIP universe
cat /home/jacobw/intraday_stack/data/daily_sip/date=$(date +%F)/sip_universe.json | jq '.symbols[:10]'

# Trading performance report
python scripts/trading_report.py --date $(date +%F)

# Export trades to CSV
python scripts/trading_report.py --date $(date +%F) --export trades_today.csv
```

### NTFY Notifications

Real-time trade notifications sent to your phone via NTFY:

**Channels:**
- `jacobw-trading-status`: System status updates
- `jacobw-trading-alerts`: Errors and failures  
- `jacobw-trading-trades`: **Trade executions and exits with P&L**

**Trade Notifications:**
- Entry: Symbol, direction, price, quantity, system
- Exit: Symbol, P&L, exit reason (TARGET/STOP/EXIT), system

**Subscribe on your phone:**
```
https://ntfy.sh/jacobw-trading-trades
https://ntfy.sh/jacobw-trading-alerts
https://ntfy.sh/jacobw-trading-status
```

### Trade Journal & Performance Analysis

All trades are logged to SQLite database at `/home/jacobw/intraday_stack/data/journal/events.db` with:
- **System tracking**: Identifies which system made each trade (intraday-paper, l2-scalping)
- **Strategy tracking**: Records strategy name (reversal, scalping, etc.)
- **Full audit trail**: Entry/exit prices, fills, commissions, P&L
- **Per-system reports**: Separate performance metrics for each trading system

**Generate Reports:**
```bash
# Today's performance by system
python scripts/trading_report.py --date $(date +%F)

# All-time performance
python scripts/trading_report.py

# Export to CSV for analysis
python scripts/trading_report.py --date $(date +%F) --export trades_today.csv

# Filter by strategy
python scripts/trading_report.py --strategy reversal
```

**Report Output:**
- Total trades, open/closed breakdown
- Per-system performance (intraday-paper vs l2-scalping)
- Win rate, P&L, commission by strategy
- Trade-by-trade audit with entry/exit details

---

## Previous: Production-Ready Live Trading System (2025-12-21)

### Phase 1 & 2 Implementation Complete

The critical mock data issue has been fixed AND system upgraded to 1-minute trading.

**Phase 1 Changes:**
- ✅ Created `IBKRMarketDataManager` for real-time data
- ✅ Updated ML predictor with 11 cross-sectional features
- ✅ Removed mock data from live trading system (line 207)
- ✅ Integrated real-time streaming and historical bars

**Phase 2 Changes:**
- ✅ Created `PerformanceMonitor` for cycle timing
- ✅ Optimized feature computation (parallel + vectorized)
- ✅ Upgraded trading frequency from 5 minutes to 1 minute
- ✅ Added performance monitoring and timeout detection

**Test Before Deploy:**
```bash
# Test Phase 1 (real data)
python scripts/test_phase1_real_data.py

# Test Phase 2 (1-minute trading)
python scripts/test_phase2_1min_trading.py
```

**Expected Performance:**
- Trading frequency: Every 1 minute (390 opportunities/day)
- Cycle latency: 15-20 seconds
- Skip rate: <5%

**See**: [LIVE_TRADING_UPGRADE_PLAN.md](LIVE_TRADING_UPGRADE_PLAN.md) for full details.

**Status**: Both phases complete, ready for production testing.

### System Status
- ✅ **Live Trading**: Running on IBKR paper account with production reliability
- ✅ **Multi-Session SIP**: Prior day + overnight + premarket data integration  
- ✅ **API Resilience**: Polygon retry logic with exponential backoff
- ✅ **Auto-Recovery**: IBKR Gateway and L2 collector automatic restart
- ✅ **System Persistence**: All services enabled for autostart across reboots
- ✅ **Price Range**: Expanded to $2-200 for broader universe coverage
- ✅ **Notifications**: Real-time system status via ntfy (iPhone compatible)
- ✅ **Scheduling**: Daily SIP generation at 8:00 AM ET via systemd timer

### Quick Start
```bash
# Check live system status
tail -f logs/live_trading.log

# Retrain regime-aware models
python scripts/train_and_save_regime_models.py

# Run regime-aware backtest
python scripts/regime_aware_strategy.py

# Regenerate daily SIP universe
python /home/jacobw/intraday_stack/scripts/generate_daily_sip_universe.py --date $(date +%F)

# Start/restart live system
./start_live_system.sh
```

### Performance Summary (2024)
| Approach | Return | Win Rate | Max DD | Trades |
|----------|--------|----------|--------|--------|
| **Regime-aware (11 features)** | **+13.0%** | 49.7% | -19.6% | 5,142 |
| Validation (30 days) | +1.3% | 50.0% | N/A | 321 |

### Model Training Details
| Regime | Samples | Top Feature | Importance |
|--------|---------|-------------|------------|
| Bull | 4,588 | sector_momentum | 0.334 |
| Bear | 3,303 | sector_momentum | 0.312 |
| Sideways | 6,100 | sector_momentum | 0.268 |

### Root Causes Fixed
1. **CRITICAL - Timezone inconsistency**: Mixed UTC/ET data → Normalized to ET
2. **HIGH - Raw price drift**: 24 raw features → 0 raw features  
3. **MEDIUM - ICT implementation**: Enhanced with kill zones, normalized VPA
4. **MEDIUM - Time stratification**: Single model → Morning/afternoon models

### Quick Start: Run Fixed System

```bash
# Run complete fixed pipeline
python scripts/run_fixed_pipeline.py

# Or run individual phases:
python scripts/build_intraday_features_fixed.py    # Phase 1: Clean features
python scripts/validate_fixed_features.py          # Validation
python scripts/rolling_train_fixed.py              # Phase 3: Time-stratified training

# Monitor progress
python scripts/monitor_fixed_pipeline.py

# View results
cat run/rolling_results_fixed/trades.csv
```

**Key Files**:
- [Root Cause Analysis](ROOT_CAUSE_ANALYSIS_DEC12.md) - Complete technical analysis
- [Implementation Status](FINAL_IMPLEMENTATION_STATUS_DEC10.md) - Previous system analysis
- [Pipeline Status](PIPELINE_RUNNING_DEC9.md) - Development log

## Features

### Daily HMM_SIP Universe Selection
- **Dynamic Symbol Selection**: Uses shared daily_sip JSON ranked by score
- **Configuration Driven**: Simple enable/disable via SIP configuration (`mode: "daily"`)
- **Framework Agnostic**: Works with any trading strategy (VWAP, ML, custom policies)
- **Performance Optimized**: Hybrid caching with O(1) symbol eligibility checks
- **Documentation**: See [docs/features/daily-hmm-sip.md](docs/features/daily-hmm-sip.md) for complete guide

### Quick Start with Daily HMM_SIP

```yaml
# Example configuration
sip:
  method: "hmm"
  config:
    mode: "daily"      # Enable daily universe selection
    score_floor: 0.01  # Minimum SIP score
    top_k: 40         # Maximum symbols per day (optional cap)
```

```bash
# Run example
python examples/daily_hmm_sip_example.py

# Run experiment with daily HMM_SIP
qx-cli exp entry-ab experiments/vwap_daily_hmm/strategy.yaml
```

## Data Storage Locations

### Core Data Directories
```
/home/jacobw/quantstack/
├── data/
│   ├── daily_sip/                    # Compatibility outputs (txt)
│   │   ├── sip_universe_YYYY-MM-DD.txt
│   │   └── l2_symbols_YYYY-MM-DD.txt
│   ├── l2_maximum/                   # L2 microstructure data
│   │   ├── features/date=YYYY-MM-DD/ # Processed L2 features (parquet)
│   │   │   └── symbol=XXX/           # Per-symbol feature files
│   │   ├── raw/                      # Raw L2 snapshots
│   │   ├── exports/                  # Analysis exports
│   │   ├── selection_log/            # Symbol rotation logs
│   │   └── journal.db                # Collection metadata
│   └── models/                       # Trained ML models
├── logs/
│   ├── live_trading.log             # Live trading system logs
│   ├── l2_collector.log             # L2 data collection logs
│   └── daily_sip.log                # SIP universe generation logs
├── run/
│   ├── rolling_results_fixed/       # Backtest results
│   │   └── trades.csv               # Trade execution records
│   └── experiments/                 # Experiment outputs
└── config/                          # Configuration files
```

### External Data Sources
```
/home/jacobw/gcs-mount/gold/stocks/1m/   # Historical training data (GCS mount)
/home/jacobw/intraday_stack/data/daily_sip/  # Shared SIP JSON artifacts
```

### Live System Files
```
~/.aws/credentials                   # AWS credentials for services
/etc/systemd/system/
├── l2-collector.service            # L2 collection service
└── l2-watchdog.service             # L2 monitoring service
```

## L2 Data Collection

### Current Status (2025-12-20)
- **Records Collected**: 135,920+ L2 snapshots
- **Symbols**: HAL (45k), PFE (44k), LUV (44k), SLB (1.3k), XOM (1.3k)
- **Data Quality**: 100% depth coverage, 2 snapshots/second
- **Features**: 32 per record (OBI, depth imbalance, spread dynamics)
- **Analysis Ready**: ✅ Sufficient for initial microstructure analysis

### L2 Features Schema
Each record contains 32 features:
- **Timestamps**: ts_utc, ts_epoch, date_et
- **Depth**: depth_bid_k, depth_ask_k, depth_imb_k, pressure_k
- **Order Book Imbalance**: obi_1, obi_2, obi_3, obi_5, obi_10
- **Delta Features** (4 windows: 5s, 15s, 30s, 60s):
  - Mid price changes (d_mid_*)
  - Spread changes (d_spread_*)
  - OBI changes (d_obi_1_*)
  - Microstructure offset (d_micro_off_*)

### Analysis Examples
```python
import pandas as pd
import glob

# Load PFE L2 data
files = glob.glob('data/l2_maximum/features/date=2025-12-19/symbol=PFE/*.parquet')
df = pd.concat([pd.read_parquet(f) for f in files])

# Analyze order book imbalance
obi_correlation = df[['obi_1', 'obi_2', 'obi_3', 'd_mid_5s']].corr()
print(f"Records: {len(df):,}")
print(f"OBI-1 range: {df['obi_1'].min():.3f} to {df['obi_1'].max():.3f}")
```

### Collection System
- **Service**: `l2-collector.service` (systemd)
- **Watchdog**: `l2-watchdog.service` (enhanced monitoring)
- **IBKR Client ID**: 521 (separate from trading systems)
- **Compliance**: 3-symbol concurrent limit with 5-minute rotation
- **SIP Integration**: Dynamic symbol selection from daily universe

The system uses modular qx-* packages:

- **qx-core**: Schemas, contracts, validators, and utilities
- **qx-data**: Gold data loading and normalization
- **qx-features**: Feature engineering and registry system
- **qx-screener**: Universe selection (SIP + HMM methods)
- **qx-backtest**: Order → fill → position → P&L pipeline
- **qx-risk**: Risk management and position sizing
- **qx-report**: Comparative analysis and reporting
- **qx-cli**: Typer/Rich CLI surface and experiment orchestration

### Data Integration (Gold + Polygon + IBKR)
- **Historical training**: Reads gold parquet from `/home/jacobw/gcs-mount/gold/stocks/1m/`
- **Live SIP**: Uses Polygon delayed data to select daily SIP universes and persists to `data/daily_sip/`
- **Paper trading**: Executes via IBKR (TWS/Gateway on `127.0.0.1:7497`) using the live SIP list
- **L2 capture**: Collects NYSE L2 for opening/power hours from the SIP-filtered list
- **Validator**: Run `python scripts/validate_data_integrations.py --check-polygon --check-ibkr` to verify gold mount, SIP artifacts, and live endpoints before market open

### Key Data Files by Purpose

#### Daily Trading Operations
- `data/daily_sip/sip_universe_YYYY-MM-DD.txt` - 40 NYSE symbols for live trading
- `logs/live_trading.log` - Real-time trading system activity
- `run/rolling_results_fixed/trades.csv` - Historical trade execution records

#### L2 Microstructure Analysis
- `data/l2_maximum/features/date=YYYY-MM-DD/symbol=XXX/*.parquet` - Processed L2 features
- `data/l2_maximum/journal.db` - Collection metadata and symbol rotation logs
- `logs/l2_collector.log` - L2 data collection system logs

#### Model Training & Backtesting
- `data/models/` - Trained regime-aware ML models
- `/home/jacobw/gcs-mount/gold/stocks/1m/` - Historical 1-minute bar data
- `run/experiments/` - Experiment outputs and comparative analysis

#### System Configuration
- `config/` - YAML configuration files for strategies and experiments
- `~/.aws/credentials` - AWS credentials for cloud services
- `/etc/systemd/system/l2-*.service` - L2 collection system services

### VWAP Momentum Strategy

The VWAP Momentum strategy complements the reversion strategy by trading breakouts above and below VWAP:

```python
from qx_backtest.policies import VwapMomentumPolicy, VwapMomentumPolicyEnhanced

# Basic momentum - buys breakouts above VWAP
policy = VwapMomentumPolicy(
    vwap_window=30,
    min_breakout_strength=0.8,
    position_size_pct=0.15
)

# Enhanced with ATR-based stops
enhanced = VwapMomentumPolicyEnhanced(
    vwap_window=30,
    atr_window=14,
    atr_multiplier=2.0,
    min_profit_atr=1.0
)
```

**Key Features:**
- **Opposite Logic**: Buys when price > VWAP (momentum), sells when price < VWAP (momentum)
- **ATR Risk Management**: Enhanced version includes volatility-based stops
- **Trend Following**: Designed for trending markets with momentum
- **Volume Filtering**: Requires minimum relative volume for entries

**Use Cases:**
- Strong trending markets
- Breakout continuation strategies
- Momentum-based trading systems
- Complement to reversion strategies

See [VWAP Momentum Guide](docs/vwap_momentum_guide.md) for detailed documentation.

## Documentation

- [Features](docs/features/) - Detailed feature documentation
- [Architecture](docs/ARCHITECTURE.md) - System architecture overview
- [Production Architecture](docs/PRODUCTION_ARCHITECTURE.md) - Production system details
- [IBKR Gateway Startup](docs/IBKR_GATEWAY_STARTUP.md) - Programmatic Gateway startup methods
- [Experiments](docs/EXPERIMENTS.md) - Experiment framework guide
- [Development](docs/DEV_ENV.md) - Development environment setup
- [Examples](examples/) - Working code examples
