# qx-l2 Run Instructions

Step-by-step instructions for running the L2 data collector.

## Prerequisites Checklist

- [ ] Python 3.11+ installed
- [ ] Interactive Brokers TWS or Gateway running
- [ ] Market data subscriptions active
- [ ] Sufficient disk space (>1GB recommended)

## Installation

### Step 1: Install Package
```bash
cd /home/jacobw/quantstack/qx-l2
pip install -e .
```

### Step 2: Verify Installation
```bash
l2-collect --help
```
Expected output: Command help text

## Configuration

### Step 3: Edit Configuration
```bash
nano configs/default.yaml
```

**Required Changes:**
```yaml
# IBKR Connection - VERIFY THESE
ibkr:
  host: "127.0.0.1"
  port: 7497        # 7497=Paper, 7496=Live
  client_id: 500    # Must be unique

# Symbols - CUSTOMIZE FOR YOUR NEEDS
symbols:
  mode: "hybrid"
  core: [HAL, PFE, LUV]  # Always collected
  rotating_pool: [MOS, ACHR, CRGY]  # Daily rotation
  max_symbols: 6

# Collection Windows - ADJUST FOR YOUR TIMEZONE
schedule:
  timezone: "America/New_York"
  windows:
    - "09:30-10:30"  # Market open
    - "15:00-16:00"  # Power hour
```

## Pre-Flight Checks

### Step 4: Test IBKR Connection
```bash
python -c "
from ib_insync import IB
ib = IB()
try:
    ib.connect('127.0.0.1', 7497, 500, timeout=10)
    print('✅ IBKR Connection: OK')
    print(f'Account: {ib.managedAccounts()}')
    ib.disconnect()
except Exception as e:
    print(f'❌ IBKR Connection: FAILED - {e}')
"
```

### Step 5: Test Symbol Subscription
```bash
l2-collect --once --symbols HAL --log-level INFO
```

**Expected Output:**
```
INFO - [L2COLLECT_500] Connected to IBKR 127.0.0.1:7497
INFO - [L2COLLECT_500] Subscribed to HAL
INFO - [L2COLLECT_500] Collecting for 1 symbols
```

**If Errors:**
- `Connection failed`: Check TWS/Gateway is running
- `Market data not available`: Check subscriptions
- `Symbol not found`: Verify symbol exists

## Running Modes

### Mode 1: Test Run (Recommended First)
```bash
# Test with single symbol
l2-collect --once --symbols HAL

# Check output
ls -la data/l2/raw/date=$(date +%Y-%m-%d)/
```

### Mode 2: Production Daemon
```bash
# Run in background
nohup l2-collect --daemon > l2_daemon.log 2>&1 &

# Check it's running
ps aux | grep l2-collect
tail -f l2_daemon.log
```

### Mode 3: Interactive Mode
```bash
# Shows status and runs if in window
l2-collect
```

## Monitoring

### Real-Time Monitoring
```bash
# Watch logs
tail -f l2_collector.log

# Monitor data collection
watch -n 10 'find data/l2/raw -name "*.parquet" | wc -l'

# Check latest data
ls -lt data/l2/raw/date=$(date +%Y-%m-%d)/symbol=HAL/ | head -5
```

### Daily Health Check
```bash
# Run analysis
python scripts/analyze_data.py --date $(date +%Y-%m-%d)
```

**Expected Output:**
```
Storage Statistics:
  Raw files: 24
  Total size: 2.5 MB
  Est. records: 1,440

Daily Summary (2025-12-18):
  Sessions: 4
  Records: 1,440
  Depth rate: 95.2%
  Avg spread: 0.012
```

## Data Export

### Export ML Dataset
```bash
# Export all features
python scripts/export_dataset.py --output training.parquet --features-only

# Check export
python -c "
import pandas as pd
df = pd.read_parquet('training.parquet')
print(f'Records: {len(df):,}')
print(f'Symbols: {df.symbol.nunique()}')
print(f'Columns: {list(df.columns)}')
"
```

## Troubleshooting

### Common Issues

#### 1. "Connection refused"
```bash
# Check IBKR is running
netstat -an | grep 7497
```
**Solution**: Start TWS/Gateway

#### 2. "No market data"
```bash
# Check subscriptions in TWS
# Account > Market Data Subscriptions
```
**Solution**: Subscribe to required exchanges

#### 3. "Permission denied" on data directory
```bash
chmod -R 755 data/
```

#### 4. High memory usage
Edit `configs/default.yaml`:
```yaml
collection:
  snapshot_interval_ms: 2000  # Reduce frequency
storage:
  flush_rows: 100  # Flush more frequently
```

### Debug Mode
```bash
l2-collect --once --symbols HAL --log-level DEBUG
```

## Production Deployment

### Systemd Service (Linux)
```bash
# Create service file
sudo nano /etc/systemd/system/l2-collect.service
```

```ini
[Unit]
Description=L2 Data Collector
After=network.target

[Service]
Type=simple
User=trader
WorkingDirectory=/home/trader/quantstack/qx-l2
ExecStart=/home/trader/quantstack/qx-l2/scripts/run_collector.py --daemon
Restart=always
RestartSec=30
Environment=L2_CLIENT_ID=500

[Install]
WantedBy=multi-user.target
```

```bash
# Enable and start
sudo systemctl enable l2-collect
sudo systemctl start l2-collect

# Check status
sudo systemctl status l2-collect
```

### Cron Job (Alternative)
```bash
# Edit crontab
crontab -e

# Add entry (runs at market open)
30 9 * * 1-5 cd /home/trader/quantstack/qx-l2 && timeout 3600 l2-collect --daemon
```

## Performance Tuning

### High-Frequency Collection
```yaml
collection:
  snapshot_interval_ms: 500  # 2 snapshots/second
  levels: 5                  # Reduce depth levels
storage:
  flush_rows: 500           # Larger batches
```

### Low-Resource Mode
```yaml
symbols:
  max_symbols: 3            # Fewer symbols
collection:
  snapshot_interval_ms: 2000  # Lower frequency
features:
  enabled: false            # Disable features
```

## Maintenance

### Daily Tasks
```bash
# Check data quality
python scripts/analyze_data.py --date $(date +%Y-%m-%d)

# Export recent data
python scripts/export_dataset.py --output daily_$(date +%Y%m%d).parquet \
  --start-date $(date +%Y-%m-%d) --features-only
```

### Weekly Tasks
```bash
# Consolidate files
python -c "
from qx_l2 import L2Storage, load_config
storage = L2Storage(load_config())
for i in range(7):
    date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
    storage.consolidate_daily(date)
"

# Clean old data (>90 days)
python -c "
from qx_l2 import L2Storage, load_config
storage = L2Storage(load_config())
storage.cleanup_old_data()
"
```

## Quick Reference

### Essential Commands
```bash
# Install
pip install -e .

# Test run
l2-collect --once --symbols HAL

# Production daemon
l2-collect --daemon

# Export data
python scripts/export_dataset.py --output data.parquet --features-only

# Analyze
python scripts/analyze_data.py
```

### Key Files
- `configs/default.yaml` - Configuration
- `l2_collector.log` - Application logs
- `data/l2/journal.db` - Event database
- `data/l2/raw/` - Raw L2 data
- `data/l2/features/` - Computed features

### Support
- Check logs: `tail -f l2_collector.log`
- Debug mode: `--log-level DEBUG`
- Test connection: See "Pre-Flight Checks"
- Data analysis: `python scripts/analyze_data.py`
