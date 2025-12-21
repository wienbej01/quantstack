# quantstack

A modular, framework-agnostic trading system with configurable universe selection, backtesting, and experiment orchestration.

## Latest: Live Intraday ML Trading System (2025-12-21)

**✅ FULL 2025 YTD COVERAGE: Features and SIP complete through Dec 15, 2025**  
**✅ REGIME-AWARE MODELS: Trained on 2024-12-01 to 2025-11-15, validated through Dec 15**  
**✅ PRODUCTION READY: 1,700,509 feature rows, 86 features, 3 regime models**  
**✅ LIVE SIP: 40 NYSE symbols via real-time Polygon filtering**

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
- ✅ **Live Trading**: Running on IBKR paper account (PID: 1594347)
- ✅ **Regime Detection**: Bull/Bear/Sideways models trained on 6 months data
- ✅ **Feature Set**: 11 cross-sectional features (best performers)
- ✅ **L2 Data Collection**: 135,920+ records collected (HAL, PFE, LUV, SLB, XOM)
- ✅ **L2 Storage**: `/home/jacobw/quantstack/data/l2_maximum/` (128MB+)
- ✅ **Position Sizing**: 100 shares per trade, confidence-based entry
- ✅ **Universe**: 40 NYSE symbols via live Polygon SIP filtering
- ✅ **L2 Collection**: Opening hour (9:30-10:30) + Power hour (15:00-16:00) ET
- ✅ **Next Market Open**: 9:30 AM ET, system ready for trading

### Quick Start
```bash
# Check live system status
tail -f logs/live_trading.log

# Retrain regime-aware models
python scripts/train_and_save_regime_models.py

# Run regime-aware backtest
python scripts/regime_aware_strategy.py

# Regenerate daily SIP universe
python scripts/daily_sip_scheduler.py

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
- **Dynamic Symbol Selection**: Uses Hidden Markov Model scoring to select top-k symbols daily
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
    score_floor: 0.01  # Minimum HMM score
    top_k: 40         # Maximum symbols per day
```

```bash
# Run example
python examples/daily_hmm_sip_example.py

# Run experiment with daily HMM_SIP
qx-cli exp entry-ab experiments/vwap_daily_hmm/strategy.yaml
```

## L2 Data Collection

### Current Status (2025-12-20)
- **Records Collected**: 135,920+ L2 snapshots
- **Symbols**: HAL (45k), PFE (44k), LUV (44k), SLB (1.3k), XOM (1.3k)
- **Data Quality**: 100% depth coverage, 2 snapshots/second
- **Features**: 32 per record (OBI, depth imbalance, spread dynamics)
- **Analysis Ready**: ✅ Sufficient for initial microstructure analysis

### Data Locations
```
Primary Directory: /home/jacobw/quantstack/data/l2_maximum/
├── features/date=2025-12-19/     # Processed L2 features (parquet)
│   ├── symbol=HAL/               # 45,307 records
│   ├── symbol=PFE/               # 43,974 records (today's SIP)
│   ├── symbol=LUV/               # 43,971 records
│   ├── symbol=SLB/               # 1,334 records
│   └── symbol=XOM/               # 1,334 records
├── raw/                          # Raw L2 snapshots
├── exports/                      # Analysis exports
├── selection_log/                # Symbol rotation logs
└── journal.db                    # Collection metadata (40KB)
```

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
- **Historical training**: Reads gold parquet from `/home/jacobw/gcs-mount/gold/stocks/1m/`.
- **Live SIP**: Uses Polygon delayed data to select daily SIP universes and persists to `data/daily_sip/`.
- **Paper trading**: Executes via IBKR (TWS/Gateway on `127.0.0.1:7497`) using the live SIP list.
- **L2 capture**: Collects NYSE L2 for opening/power hours from the SIP-filtered list.
- **Validator**: Run `python scripts/validate_data_integrations.py --check-polygon --check-ibkr` to
  verify gold mount, SIP artifacts, and live endpoints before market open.

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
