# qx-l2: Standalone L2 Order Book Data Collector

A production-ready, standalone module for collecting Level 2 order book data from Interactive Brokers (IBKR) with comprehensive feature engineering and ML-ready dataset export.

## Features

- **Standalone Operation**: No dependencies on external trading systems
- **Independent Symbol Selection**: Static, rotating, hybrid, or external modes
- **Flexible Scheduling**: Configurable collection windows with timezone support
- **System Tagging**: IBKR client separation following PAPER_TRADING_GUIDE best practices
- **Event Journaling**: Complete SQLite audit trail
- **Feature Engineering**: 20+ microstructure features (OBI, microprice, depth imbalance)
- **Partitioned Storage**: Efficient parquet storage with daily consolidation
- **ML Export**: One-command dataset export for training

## Quick Start

### Installation

```bash
cd qx-l2
pip install -e .
```

### Basic Usage

```bash
# Run in daemon mode (waits for collection windows)
l2-collect --daemon

# Run single collection cycle now
l2-collect --once

# Override symbols
l2-collect --once --symbols HAL PFE LUV

# Export training dataset
python scripts/export_dataset.py --output training.parquet --features-only
```

## Configuration

Edit `configs/default.yaml`:

```yaml
# Symbol selection
symbols:
  mode: "hybrid"  # static, rotating, hybrid, external
  core: [HAL, PFE, LUV]  # Always collected
  rotating_pool: [MOS, ACHR, CRGY]  # Rotated daily
  max_symbols: 6

# Collection schedule (ET)
schedule:
  windows:
    - "09:30-10:30"  # Opening
    - "15:00-16:00"  # Power hour

# IBKR connection
ibkr:
  host: "127.0.0.1"
  port: 7497
  client_id: 500  # Unique per system
```

## Architecture

```
qx-l2/
├── src/qx_l2/
│   ├── collector.py      # Main collector
│   ├── symbols.py        # Independent symbol selection
│   ├── scheduler.py      # Time window management
│   ├── storage.py        # Partitioned storage
│   ├── features.py       # L2 feature engineering
│   ├── journal.py        # Event logging
│   └── config.py         # Configuration management
├── scripts/
│   ├── run_collector.py  # Main entry point
│   ├── export_dataset.py # ML dataset export
│   └── analyze_data.py   # Data quality analysis
└── configs/
    └── default.yaml      # Default configuration
```

## Symbol Selection Modes

### Hybrid (Recommended)
- **Core symbols**: Always collected for time-series continuity
- **Rotating symbols**: Daily rotation from pool for diversity
- **Example**: Core=[HAL,PFE,LUV] + 3 rotating from pool

### Static
- Fixed symbol list from configuration
- Best for focused studies on specific symbols

### Rotating
- Round-robin through entire pool
- Maximizes symbol diversity over time

### External
- Accept symbols from external source (e.g., SIP integration)
- Allows integration with existing universe selection

## Data Structure

### Raw Data (76 columns)
```
Timestamps: ts_utc, ts_epoch, date_et
L1 Data: l1_bid, l1_ask, l1_mid, l1_spread, l1_last
L2 Depth: bid_px_1-10, ask_px_1-10, bid_sz_1-10, ask_sz_1-10
Market Makers: bid_mm_1-10, ask_mm_1-10
```

### Features (28 columns)
```
Microstructure: mid, spread, microprice, micro_off
Depth: depth_bid_k, depth_ask_k, depth_imb_k, pressure_k
OBI: obi_1, obi_3, obi_5, obi_10
Time Deltas: d_mid_5s, d_spread_5s, d_obi1_5s, d_microoff_5s (+ 30s versions)
```

### Storage Layout
```
data/l2/
├── raw/
│   └── date=2025-12-18/
│       └── symbol=HAL/
│           └── part_*.parquet
├── features/
│   └── date=2025-12-18/
│       └── symbol=HAL/
│           └── part_*.parquet
├── exports/
│   └── training_*.parquet
└── journal.db
```

## System Tagging

Following PAPER_TRADING_GUIDE best practices:

- **System Name**: `L2COLLECT`
- **Client ID**: 500 (configurable)
- **System Tag**: `L2COLLECT_500`

This ensures clean separation from other IBKR systems.

## Event Journaling

Complete audit trail in SQLite:

```sql
-- Collection sessions
sessions: session_id, start_time, end_time, symbols, records_collected

-- Errors
errors: error_id, timestamp, error_type, message, symbol

-- Daily statistics  
daily_stats: date, total_records, avg_depth_rate, avg_spread
```

## ML Integration

### Export Training Dataset
```bash
# Export all features
python scripts/export_dataset.py --output training.parquet --features-only

# Export date range
python scripts/export_dataset.py --output recent.parquet \
  --start-date 2025-12-01 --end-date 2025-12-18 --features-only

# Export specific symbols
python scripts/export_dataset.py --output hal_pfe.parquet \
  --symbols HAL PFE --features-only
```

### Use in ML Pipeline
```python
import pandas as pd

# Load L2 features
df = pd.read_parquet("training.parquet")

# Key features for ML
l2_features = [
    'obi_10',           # Deep book imbalance
    'micro_off',        # Microprice deviation  
    'depth_imb_k',      # Total depth imbalance
    'pressure_k',       # Liquidity pressure
    'd_mid_30s',        # 30s price momentum
    'd_obi1_30s',       # 30s OBI momentum
]

# Combine with cross-sectional features
X = df[l2_features + cross_sectional_features]
```

## Monitoring

### Data Quality Analysis
```bash
# Overall statistics
python scripts/analyze_data.py

# Daily summary
python scripts/analyze_data.py --date 2025-12-18
```

### Journal Queries
```python
from qx_l2 import L2Journal, load_config

journal = L2Journal(load_config())
summary = journal.get_daily_summary("2025-12-18")
print(f"Records: {summary['records']}, Depth rate: {summary['depth_rate']:.1%}")
```

## Production Deployment

### Systemd Service
```ini
[Unit]
Description=L2 Data Collector
After=network.target

[Service]
Type=simple
User=trader
WorkingDirectory=/home/trader/qx-l2
ExecStart=/home/trader/qx-l2/scripts/run_collector.py --daemon
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### Environment Variables
```bash
export L2_IBKR_HOST=127.0.0.1
export L2_IBKR_PORT=7497
export L2_CLIENT_ID=500
export L2_STORAGE_DIR=/data/l2
```

## Performance

- **Collection Rate**: ~1 snapshot/second per symbol
- **Storage**: ~1KB per snapshot (compressed)
- **Memory**: <100MB for 6 symbols
- **CPU**: <5% on modern hardware

## Troubleshooting

### Connection Issues
```bash
# Check IBKR connectivity
python -c "from ib_insync import IB; ib=IB(); ib.connect('127.0.0.1', 7497, 500); print('OK' if ib.isConnected() else 'FAIL')"
```

### Data Quality Issues
- Monitor depth rate (target: >85%)
- Check spread distribution (target: <0.03)
- Verify symbol rotation logs

### Storage Issues
- Run daily consolidation: `storage.consolidate_daily()`
- Clean old data: `storage.cleanup_old_data()`
- Monitor disk usage

## License

Part of the quantstack trading system.
