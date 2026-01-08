# quantstack

A modular, framework-agnostic trading system with configurable universe selection, backtesting, and experiment orchestration.

## Latest: Production-Ready Live Trading System (2025-12-21)

**✅ PRODUCTION RELIABILITY: Enhanced orchestrator with automatic recovery**  
**✅ SYSTEM PERSISTENCE: All services enabled for autostart across reboots**  
**✅ MULTI-SESSION SIP: Prior day + overnight + premarket data integration**  
**✅ API RESILIENCE: Polygon retry logic with exponential backoff**  
**✅ IBKR AUTO-RECOVERY: Gateway restart capability with health monitoring**

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
- [Experiments](docs/EXPERIMENTS.md) - Experiment framework guide
- [Development](docs/DEV_ENV.md) - Development environment setup
- [Examples](examples/) - Working code examples
