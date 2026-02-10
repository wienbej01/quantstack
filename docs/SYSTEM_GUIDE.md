# Quantstack Trading System - Complete Guide

**Version**: 10.0  
**Date**: 2026-02-10  
**Status**: Production (IBKR Gateway + ib_insync + systemd timers + PostgreSQL)

## System Overview

Automated trading system running L2 scalping, L2 VWAP reversion, and intraday paper trading strategies on IBKR paper account.

**Key Components**:
- IBKR Gateway (manual auth required daily)
- L2 Scalping (trades + L2 data collection + overnight safeguards)
- L2 VWAP Reversion (VWAP mean reversion with L2 filter)
- L2 Health Monitor (auto-recovery for zombie subscriptions)
- Shared Position Ledger (cross-service margin awareness) — NEW v10
- Exit Guard + Margin Checker (Feb 9 incident fixes) — NEW v10

> **Feb 9 Incident Fixes (v10)**: Exit retry circuit breaker, pre-trade margin checks via IBKR whatIfOrder, shared position ledger with global margin budget, CPU spike alerting, EOD flatten hardening. See [SPRINT_FEB9_INCIDENT_FIX.md](SPRINT_FEB9_INCIDENT_FIX.md) and [INCIDENT_LOG.md](INCIDENT_LOG.md).
- Intraday Paper Trading
- Daily SIP universe generation
- PostgreSQL event store (migrated from SQLite)
- Systemd timer orchestration
- NTFY notifications
- Audit logging
- Emergency EOD close

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     IBKR Gateway (7494)                      │
│              (Manual start + browser auth daily)             │
└──────────────────────┬──────────────────────────────────────┘
                       │
       ┌───────────────┼───────────────┬───────────────┐
       │               │               │               │
       ▼               ▼               ▼               ▼
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ L2 Scalping │ │ L2 VWAP     │ │   Intraday  │ │   Position  │
│  (Client    │ │ Reversion   │ │    Paper    │ │   Monitor   │
│  200, 250)  │ │ (300, 350)  │ │ (Client 111)│ │ (Client 998)│
│             │ │             │ │             │ │             │
│ • Bracket   │ │ • Bracket   │ │ • Bracket   │ │             │
│   Orders    │ │   Orders    │ │   Orders    │ │             │
│ • L2 Data   │ │ • Uses L2   │ │             │ │             │
│   Collect   │ │   from L2S  │ │             │ │             │
└──────┬──────┘ └──────┬──────┘ └─────────────┘ └─────────────┘
       │               │               │               │
       │               │               └───────┬───────┘
       │               │                       ▼
       │               │              ┌─────────────────┐
       │               └──────────────│  PostgreSQL DB  │
       │                              │   (trading)     │
       │                              │  User: jacobw   │
       │                              └─────────────────┘
       ▼
┌─────────────┐
│   Health    │
│   Monitor   │
│ (Auto-      │
│  Recovery)  │
└─────────────┘
```

---

## Services & Timers

### Daily Schedule (America/New_York)

**START (Morning)**:
| Time ET | Manila | Service | Action |
|---------|--------|---------|--------|
| 09:00 | 22:00 | preflight-check | Validate Gateway + Polygon |
| 09:10 | 22:10 | intraday-sip | Generate SIP universe |
| 09:20 | 22:20 | l2-vwap-reversion | Start VWAP trading (auto-starts l2-scalping) |
| 09:28 | 22:28 | intraday-paper | Start paper trading |
| 09:30 | 22:30 | **MARKET OPEN** | |
| 09:40 | 22:40 | market-open-health-check | Verify systems running |

**STOP (Evening)**:
| Time ET | Manila | Service | Action |
|---------|--------|---------|--------|
| 15:55 | 04:55+1 | emergency-eod-close | Force close positions |
| 17:00 | 06:00+1 | l2-vwap-reversion-stop | Stop VWAP trading |
| 17:01 | 06:01+1 | l2-scalping-stop | Stop L2 scalping |
| 17:02 | 06:02+1 | intraday-paper-stop | Stop paper trading |
| 17:10 | 06:10+1 | daily-trade-report | Generate EOD report |

**Notes**:
- l2-scalping starts automatically as dependency of l2-vwap-reversion (`Requires=`)
- l2-collector is **ARCHIVED** - l2-scalping handles L2 data collection
- All times are Mon-Fri only

### Service Details

#### L2 Scalping (`l2-scalping.service`)
- **Location**: `/home/jacobw/quantstack/l2_scalping/`
- **Entry**: `src/main.py`
- **Client IDs**: 200 (orders), 250 (data)
- **Function**: L2 order book scalping + data collection
- **Data Output**: `/home/jacobw/quantstack/data/l2_maximum/features/`
- **Config**: `l2_scalping/config/*.yaml`
- **Symbols**: From SIP (NYSE-only, max 3)
- **Overnight Protection**:
  - Bracket orders (stop-loss + profit-target) on every entry
  - Entry curfew: Blocks entries after 15:49 ET (with 600s max hold)
  - Force exit: Market order at 600s max hold time
  - Polling backup: Checks exits every 10ms
  - Emergency EOD: Timer at 15:55 ET

#### L2 VWAP Reversion (`l2-vwap-reversion.service`)
- **Location**: `/home/jacobw/quantstack/l2_vwap_reversion/`
- **Entry**: `src/main.py`
- **Client IDs**: 300-349 (orders), 350-399 (data) - dynamic allocation
- **Function**: VWAP mean reversion with L2 depth filter
- **Strategy**: Long when close <= VWAP * 0.995 + L2 ratio >= 1.165
- **Data Source**: L2 features from l2-scalping output
- **Symbols**: Same SIP symbols as l2-scalping (max 3)
- **Timer**: User-level (`~/.config/systemd/user/l2-vwap-reversion.timer`)
- **Dependencies**: `Requires=l2-scalping.service` (auto-starts l2-scalping)
- **Features**:
  - Bracket orders with SL/TP (tick size rounded)
  - Dynamic client ID management (avoids Gateway caching issues)
  - EOD flatten at 15:55 ET
  - PostgreSQL trade database
  - NTFY notifications
  - Audit logging
- **Expected**: 67.5% win rate, 15.32 expectancy

#### Intraday Paper (`intraday-paper.service`)
- **Location**: `/home/jacobw/intraday_stack/`
- **Entry**: `scripts/paper_trade.py`
- **Client ID**: 111
- **Function**: Intraday paper trading with bracket orders
- **Data Output**: PostgreSQL database `trading` (user: jacobw)
- **Config**: `intraday_stack/configs/`
- **Symbols**: From SIP

#### SIP Generation (`intraday-sip.timer`)
- **Location**: `/home/jacobw/intraday_stack/`
- **Entry**: `scripts/generate_daily_sip_universe.py`
- **Function**: Daily universe selection (HMM scoring)
- **Output**: `/home/jacobw/intraday_stack/data/daily_sip/date=YYYY-MM-DD/sip_universe.json`
- **Filters**: NYSE-only (excludes ARCA ETFs like UNG, SLV)

#### Position Monitor (`position-monitor.service`)
- **Location**: `/home/jacobw/quantstack/`
- **Entry**: `position_monitor/main.py`
- **Client ID**: 998
- **Function**: Real-time position tracking for Conky display
- **Output**: `/tmp/positions.json`

#### L2 Health Monitor (`l2-health-monitor.service`)
- **Location**: `/home/jacobw/quantstack/scripts/l2_health_monitor.py`
- **Function**: Auto-recovery for zombie depth subscriptions
- **Monitors**: Error 309 (max depth), Error 326 (client ID conflicts), data flow
- **Recovery**: Stops service, clears subscriptions, restarts service
- **Check Interval**: 60 seconds
- **Max Attempts**: 3 recovery attempts with 5-minute cooldown
- **Auto-start**: Enabled (starts with l2-scalping)

---

## File Locations

### Code
```
/home/jacobw/quantstack/
├── l2_scalping/          # L2 scalping system
│   ├── src/main.py       # Main entry point
│   ├── config/           # Strategy configs
│   └── src/data/l2_feed.py  # L2 data + storage
├── l2_vwap_reversion/    # L2 VWAP mean reversion (NEW)
│   ├── src/main.py       # Main entry point
│   ├── config/           # Strategy configs
│   └── src/reporting/trade_journal.py  # PostgreSQL + audit
├── qx-l2/                # L2 collector (DISABLED - l2-scalping handles this)
├── qx-*/                 # Framework packages
├── cpapi/                # IBKR Client Portal API + audit logger
├── scripts/              # Operational scripts
└── systemd/              # Service definitions

/home/jacobw/intraday_stack/
├── scripts/paper_trade.py        # Paper trading main
├── scripts/generate_daily_sip_universe.py  # SIP generation
├── src/journal/event_store.py    # Shared event store
└── configs/              # Trading configs
```

### Data
```
/home/jacobw/quantstack/data/l2_maximum/
├── features/date=YYYY-MM-DD/symbol=TICKER/*.parquet  # L2 features (from l2-scalping)
└── selection_log/YYYY-MM-DD.json  # Symbol selection log

/home/jacobw/intraday_stack/data/
└── daily_sip/date=YYYY-MM-DD/sip_universe.json  # Daily universe

PostgreSQL Database (trading):
├── trades          # Trade entries and exits
├── decisions       # Trading decisions
├── orders          # Order history
├── fills           # Fill executions
└── signals         # Signal history
```

### Logs
```
/home/jacobw/quantstack/logs/
├── audit/                # Audit logs (JSONL + human-readable)
└── paper_trade.log       # Intraday paper logs

/home/jacobw/quantstack/l2_vwap_reversion/logs/
├── vwap_reversion_YYYYMMDD.log  # System logs
└── trades_YYYY-MM-DD.jsonl      # Trade journal (local backup)

journalctl -u l2-scalping
journalctl -u l2-vwap-reversion
journalctl -u intraday-paper
journalctl -u intraday-sip
journalctl -u l2-health-monitor
```

### Configs
```
/home/jacobw/quantstack/l2_scalping/config/
├── strategy.yaml         # L2 scalping rules
├── risk.yaml             # Risk limits
└── ibkr.yaml             # IBKR connection + client ID ranges

/home/jacobw/quantstack/l2_vwap_reversion/config/
├── strategy.yaml         # VWAP strategy rules
└── ibkr.yaml             # IBKR connection + client ID ranges (300-399)

/home/jacobw/quantstack/archive/l2-collector-deprecated/
└── *.yaml                # ARCHIVED - l2-collector configs (DO NOT USE)

/home/jacobw/intraday_stack/configs/
└── paper_trading.yaml    # Paper trading config

~/.quantstack/
├── client_id_ranges.yaml # Central client ID allocation registry
└── client_ids/           # Per-service client ID state files

/etc/systemd/system/
├── l2-scalping.service
├── l2-scalping.timer     # (inactive - starts via l2-vwap dependency)
├── l2-scalping-stop.timer
├── l2-vwap-reversion-stop.timer  # NEW
├── l2-vwap-reversion-stop.service  # NEW
├── intraday-paper.service
├── intraday-paper.timer
├── intraday-paper-stop.timer
├── intraday-sip.timer
├── emergency-eod-close.timer
├── market-open-health-check.timer
├── daily-trade-report.timer
└── preflight-check.timer

~/.config/systemd/user/
└── l2-vwap-reversion.timer  # User-level timer (09:20 ET)
```

---

## Daily Startup Procedure

### 1. Start IBKR Gateway (Manual)
```bash
# Start Gateway application
# Login to paper account DUN575068
# Enable API: Configure > Settings > API > Settings
#   - Enable ActiveX and Socket Clients: ✓
#   - Socket port: 7494
#   - Trusted IPs: 127.0.0.1
# Accept paper trading disclaimer
```

### 2. Verify Gateway
```bash
# Check port listening
ss -ltn | grep :7494

# Test connection
python3 -c "from ib_insync import IB; ib=IB(); ib.connect('127.0.0.1',7494,999); print('OK'); ib.disconnect()"
```

### 3. Timers Handle Rest
Systemd timers automatically start services at scheduled times. No manual intervention needed.

---

## Operations

### Check System Status
```bash
# Service status
systemctl status l2-scalping intraday-paper position-monitor l2-health-monitor

# Timer schedule
systemctl list-timers l2-scalping.timer intraday-paper.timer intraday-sip.timer

# Recent logs
journalctl -u l2-scalping -n 50
journalctl -u intraday-paper -n 50

# End-of-day performance report
python3 /home/jacobw/quantstack/scripts/eod_report.py --date $(date +%F)

# Export to CSV
python3 /home/jacobw/quantstack/scripts/eod_report.py --date $(date +%F) --csv report.csv
```

### Manual Service Control
```bash
# Start/stop services
sudo systemctl start l2-scalping
sudo systemctl stop l2-scalping
sudo systemctl restart l2-scalping

# Enable/disable timers
sudo systemctl enable l2-scalping.timer
sudo systemctl disable l2-scalping.timer
```

### Emergency Stop
```bash
# Stop all trading
sudo systemctl stop l2-scalping intraday-paper

# Force close positions (runs automatically at 15:55 ET)
python3 /home/jacobw/quantstack/scripts/emergency_eod_close.py
```

---

## Data Collection

### L2 Data
L2-scalping now handles L2 data collection (l2-collector is disabled).

**Storage**: `/home/jacobw/quantstack/data/l2_maximum/features/date=YYYY-MM-DD/`

**Check collection**:
```bash
# Files written today
find /home/jacobw/quantstack/data/l2_maximum/features/date=$(date +%F) -name "*.parquet" | wc -l

# Recent files
find /home/jacobw/quantstack/data/l2_maximum/features/date=$(date +%F) -name "*.parquet" -newermt "5 min ago" | wc -l
```

### Trade Data
**Location**: PostgreSQL database `trading` (user: jacobw)

**Query**:
```bash
# Connect to database
psql -d trading -U jacobw

# Recent trades
SELECT * FROM trades WHERE entry_time::date = CURRENT_DATE ORDER BY entry_time DESC LIMIT 10;

# Today's P&L
SELECT 
    COUNT(*) as trades,
    SUM(pnl) as total_pnl,
    AVG(pnl) as avg_pnl
FROM trades 
WHERE exit_time::date = CURRENT_DATE;

# Exit reasons
SELECT exit_reason, COUNT(*) 
FROM trades 
WHERE exit_time::date = CURRENT_DATE 
GROUP BY exit_reason;
```

---

## Symbol Selection

### SIP Universe
Generated daily at 09:10 ET by `intraday-sip.timer`.

**File**: `/home/jacobw/intraday_stack/data/daily_sip/date=YYYY-MM-DD/sip_universe.json`

**Format**:
```json
{
  "date": "2026-01-20",
  "symbols": ["INTC", "NVTS", "NVAX", "NOW", "ACHR"],
  "scores": {"INTC": 0.73, "NVTS": 0.73, ...}
}
```

### NYSE Filtering
Both l2-scalping and intraday-paper filter for NYSE-only symbols:
- **Excluded**: ARCA ETFs (UNG, SLV, SPY, QQQ, etc.)
- **Included**: NYSE stocks only
- **Limit**: 3 symbols max (IBKR depth subscription limit)

**Known ARCA ETFs**: UNG, SPY, QQQ, IWM, EFA, EEM, GLD, SLV, TLT, HYG

---

## IBKR Connection

### Client ID Allocation
| Service | Client ID Range | Purpose |
|---------|-----------------|---------|
| L2 Collector | 1-99 | **ARCHIVED** |
| Intraday Paper | 100-199 | Trading |
| L2 Scalping | 200-299 | Orders (200-249), Data (250-299) |
| L2 VWAP Reversion | 300-399 | Orders (300-349), Data (350-399) |
| Reserved | 400-899 | Future services |
| Utilities | 900-999 | Preflight (998), Monitor (999) |

**Client ID Management**:
- Services use `cpapi/client_id_manager.py` for dynamic allocation
- IDs increment within range on each startup (avoids Gateway caching)
- State persisted to `~/.quantstack/client_ids/{service}.json`
- Central registry: `~/.quantstack/client_id_ranges.yaml`

### Connection Details
- **Host**: 127.0.0.1
- **Port**: 7494
- **Account**: DUN575068 (paper)
- **Max Depth Subscriptions**: 3 per account

---

## Notifications

### NTFY
Trade notifications sent to `ntfy.sh/jacobw-trading-alerts`.

**Rate Limit**: Free tier has daily message limit. System may hit limit during high-frequency trading.

**Check**:
```bash
journalctl -u l2-scalping | grep -i ntfy | tail -10
```

---

## Troubleshooting

### Gateway Issues
```bash
# Gateway not responding
ss -ltn | grep :7494  # Check if listening

# Restart Gateway (manual)
# Close Gateway app, restart, re-authenticate

# Clear zombie depth subscriptions
python3 /home/jacobw/quantstack/scripts/clear_ibkr_depth_subscriptions.py
```

### Service Issues
```bash
# Service failed to start
journalctl -u l2-scalping -n 50

# PostgreSQL connection issues
psql -d trading -U jacobw -c "SELECT 1"  # Test connection

# Symbol mismatch
# Both systems now use same NYSE filter

# No trades
# Check if market is open, symbols are valid, Gateway is connected

# Overnight positions
# Check logs for:
#   - "Entry blocked by curfew" (entry curfew working)
#   - "FORCE EXIT" (max hold exceeded)
#   - "Bracket order placed" (bracket orders active)
```

### Data Issues
```bash
# No L2 data being written
find /home/jacobw/quantstack/data/l2_maximum/features/date=$(date +%F) -name "*.parquet" -newermt "5 min ago" | wc -l

# L2-scalping handles data collection now (l2-collector disabled)
systemctl status l2-scalping

# Zombie depth subscriptions (Error 309)
# Health monitor auto-recovers, or manually:
python3 /home/jacobw/quantstack/scripts/clear_ibkr_depth_subscriptions.py
sudo systemctl restart l2-scalping

# Check health monitor
journalctl -u l2-health-monitor -f
```

---

## Post-Outage Recovery

See `docs/POST_OUTAGE_RECOVERY.md` for detailed recovery procedures.

**Quick steps**:
1. Verify Gateway is running and authenticated
2. Clear zombie depth subscriptions if needed
3. Restart services: `sudo systemctl restart l2-scalping intraday-paper`
4. Verify positions sync with IBKR
5. Check scheduled exits are active

---

## Key Changes (v9.0)

### L2-VWAP Fixes (v9.0) - 2026-01-31
1. **Event Loop Fix**: Fixed "event loop already running" error in order submission
   - Changed direct `ib.placeOrder()` calls to use `session.call()` wrapper
   - All bracket order submissions now work correctly

2. **Client ID Management**: Added dynamic client ID allocation
   - Created `cpapi/client_id_manager.py` for shared client ID management
   - L2-VWAP uses range 300-399 with auto-increment on reconnect
   - Prevents "ClientId already in use" errors after crashes/restarts

3. **Timer Cleanup**:
   - Removed duplicate system-level `l2-vwap-reversion.timer`
   - User-level timer at 09:20 ET is now the only l2-vwap timer
   - Added `l2-vwap-reversion-stop.timer` at 17:00 ET

4. **L2-Collector Archived**:
   - Moved all l2-collector files to `archive/l2-collector-deprecated/`
   - Removed systemd service and timer files
   - L2 data collection handled by l2-scalping

### Database Migration (v7.0-8.0)
1. **PostgreSQL Migration**: Migrated from SQLite to PostgreSQL for all production systems
   - Database: `trading`, User: `jacobw`, Auth: peer
   - Migrated 68 trades, 250,225 decisions, 75 orders, 41 fills
   - Fixed EventStore PostgreSQL compatibility issues
   - All services now use PostgreSQL exclusively

### Overnight Position Safeguards (v7.0)
2. **5-Layer Protection System**: Ensures no positions remain open overnight
   - **Bracket Orders**: Automatic stop-loss (10 bps) + profit-target (15 bps) on every entry
   - **Entry Curfew**: Blocks entries after 15:49 ET (with 600s max hold + 60s buffer)
   - **Force Exit**: Market order at 600s max hold time (priority 1)
   - **Polling Backup**: Continuous monitoring every 10ms
   - **Emergency EOD**: Timer at 15:55 ET (final safety net)

### Previous Changes (v6.0)
3. **L2 Data Collection**: Now handled by l2-scalping (l2-collector disabled)
4. **Symbol Alignment**: Both systems use identical NYSE filtering
5. **Intraday Paper**: Fixed SYNC bug and EventStore crashes
6. **Timer Management**: l2-collector timer disabled

---

## Trade Reconciliation

### Overview
Trade-by-trade reconciliation validates data integrity across three sources:
- **TradeDB** (PostgreSQL) - Trade records
- **Audit Log** (JSONL) - Event trail
- **IBKR API Log** - Broker execution data

### Run Reconciliation
```bash
# Auto-detect IBKR log location
python3 ~/quantstack/scripts/reconcile_trades.py --date 2026-02-02

# Explicit IBKR log path
python3 ~/quantstack/scripts/reconcile_trades.py --date 2026-02-02 \
    --ibkr-log /home/jacobw/IBKRlogs/20260202/api-exported-logs.txt

# Custom IBKR log directory
python3 ~/quantstack/scripts/reconcile_trades.py --date 2026-02-02 \
    --ibkr-dir /custom/path
```

### What It Validates
| Check | Description | Tolerance |
|-------|-------------|-----------|
| Entry Qty Match | DB qty = IBKR fill qty | Exact |
| Exit Qty Match | DB qty = IBKR fill qty | Exact |
| Entry Price Match | DB price = IBKR VWAP | $0.01 |
| Exit Price Match | DB price = IBKR VWAP | $0.01 |
| PnL Calculation | DB PnL = (exit - entry) × qty | $1.00 |
| Slippage | Recorded vs actual | $0.02 |
| Audit Open Event | TRADE_OPEN logged | Present |
| Audit Close Event | TRADE_CLOSE logged | Present |

### Output
- **Console**: Summary + detailed issues
- **JSON Report**: `~/quantstack/logs/reconciliation/reconciliation_YYYY-MM-DD.json`

### Status Codes
- **PASS**: All checks passed
- **WARN**: Minor issues (e.g., missing audit events)
- **FAIL**: Critical issues (price/qty mismatch)

### Data Integrity Checks
- Orphan IBKR orders (fills with no DB trade)
- DB trades with no IBKR fills
- Audit log coverage percentage
- Price accuracy rate
- PnL verification rate

### IBKR Log Location
IBKR API logs are stored in: `/home/jacobw/IBKRlogs/YYYYMMDD/api-exported-logs.txt`

Export logs daily from IBKR Gateway: File > Export API Logs

### Recommended Schedule
Run reconciliation after market close each day:
```bash
# Add to daily-trade-report or run manually
python3 ~/quantstack/scripts/reconcile_trades.py --date $(date +%F)
```

---

## References

- **Connection Protocol**: `docs/IBKR_IB_INSYNC_CONNECTION_PROTOCOL.md`
- **L2 Scalping Design**: `docs/L2_SCALPING_SYSTEM_DESIGN.md`
- **Overnight Position Safeguards**: `l2_scalping/docs/OVERNIGHT_POSITION_SAFEGUARDS.md`
- **PostgreSQL Migration**: `docs/POSTGRESQL_MIGRATION.md`
- **SQLite Removal Verification**: `docs/SQLITE_REMOVAL_VERIFICATION.md`
- **Post-Outage Recovery**: `docs/POST_OUTAGE_RECOVERY.md`
- **Timezone Guide**: `docs/TIMEZONE_GUIDE.md`
- **Audit Logging**: `docs/INFRASTRUCTURE.md` (Section 3)
- **Trade Reconciliation**: `scripts/reconcile_trades.py`
