# qx-l2 User Guide

Complete guide for using the standalone L2 order book data collector.

## Table of Contents

1. [Quick Start](#quick-start)
2. [Installation](#installation)
3. [Configuration](#configuration)
4. [Running the Collector](#running-the-collector)
5. [Data Management](#data-management)
6. [Monitoring](#monitoring)
7. [Troubleshooting](#troubleshooting)

## Quick Start

### Prerequisites
- Python 3.11+
- Interactive Brokers TWS or Gateway running
- Market data subscriptions for target symbols

### 5-Minute Setup
```bash
# 1. Install
cd qx-l2
pip install -e .

# 2. Configure (edit configs/default.yaml)
# Set your symbols and IBKR connection

# 3. Test connection
l2-collect --once --symbols HAL

# 4. Run daemon
l2-collect --daemon
```

## Installation

### From Source
```bash
git clone <repo>
cd quantstack/qx-l2
pip install -e .
```

### Verify Installation
```bash
l2-collect --help
python -c "import qx_l2; print('OK')"
```

## Configuration

### Basic Configuration
Edit `configs/default.yaml`:

```yaml
# IBKR Connection
ibkr:
  host: "127.0.0.1"
  port: 7497        # Paper: 7497, Live: 7496
  client_id: 500    # Unique per system

# Symbols to collect
symbols:
  mode: "hybrid"    # static, rotating, hybrid, external
  core: [HAL, PFE, LUV]
  max_symbols: 6

# Collection windows (ET)
schedule:
  windows:
    - "09:30-10:30"  # Opening hour
    - "15:00-16:00"  # Power hour
```

### Symbol Selection Modes

#### Static Mode
Fixed list of symbols:
```yaml
symbols:
  mode: "static"
  core: [HAL, PFE, LUV, MOS, ACHR, CRGY]
```

#### Hybrid Mode (Recommended)
Core symbols + daily rotation:
```yaml
symbols:
  mode: "hybrid"
  core: [HAL, PFE, LUV]           # Always collected
  rotating_pool: [MOS, ACHR, CRGY, FCX, AA]  # Rotated daily
  max_symbols: 6
```

#### External Mode
Accept symbols from external source:
```yaml
symbols:
  mode: "external"
  core: [HAL, PFE, LUV]  # Fallback if no external symbols
```

### Advanced Configuration

#### Collection Parameters
```yaml
collection:
  levels: 10                    # Order book depth
  snapshot_interval_ms: 1000    # 1 snapshot/second
  rotate_seconds: 300           # 5-minute symbol rotation
```

#### Storage Settings
```yaml
storage:
  base_dir: "./data/l2"
  compression: "snappy"
  flush_rows: 300
  retention_days: 90
```

#### Feature Engineering
```yaml
features:
  enabled: true
  obi_levels: [1, 3, 5, 10]     # Order book imbalance levels
  delta_windows_sec: [5, 30]    # Time delta windows
```

### Environment Variables
Override config with environment variables:
```bash
export L2_IBKR_HOST=127.0.0.1
export L2_IBKR_PORT=7497
export L2_CLIENT_ID=500
export L2_STORAGE_DIR=/data/l2
```

## Running the Collector

### Command Line Options
```bash
l2-collect [OPTIONS]

Options:
  --config PATH         Configuration file (default: configs/default.yaml)
  --daemon             Run as daemon (waits for collection windows)
  --once               Run single collection cycle
  --symbols SYMBOL...  Override symbols to collect
  --log-level LEVEL    Logging level (DEBUG, INFO, WARNING, ERROR)
```

### Daemon Mode (Production)
Waits for collection windows and runs automatically:
```bash
l2-collect --daemon
```

**Behavior:**
- Waits for collection windows
- Connects to IBKR when window starts
- Collects data during window
- Disconnects when window ends
- Repeats for next window

### One-Shot Mode (Testing)
Run single collection cycle immediately:
```bash
# Use configured symbols
l2-collect --once

# Override symbols
l2-collect --once --symbols HAL PFE LUV

# Custom config
l2-collect --once --config my_config.yaml
```

### Interactive Mode
Default mode - shows status and runs if in collection window:
```bash
l2-collect
```

## Data Management

### Data Structure
```
data/l2/
├── raw/                    # Raw L2 snapshots
│   └── date=2025-12-18/
│       └── symbol=HAL/
│           └── part_*.parquet
├── features/               # Computed features
│   └── date=2025-12-18/
│       └── symbol=HAL/
│           └── part_*.parquet
├── exports/                # ML datasets
│   └── training_*.parquet
├── selection_log/          # Symbol selection log
│   └── 2025-12-18.json
└── journal.db             # Event log
```

### Export ML Dataset
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

### Data Analysis
```bash
# Overall statistics
python scripts/analyze_data.py

# Daily summary
python scripts/analyze_data.py --date 2025-12-18
```

### Storage Management
```python
from qx_l2 import L2Storage, load_config

storage = L2Storage(load_config())

# Consolidate daily files
storage.consolidate_daily("2025-12-18")

# Clean old data
storage.cleanup_old_data()

# Get statistics
stats = storage.get_stats()
print(f"Total size: {stats['total_size_mb']:.1f}MB")
```

## Monitoring

### Real-Time Monitoring
```bash
# Watch logs
tail -f l2_collector.log

# Monitor data directory
watch -n 5 'ls -la data/l2/raw/date=$(date +%Y-%m-%d)/'
```

### Data Quality Metrics
```python
from qx_l2 import L2Journal, load_config

journal = L2Journal(load_config())
summary = journal.get_daily_summary("2025-12-18")

print(f"Records: {summary['records']:,}")
print(f"Depth rate: {summary['depth_rate']:.1%}")
print(f"Avg spread: {summary['avg_spread']:.4f}")
```

### Key Metrics to Monitor
- **Depth Rate**: >85% (% of snapshots with order book data)
- **Average Spread**: <0.03 (tight spreads indicate good liquidity)
- **Records/Day**: >1,000 (sufficient data volume)
- **Error Rate**: <1% (connection stability)

### Alerts
Monitor these conditions:
- Depth rate drops below 80%
- No data collected for >30 minutes during window
- Storage growth >200MB/day
- Connection errors >5/hour

## Troubleshooting

### Connection Issues

#### "Connection failed" Error
```bash
# Check IBKR is running
netstat -an | grep 7497

# Test connection manually
python -c "
from ib_insync import IB
ib = IB()
ib.connect('127.0.0.1', 7497, 500)
print('OK' if ib.isConnected() else 'FAIL')
"
```

**Solutions:**
- Ensure TWS/Gateway is running
- Check port number (7497 for paper, 7496 for live)
- Verify client ID is unique
- Check firewall settings

#### "Market data not available" Error
**Cause**: Missing market data subscriptions

**Solutions:**
- Subscribe to market data in TWS
- Check symbol permissions
- Verify exchange subscriptions (NYSE for most symbols)

### Data Quality Issues

#### Low Depth Rate (<80%)
**Causes:**
- Market data subscription issues
- Symbol not actively traded
- Exchange connectivity problems

**Solutions:**
- Check market data subscriptions
- Switch to more liquid symbols
- Verify exchange permissions

#### No Data Collected
**Causes:**
- Outside collection windows
- IBKR connection failed
- Symbol subscription failed

**Debug:**
```bash
# Check if in collection window
python -c "
from qx_l2 import L2Scheduler, load_config
scheduler = L2Scheduler(load_config())
print('In window:', scheduler.is_collection_time())
print('Next window:', scheduler.next_window_start())
"

# Test symbol subscription
l2-collect --once --symbols HAL --log-level DEBUG
```

### Storage Issues

#### Disk Space
Monitor storage growth:
```bash
# Check current usage
du -sh data/l2/

# Clean old data
python -c "
from qx_l2 import L2Storage, load_config
storage = L2Storage(load_config())
result = storage.cleanup_old_data()
print('Cleaned:', result['removed'])
"
```

#### File Permissions
Ensure write permissions:
```bash
chmod -R 755 data/l2/
```

### Performance Issues

#### High Memory Usage
- Reduce `flush_rows` in config
- Decrease `snapshot_interval_ms`
- Limit `max_symbols`

#### Slow Performance
- Use SSD storage
- Increase `flush_rows` for fewer writes
- Enable compression

### Log Analysis
```bash
# Error patterns
grep ERROR l2_collector.log | tail -20

# Connection issues
grep "Connection\|connect" l2_collector.log

# Data quality
grep "depth_rate\|spread" l2_collector.log
```

## Best Practices

### Production Deployment
1. **Use daemon mode**: `l2-collect --daemon`
2. **Monitor logs**: Set up log rotation
3. **Backup data**: Regular exports to backup storage
4. **Health checks**: Monitor depth rate and error rate
5. **Resource limits**: Set memory/CPU limits

### Symbol Selection
1. **Start small**: Begin with 3-6 liquid symbols
2. **Use hybrid mode**: Core symbols + rotation for diversity
3. **Monitor quality**: Track depth rate per symbol
4. **Adjust based on data**: Remove low-quality symbols

### Data Management
1. **Regular exports**: Export ML datasets weekly
2. **Storage cleanup**: Clean data older than 90 days
3. **Consolidation**: Run daily consolidation
4. **Monitoring**: Track storage growth

### Integration
1. **Unique client ID**: Avoid conflicts with other systems
2. **System tagging**: Use L2COLLECT prefix
3. **Clean separation**: Don't mix with trading systems
4. **Data contracts**: Use consistent export formats
