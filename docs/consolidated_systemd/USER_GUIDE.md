# QUANTSTACK TRADING SYSTEM - USER GUIDE

**Version**: 2026-01-10  
**Audience**: System operators and developers

## Quick Start

### Daily Operations

```bash
# 1. Check system status
systemctl status l2-collector l2-scalping intraday-paper

# 2. View today's trades
python3 /home/jacobw/quantstack/scripts/trading_report.py --date $(date +%F)

# 3. Monitor real-time logs
journalctl -u intraday-paper -f

# 4. Check for alerts
curl -s https://ntfy.sh/jacobw-trading-alerts/json | jq '.[-5:]'
```

### Emergency Procedures

```bash
# Force close all open positions
python3 /home/jacobw/quantstack/close_open_positions.py

# Check emergency EOD status
journalctl -u emergency-eod-close.service --since today

# Restart failed services
sudo systemctl restart l2-collector l2-scalping intraday-paper
```

## System Services

### Core Trading Services

#### 1. Trading Orchestrator
**Purpose**: Daily SIP generation and system monitoring  
**Schedule**: 21:00 Manila (08:00 ET)  
**Location**: `/home/jacobw/quantstack/bulletproof_orchestrator.py`

```bash
# Manual SIP generation
cd /home/jacobw/quantstack && python3 bulletproof_orchestrator.py

# Check orchestrator logs
tail -f logs/orchestrator.log

# View audit trail
tail -f logs/orchestrator_audit.log
```

#### 2. L2 Collector
**Purpose**: NYSE L2 order book data collection  
**Schedule**: Continuous (starts 22:25 Manila)  
**Location**: `/home/jacobw/quantstack/qx-l2/`

```bash
# Check collection status
systemctl status l2-collector

# View collection stats
journalctl -u l2-collector --since "1 hour ago" | grep "collected"

# Check data files
ls -la /home/jacobw/quantstack/data/l2_maximum/features/date=$(date +%F)/
```

#### 3. L2 Scalping
**Purpose**: High-frequency L2-based trading  
**Schedule**: Continuous (starts 22:25 Manila)  
**Location**: `/home/jacobw/quantstack/l2_scalping/`

```bash
# Check trading status
systemctl status l2-scalping

# View recent trades
journalctl -u l2-scalping --since "1 hour ago" | grep -E "TRADE|FILL"

# Check configuration
cat /home/jacobw/quantstack/l2_scalping/config/strategy.yaml
```

#### 4. Intraday Paper Trading
**Purpose**: Reversal-based paper trading  
**Schedule**: Continuous (starts 22:25 Manila)  
**Location**: `/home/jacobw/intraday_stack/scripts/paper_trade.py`

```bash
# Check trading status
systemctl status intraday-paper

# View today's log
tail -f /home/jacobw/intraday_stack/logs/paper_$(date +%Y%m%d).log

# Check SIP universe
cat /home/jacobw/intraday_stack/data/daily_sip/date=$(date +%F)/sip_universe.json | jq '.symbols[:10]'
```

### Support Services

#### 5. Preflight Check
**Purpose**: Pre-market system validation  
**Schedule**: 20:00 Manila (07:00 ET)

```bash
# Manual preflight check
cd /home/jacobw/quantstack && python3 scripts/preflight_check.py

# Check preflight results
journalctl -u preflight-check.service --since today
```

#### 6. L2 Watchdog
**Purpose**: Monitor and restart L2 collector  
**Schedule**: Continuous

```bash
# Check watchdog status
systemctl status l2-watchdog

# View watchdog actions
journalctl -u l2-watchdog --since "1 hour ago"
```

#### 7. Emergency EOD Close
**Purpose**: Backup position closer (Gateway-independent)  
**Schedule**: 20:55 Manila (03:55 ET)

```bash
# Manual emergency check
cd /home/jacobw/quantstack && python3 scripts/emergency_eod_close.py

# Check emergency log
tail -f logs/emergency_eod.log
```

## Trading Operations

### Starting Trading Day

1. **Pre-Market (07:00 ET)**
   ```bash
   # Preflight check runs automatically
   journalctl -u preflight-check.service --since today
   ```

2. **SIP Generation (08:00 ET)**
   ```bash
   # Orchestrator generates daily universe
   tail -f /home/jacobw/quantstack/logs/orchestrator.log
   ```

3. **Market Open (09:30 ET)**
   ```bash
   # Services start automatically
   systemctl status l2-collector l2-scalping intraday-paper
   ```

### During Trading Hours

#### Monitor Performance
```bash
# Real-time trade notifications (phone)
# Subscribe to: https://ntfy.sh/jacobw-trading-trades

# Check current positions
python3 -c "
from journal.event_store import EventStore
es = EventStore('/home/jacobw/intraday_stack/data/journal/events.db')
open_trades = es.get_open_trades()
print(f'Open positions: {len(open_trades)}')
for trade in open_trades:
    print(f'  {trade[\"symbol\"]} {trade[\"direction\"]} @ {trade[\"entry_price\"]:.2f}')
"

# Generate performance report
python3 /home/jacobw/quantstack/full_trading_report.py --date $(date +%F)
```

#### Check System Health
```bash
# Service status
systemctl is-active l2-collector l2-scalping intraday-paper

# IBKR Gateway connectivity
python3 /home/jacobw/quantstack/scripts/check_portal_status.py

# Data flow validation
ls -la /home/jacobw/intraday_stack/data/daily_sip/date=$(date +%F)/
```

### End of Trading Day

#### Automatic EOD (15:45 ET)
- Primary flatten via IBKR Gateway
- Emergency backup at 15:55 ET

#### Manual Verification
```bash
# Check for remaining open positions
python3 -c "
from journal.event_store import EventStore
es = EventStore('/home/jacobw/intraday_stack/data/journal/events.db')
print(f'Open positions: {len(es.get_open_trades())}')
"

# View EOD logs
journalctl -u intraday-paper --since "16:00 today" | grep -E "FLATTEN|EOD"
journalctl -u emergency-eod-close.service --since today
```

## Configuration Management

### Service Configuration

#### Systemd Services
```bash
# View service configuration
systemctl cat l2-scalping

# Edit service (requires sudo)
sudo systemctl edit l2-scalping

# Reload after changes
sudo systemctl daemon-reload
sudo systemctl restart l2-scalping
```

#### Timer Schedules
```bash
# View all trading timers
systemctl list-timers | grep -E "(trading|l2|intraday|emergency)"

# Check next run times
systemctl list-timers trading-orchestrator.timer
```

### Application Configuration

#### L2 Scalping
```bash
# Strategy parameters
vim /home/jacobw/quantstack/l2_scalping/config/strategy.yaml

# Risk parameters
vim /home/jacobw/quantstack/l2_scalping/config/risk.yaml

# Restart to apply changes
sudo systemctl restart l2-scalping
```

#### Intraday Paper Trading
```bash
# Configuration embedded in Python
vim /home/jacobw/intraday_stack/scripts/paper_trade.py

# Restart to apply changes
sudo systemctl restart intraday-paper
```

## Data Management

### Trade Data

#### Database Location
```bash
# Main trade journal
/home/jacobw/intraday_stack/data/journal/events.db

# Tables: trades, fills, orders, decisions, risk_events
sqlite3 /home/jacobw/intraday_stack/data/journal/events.db ".tables"
```

#### Export Trade Data
```bash
# Today's trades to CSV
python3 /home/jacobw/quantstack/full_trading_report.py --date $(date +%F) --export trades_today.csv

# All trades
python3 /home/jacobw/quantstack/scripts/trading_report.py --export all_trades.csv

# Custom date range
python3 /home/jacobw/quantstack/scripts/trading_report.py --date 2026-01-09 --export jan9_trades.csv
```

### L2 Data

#### Data Location
```bash
# L2 features (processed)
/home/jacobw/quantstack/data/l2_maximum/features/date=YYYY-MM-DD/symbol=XXX/

# Raw L2 snapshots
/home/jacobw/quantstack/data/l2_maximum/raw/

# Collection metadata
/home/jacobw/quantstack/data/l2_maximum/journal.db
```

#### L2 Data Analysis
```bash
# Check collection stats
python3 -c "
import glob
import pandas as pd
files = glob.glob('/home/jacobw/quantstack/data/l2_maximum/features/date=$(date +%F)/*/*.parquet')
print(f'L2 files today: {len(files)}')
if files:
    df = pd.read_parquet(files[0])
    print(f'Features per record: {len(df.columns)}')
    print(f'Records in sample: {len(df)}')
"
```

### SIP Data

#### Universe Files
```bash
# Daily SIP universe
/home/jacobw/intraday_stack/data/daily_sip/date=YYYY-MM-DD/sip_universe.json

# View today's universe
cat /home/jacobw/intraday_stack/data/daily_sip/date=$(date +%F)/sip_universe.json | jq '.symbols | length'
cat /home/jacobw/intraday_stack/data/daily_sip/date=$(date +%F)/sip_universe.json | jq '.symbols[:10]'
```

## Troubleshooting

### Common Issues

#### 1. Service Won't Start
```bash
# Check service status
systemctl status <service-name>

# View detailed logs
journalctl -u <service-name> --since "1 hour ago"

# Check dependencies
systemctl list-dependencies <service-name>

# Restart service
sudo systemctl restart <service-name>
```

#### 2. IBKR Gateway Connection Issues
```bash
# Check Gateway process
ps aux | grep -i gateway

# Test connection
python3 /home/jacobw/quantstack/scripts/check_portal_status.py

# Check client ID conflicts
# (View in IBKR Gateway GUI)

# Restart Gateway if needed
# (Manual restart required)
```

#### 3. No Trades Generated
```bash
# Check SIP universe
cat /home/jacobw/intraday_stack/data/daily_sip/date=$(date +%F)/sip_universe.json | jq '.symbols | length'

# Check market hours
python3 -c "
from datetime import datetime
import pytz
et = pytz.timezone('America/New_York')
now = datetime.now(et)
print(f'Current ET time: {now}')
print(f'Market hours: 09:30-16:00 ET')
print(f'In market hours: {9.5 <= now.hour + now.minute/60 <= 16}')
"

# Check trading system logs
journalctl -u intraday-paper --since "1 hour ago" | grep -E "candidate|signal|trade"
```

#### 4. Positions Not Closing at EOD
```bash
# Check primary EOD flatten
journalctl -u intraday-paper --since "15:30 today" | grep -E "FLATTEN|EOD"

# Check emergency backup
journalctl -u emergency-eod-close.service --since today

# Manual position check
python3 /home/jacobw/quantstack/close_open_positions.py
```

### Log Analysis

#### Key Log Patterns
```bash
# Trading signals
journalctl -u intraday-paper | grep "candidate"

# Order executions
journalctl -u l2-scalping | grep -E "ORDER|FILL"

# System errors
journalctl --since "1 hour ago" | grep -E "ERROR|CRITICAL"

# Connection issues
journalctl --since "1 hour ago" | grep -E "disconnect|reconnect|connection"
```

#### Performance Monitoring
```bash
# Service resource usage
systemctl status l2-collector l2-scalping intraday-paper

# Disk usage
df -h /home/jacobw/quantstack/data/
df -h /home/jacobw/intraday_stack/data/

# Memory usage
ps aux | grep -E "(python|l2|intraday)" | awk '{sum+=$6} END {print "Total RSS: " sum/1024 " MB"}'
```

## Maintenance

### Daily Maintenance
```bash
# Check service health
systemctl is-failed l2-collector l2-scalping intraday-paper l2-watchdog

# Review error logs
journalctl --since yesterday | grep -E "ERROR|CRITICAL" | tail -20

# Check disk space
df -h /home/jacobw/quantstack/data/ /home/jacobw/intraday_stack/data/

# Verify backup systems
systemctl list-timers emergency-eod-close.timer
```

### Weekly Maintenance
```bash
# Archive old logs
journalctl --vacuum-time=7d

# Clean old L2 data (if needed)
find /home/jacobw/quantstack/data/l2_maximum/features/ -name "date=*" -mtime +30 -exec rm -rf {} \;

# Update system packages
sudo apt update && sudo apt upgrade

# Restart services for fresh start
sudo systemctl restart l2-collector l2-scalping intraday-paper
```

### Monthly Maintenance
```bash
# Full system backup
tar -czf quantstack_backup_$(date +%Y%m%d).tar.gz \
  /home/jacobw/quantstack/ \
  /home/jacobw/intraday_stack/ \
  /etc/systemd/system/*trading* \
  /etc/systemd/system/*l2* \
  /etc/systemd/system/*intraday* \
  /etc/systemd/system/*emergency*

# Performance review
python3 /home/jacobw/quantstack/full_trading_report.py --export monthly_performance.csv

# System health audit
python3 /home/jacobw/quantstack/scripts/definitive_e2e_test.py
```

## Security

### File Permissions
```bash
# Ensure proper ownership
sudo chown -R jacobw:jacobw /home/jacobw/quantstack/ /home/jacobw/intraday_stack/

# Secure configuration files
chmod 600 /home/jacobw/quantstack/l2_scalping/config/*.yaml
chmod 600 /home/jacobw/intraday_stack/configs/*.yaml
```

### API Keys
```bash
# Polygon API key location
/etc/systemd/system/polygon.env

# IBKR credentials
# (Stored in IBKR Gateway configuration)

# NTFY channels
# (Public channels - no authentication required)
```

## Support

### Documentation
- **Current System**: [CURRENT_SYSTEM_OVERVIEW.md](CURRENT_SYSTEM_OVERVIEW.md)
- **Development History**: [DEVELOPMENT_HISTORY.md](DEVELOPMENT_HISTORY.md)
- **IBKR Gateway**: [IBKR_GATEWAY_PROTOCOL.md](IBKR_GATEWAY_PROTOCOL.md)
- **Emergency Procedures**: [EMERGENCY_PROCEDURES.md](EMERGENCY_PROCEDURES.md)

### Contact
- **System Owner**: jacobw
- **NTFY Alerts**: https://ntfy.sh/jacobw-trading-alerts
- **Trade Notifications**: https://ntfy.sh/jacobw-trading-trades

---

*This guide covers daily operations, troubleshooting, and maintenance of the QuantStack trading system.*
