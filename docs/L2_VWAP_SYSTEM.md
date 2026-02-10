# L2 VWAP Mean Reversion System

**Status**: ✅ Production Ready (Pending Installation)  
**Service**: `l2-vwap-reversion.service`  
**Schedule**: Mon-Fri 09:20-16:05 ET  
**Strategy**: VWAP mean reversion with L2 depth filter

---

## Overview

L2 VWAP Mean Reversion is a paper trading system that combines VWAP mean reversion signals with L2 order book depth filtering. It uses the same SIP universe and L2 data as the L2 Scalping system.

### Key Features

- **VWAP Mean Reversion**: Enter when price deviates from VWAP
- **L2 Depth Filter**: Confirm with order book imbalance
- **Bracket Orders**: Automatic SL/TP on every entry
- **Shared Infrastructure**: Uses L2 Scalping's data and universe
- **Full Integration**: PostgreSQL, NTFY, audit logging, EOD reporting

---

## Strategy Logic

### Entry Conditions

**LONG Entry**:
- Price <= VWAP * 0.995 (0.5% below VWAP)
- L2 Ratio >= 1.165 (bid depth > ask depth)
- Time: 09:35-15:30 ET

**SHORT Entry**:
- Price >= VWAP * 1.005 (0.5% above VWAP)
- L2 Ratio <= 0.858 (ask depth > bid depth)
- Time: 09:35-15:30 ET

### Exit Conditions

**Take Profit**:
- LONG: +0.5% from entry
- SHORT: -0.5% from entry

**Stop Loss**:
- LONG: -0.75% from entry
- SHORT: +0.75% from entry

**Mean Reversion Exit**:
- LONG: Price crosses above VWAP
- SHORT: Price crosses below VWAP

**Emergency EOD**:
- All positions closed at 15:55 ET

### Expected Performance

Based on backtest (spread_off variant):
- **Win Rate**: 67.5%
- **Expectancy**: 15.32 bps per trade
- **Avg Hold Time**: ~2 hours
- **Max Positions**: 1 at a time

---

## System Architecture

### Data Flow

```
SIP Universe (intraday_stack) 
    ↓
L2 Scalping (collects L2 data)
    ↓
L2 Data Storage (~/quantstack/data/l2)
    ↓
L2 VWAP (reads L2 features + generates signals)
    ↓
IBKR (executes bracket orders)
    ↓
PostgreSQL (records trades)
```

### Dependencies

**Required Services**:
- `l2-scalping.service` - Must run first (provides L2 data)
- `intraday-sip.timer` - Generates daily universe

**Data Sources**:
- SIP Universe: `/home/jacobw/intraday_stack/data/daily_sip/date=YYYY-MM-DD/sip_universe.json`
- L2 Features: `/home/jacobw/quantstack/data/l2/l2_maximum/features/`

**Shared Infrastructure**:
- PostgreSQL: `trading` database
- NTFY: Trade notifications
- Audit Logger: System events
- EOD Report: Daily performance

---

## Installation

### 1. Install Service Files

```bash
# Copy service and timer to systemd
cp ~/quantstack/systemd/l2-vwap-reversion.service ~/.config/systemd/user/
cp ~/quantstack/systemd/l2-vwap-reversion.timer ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload
```

### 2. Verify Configuration

```bash
# Check L2 data path
grep "L2_DATA_ROOT" ~/quantstack/l2_vwap_reversion/config/strategy.yaml

# Should show: /home/jacobw/quantstack/data/l2/l2_maximum/features
```

### 3. Enable and Start

```bash
# Enable timer (auto-start daily)
systemctl --user enable l2-vwap-reversion.timer

# Start timer
systemctl --user start l2-vwap-reversion.timer

# Verify timer is active
systemctl --user list-timers | grep vwap
```

### 4. Manual Test (Optional)

```bash
# Test service manually
systemctl --user start l2-vwap-reversion.service

# Check logs
journalctl --user -u l2-vwap-reversion.service -f

# Check status
systemctl --user status l2-vwap-reversion.service
```

---

## Configuration

### Main Config

**File**: `~/quantstack/l2_vwap_reversion/config/strategy.yaml`

```yaml
strategy:
  name: "L2_VWAP_Mean_Reversion"
  variant: "spread_off"

vwap:
  deviation_long: 0.995   # -0.5%
  deviation_short: 1.005  # +0.5%

l2_filter:
  enabled: true
  ratio_long: 1.165       # Bid/Ask >= 1.165
  ratio_short: 0.858      # Bid/Ask <= 0.858

exits:
  take_profit_long: 1.005   # +0.5%
  stop_loss_long: 0.9925    # -0.75%

timing:
  entry_start: "09:35"
  entry_end: "15:30"
  forced_exit: "15:55"

risk:
  position_size: 100
  max_positions: 1

universe:
  max_symbols: 3  # Same as L2 Scalping

l2_data:
  features_path: "/home/jacobw/quantstack/data/l2/l2_maximum/features"
```

### Service Config

**File**: `~/.config/systemd/user/l2-vwap-reversion.service`

```ini
[Unit]
Description=L2 VWAP Mean Reversion Paper Trading
After=network.target l2-scalping.service
Requires=l2-scalping.service

[Service]
Type=simple
WorkingDirectory=/home/jacobw/quantstack/l2_vwap_reversion
Environment=PYTHONPATH=/home/jacobw/quantstack/l2_vwap_reversion/src:/home/jacobw/quantstack
Environment=L2_DATA_ROOT=/home/jacobw/quantstack/data/l2
ExecStart=/home/jacobw/quantstack/.venv/bin/python src/main.py --config config
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
```

### Timer Config

**File**: `~/.config/systemd/user/l2-vwap-reversion.timer`

```ini
[Unit]
Description=L2 VWAP Mean Reversion Timer

[Timer]
# 09:20 ET = 22:20 Manila (UTC+8) during EST
OnCalendar=Mon-Fri 22:20:00
Persistent=true

[Install]
WantedBy=timers.target
```

---

## Integration Points

### 1. PostgreSQL Database

**Tables Used**:
- `trades` - Trade records (entry/exit)
- `decisions` - Signal decisions
- `fills` - Order fills (from IBKR)
- `orders` - Order submissions

**System Tag**: `l2-vwap-reversion`

**Query Example**:
```sql
SELECT * FROM trades 
WHERE system = 'l2-vwap-reversion' 
  AND entry_time::date = CURRENT_DATE
ORDER BY entry_time DESC;
```

### 2. NTFY Notifications

**Entry Notification**:
```
Opening JOBY position
Time: 09:45:23 ET
Strategy: l2-vwap-reversion
Side: LONG
Quantity: 100
Price: $11.25
Value: $1,125.00
```

**Exit Notification**:
```
Closing position JOBY
Time: 09:47:15 ET
Symbol: JOBY
Strategy: l2-vwap-reversion
Exit Price: $11.30
Quantity: 100
PnL: $5.00
Reason: take_profit
```

### 3. Audit Logging

**Log File**: `~/quantstack/logs/audit/audit_YYYY-MM-DD.jsonl`

**Events Logged**:
- Service start/stop
- Trade entries/exits
- Signal generation
- Errors and warnings

**Example**:
```json
{
  "timestamp_et": "2026-01-30T09:45:23-05:00",
  "event_type": "TRADE_SIGNAL",
  "service": "l2-vwap-reversion",
  "message": "ENTRY LONG 100 JOBY @ 11.25",
  "context": {
    "symbol": "JOBY",
    "vwap": 11.30,
    "l2_ratio": 1.25,
    "stop_loss": 11.17,
    "take_profit": 11.31
  }
}
```

### 4. EOD Reporting

**Script**: `~/quantstack/scripts/eod_report.py`

L2 VWAP trades are automatically included in the unified EOD report:

```bash
python3 ~/quantstack/scripts/eod_report.py --date 2026-01-30
```

**Output Includes**:
- Performance by system (includes l2-vwap-reversion)
- Performance by strategy
- Performance by symbol
- Exit reason analysis
- Risk metrics

---

## Monitoring

### Health Checks

```bash
# Check service status
systemctl --user status l2-vwap-reversion.service

# Check timer status
systemctl --user list-timers | grep vwap

# Check recent logs
journalctl --user -u l2-vwap-reversion.service --since today

# Check for errors
journalctl --user -u l2-vwap-reversion.service -p err --since today
```

### Database Checks

```sql
-- Check today's trades
SELECT COUNT(*), SUM(net_pnl) as total_pnl
FROM trades 
WHERE system = 'l2-vwap-reversion' 
  AND entry_time::date = CURRENT_DATE;

-- Check last trade time
SELECT MAX(entry_time) as last_trade
FROM trades 
WHERE system = 'l2-vwap-reversion';

-- Check win rate (last 7 days)
SELECT 
    COUNT(*) as trades,
    SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as winners,
    ROUND(100.0 * SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate
FROM trades 
WHERE system = 'l2-vwap-reversion' 
  AND entry_time >= CURRENT_DATE - INTERVAL '7 days'
  AND status = 'CLOSED';
```

### Alert Conditions

**Critical**:
- Service not running during market hours
- No trades in 3+ hours (during market hours)
- Database connection failures

**Warning**:
- Win rate < 60% (over 20+ trades)
- Avg P&L < 5 bps
- L2 data not available

---

## Troubleshooting

### Service Won't Start

```bash
# Check dependencies
systemctl --user status l2-scalping.service

# Check logs for errors
journalctl --user -u l2-vwap-reversion.service -n 50

# Verify L2 data exists
ls -la ~/quantstack/data/l2/l2_maximum/features/

# Check SIP universe
ls -la ~/intraday_stack/data/daily_sip/date=$(date +%Y-%m-%d)/
```

### No Trades Generated

**Check**:
1. L2 Scalping is running (provides data)
2. SIP universe has symbols
3. Market is open (09:35-15:30 ET)
4. L2 data is recent (check timestamps)
5. VWAP deviation conditions met

**Debug**:
```bash
# Check strategy logs
tail -f ~/quantstack/l2_vwap_reversion/logs/vwap_reversion_$(date +%Y%m%d).log

# Check L2 data freshness
ls -lt ~/quantstack/data/l2/l2_maximum/features/ | head -10
```

### Database Connection Issues

```bash
# Test PostgreSQL connection
psql -d trading -U jacobw -c "SELECT 1;"

# Check event store initialization
grep "PostgreSQL event store" ~/quantstack/l2_vwap_reversion/logs/vwap_reversion_*.log
```

---

## Performance Tracking

### Daily Metrics

```sql
-- Daily performance summary
SELECT 
    entry_time::date as date,
    COUNT(*) as trades,
    SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) as winners,
    ROUND(AVG(net_pnl), 2) as avg_pnl,
    ROUND(SUM(net_pnl), 2) as total_pnl,
    ROUND(100.0 * SUM(CASE WHEN net_pnl > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) as win_rate
FROM trades 
WHERE system = 'l2-vwap-reversion'
  AND entry_time >= CURRENT_DATE - INTERVAL '30 days'
GROUP BY entry_time::date
ORDER BY date DESC;
```

### Strategy Validation

Compare actual vs expected performance:

| Metric | Expected | Actual | Status |
|--------|----------|--------|--------|
| Win Rate | 67.5% | TBD | ⏳ |
| Expectancy | 15.32 bps | TBD | ⏳ |
| Avg Hold | ~2 hours | TBD | ⏳ |

---

## Maintenance

### Daily Tasks

- ✅ Verify service started (automated via timer)
- ✅ Check EOD report for performance
- ✅ Review NTFY notifications

### Weekly Tasks

- Review win rate and expectancy
- Check for any errors in logs
- Verify L2 data quality

### Monthly Tasks

- Compare performance vs backtest
- Review strategy parameters
- Analyze exit reasons

---

## Related Documentation

- [Strategy Design](../l2_vwap_reversion/docs/STRATEGY_DESIGN.md) - Full strategy specification
- [L2 Scalping System](L2_SCALPING_SYSTEM_DESIGN.md) - Dependency system
- [Operations Runbook](OPERATIONS.md) - Daily reporting & procedures
- [Infrastructure](INFRASTRUCTURE.md) - IBKR, Trade DB, Audit system
- [System Guide](SYSTEM_GUIDE.md) - Overall system architecture

---

**Last Updated**: 2026-01-30
