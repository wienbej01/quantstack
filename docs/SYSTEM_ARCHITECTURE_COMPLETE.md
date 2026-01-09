# Complete System Architecture & Component Map

## Executive Summary

The trading system consists of 8 systemd services orchestrating data collection, SIP generation, L2 microstructure analysis, and live paper trading. All components communicate via IBKR Gateway, Polygon API, and NTFY notifications.

---

## 1. SYSTEMD SERVICES (Entry Points)

### 1.1 Trading Orchestrator
**Service**: `trading-orchestrator.service` / `trading-orchestrator.timer`
**Schedule**: Daily at 21:00 Manila (08:00 ET)
**Entry Point**: `/home/jacobw/quantstack/bulletproof_orchestrator.py`

**Responsibilities**:
- SIP universe generation (1796 symbols → ~20 qualified)
- Gateway health checks
- Service monitoring
- NTFY status updates

**Key Files**:
- `bulletproof_orchestrator.py` - Main orchestrator
- `multi_session_sip_generator.py` - SIP generation logic
- `trading_orchestrator.py` - Legacy orchestrator (backup)

---

### 1.2 Pre-Flight Check
**Service**: `preflight-check.service` / `preflight-check.timer`
**Schedule**: Daily at 20:00 Manila (07:00 ET)
**Entry Point**: `/home/jacobw/quantstack/scripts/preflight_check.py`

**Responsibilities**:
- IBKR Gateway connectivity test
- Polygon API validation
- Service status checks
- Pre-market validation

**Key Files**:
- `scripts/preflight_check.py` - Validation logic
- `scripts/ibkr_preflight.py` - IBKR connection test

---

### 1.3 L2 Collector
**Service**: `l2-collector.service` / `l2-collector.timer`
**Schedule**: Continuous (starts at 22:25 Manila / 09:25 ET)
**Entry Point**: `/home/jacobw/.local/bin/l2-collect`

**Responsibilities**:
- L2 order book data collection (NYSE)
- Dynamic symbol rotation (3 concurrent max)
- Feature engineering (32 features per snapshot)
- Parquet file storage

**Key Files**:
- `qx-l2/configs/maximum_l2.yaml` - Configuration
- `qx-l2/src/` - L2 collection logic
- `data/l2_maximum/features/` - Output storage

---

### 1.4 L2 Scalping
**Service**: `l2-scalping.service`
**Schedule**: Continuous (starts at 22:25 Manila / 09:25 ET)
**Entry Point**: `/home/jacobw/quantstack/l2_scalping/src/main.py`

**Responsibilities**:
- L2-based scalping signals
- Order execution via IBKR
- Risk management
- Trade logging

**Key Files**:
- `l2_scalping/src/main.py` - Main entry
- `l2_scalping/src/execution/order_manager.py` - Order execution
- `l2_scalping/src/data/l2_feed.py` - L2 data feed
- `l2_scalping/src/signals/l2_signals.py` - Signal generation
- `l2_scalping/config/` - Strategy configuration

---

### 1.5 Intraday Paper Trading
**Service**: `intraday-paper.service` / `intraday-paper.timer`
**Schedule**: Continuous (starts at 22:25 Manila / 09:25 ET)
**Entry Point**: `/home/jacobw/intraday_stack/scripts/paper_trade.py`

**Responsibilities**:
- Reversal strategy trading
- SIP universe trading
- Trade journal logging
- NTFY trade notifications

**Key Files**:
- `scripts/paper_trade.py` - Main trading loop
- `src/journal/event_store.py` - Trade logging
- `src/notifications/ntfy_notifier.py` - Notifications
- `src/universe/polygon_sip_universe.py` - SIP loading
- `src/signals/candidate_generator.py` - Signal generation

---

### 1.6 Intraday SIP Refresh
**Service**: `intraday-sip.service` / `intraday-sip.timer`
**Schedule**: Daily at 21:45 Manila (08:45 ET)
**Entry Point**: `/home/jacobw/intraday_stack/scripts/refresh_sip.py`

**Responsibilities**:
- Refresh SIP universe mid-day
- Update trading symbols

---

### 1.7 L2 Watchdog
**Service**: `l2-watchdog.service`
**Schedule**: Continuous
**Entry Point**: `/home/jacobw/quantstack/scripts/l2_watchdog.py`

**Responsibilities**:
- Monitor L2 collector health
- Auto-restart on failure
- Collection statistics

---

### 1.8 System Health Monitor
**Service**: `system-health-monitor.service` / `system-health-monitor.timer`
**Schedule**: Every 5 minutes (market hours only)
**Entry Point**: `/home/jacobw/quantstack/system_health_monitor.py`

**Responsibilities**:
- Service status checks
- CRITICAL error detection
- NTFY alerts on failures
- Gateway accessibility checks

---

## 2. DATA FLOW ARCHITECTURE

```
┌─────────────────────────────────────────────────────────────────┐
│                        EXTERNAL DATA SOURCES                     │
├─────────────────────────────────────────────────────────────────┤
│  IBKR Gateway (7497)  │  Polygon API  │  Gold Data (GCS Mount)  │
└──────────┬──────────────────┬──────────────────┬────────────────┘
           │                  │                  │
           ▼                  ▼                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                    DATA COLLECTION LAYER                         │
├──────────────────────────────────────────────────────────────────┤
│  L2 Collector (521)  │  SIP Generator  │  Historical Bars        │
│  - NYSE L2 snapshots │  - Polygon data │  - 1m bars from gold    │
│  - 32 features/snap  │  - 1796 symbols │  - Training data        │
│  - 3 concurrent      │  - Score floor  │                         │
└──────────┬──────────────────┬──────────────────┬────────────────┘
           │                  │                  │
           ▼                  ▼                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                    DATA STORAGE LAYER                            │
├──────────────────────────────────────────────────────────────────┤
│  L2 Features          │  SIP Universe        │  Trade Journal     │
│  /data/l2_maximum/    │  /daily_sip/         │  /journal/         │
│  - Parquet files      │  - sip_universe.json │  - events.db       │
│  - Per-symbol dirs    │  - 4 symbols today   │  - Trade records   │
└──────────┬──────────────────┬──────────────────┬────────────────┘
           │                  │                  │
           ▼                  ▼                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                    PROCESSING LAYER                              │
├──────────────────────────────────────────────────────────────────┤
│  L2 Scalping (10,11)  │  Intraday Paper (15) │  Health Monitor    │
│  - L2 signals         │  - Reversal strategy │  - Service checks  │
│  - Order execution    │  - SIP universe      │  - Error detection │
│  - Risk management    │  - Trade logging     │  - NTFY alerts     │
└──────────┬──────────────────┬──────────────────┬────────────────┘
           │                  │                  │
           ▼                  ▼                  ▼
┌──────────────────────────────────────────────────────────────────┐
│                    OUTPUT LAYER                                  │
├──────────────────────────────────────────────────────────────────┤
│  IBKR Orders         │  Trade Notifications │  System Logs        │
│  - Entry/exit        │  - jacobw-trading-*  │  - journalctl       │
│  - Position updates  │  - Entry/exit alerts │  - Service logs     │
│  - P&L tracking      │  - P&L notifications │  - Audit trails     │
└──────────────────────────────────────────────────────────────────┘
```

---

## 3. COMPONENT DEPENDENCY MAP

### 3.1 Trading Orchestrator Dependencies
```
bulletproof_orchestrator.py
├── multi_session_sip_generator.py
│   ├── Polygon API (async)
│   ├── Gold data directory
│   └── SIP scoring logic
├── IBKR Gateway (health check)
├── Systemd services (status)
└── NTFY notifications
```

### 3.2 L2 Collector Dependencies
```
l2-collect (qx-l2)
├── IBKR Gateway (client 521)
│   ├── L2 order book subscription
│   └── Market data streaming
├── SIP universe (daily_sip/sip_universe.json)
├── Feature engineering (32 features)
├── Parquet storage
└── L2 watchdog monitoring
```

### 3.3 L2 Scalping Dependencies
```
l2_scalping/src/main.py
├── IBKR Gateway (clients 10, 11)
│   ├── L2 feed (client 10)
│   ├── Order execution (client 11)
│   └── Position tracking
├── SIP universe (daily_sip/sip_universe.json)
├── L2 signals (microstructure analysis)
├── Risk management
├── Order manager (async reconnect)
└── Trade journal (event_store)
```

### 3.4 Intraday Paper Trading Dependencies
```
paper_trade.py
├── IBKR Gateway (client 15)
│   ├── Market data streaming
│   ├── Order execution
│   └── Position tracking
├── SIP universe (daily_sip/sip_universe.json)
├── Polygon API (historical bars)
├── Signal generation (reversal strategy)
├── Trade journal (event_store)
├── NTFY notifications
│   ├── Trade entries
│   ├── Trade exits
│   └── P&L alerts
└── Event store (SQLite)
```

### 3.5 Health Monitor Dependencies
```
system_health_monitor.py
├── Systemd services (is-active)
│   ├── l2-collector
│   ├── l2-scalping
│   └── l2-watchdog
├── Journalctl logs (CRITICAL errors)
├── IBKR Gateway (connectivity)
└── NTFY alerts
```

---

## 4. FILE INVENTORY BY COMPONENT

### 4.1 Quantstack (Core Trading System)
**Location**: `/home/jacobw/quantstack/`

**Systemd Services**:
- `bulletproof_orchestrator.py` - SIP generation orchestrator
- `trading_orchestrator.py` - Legacy orchestrator
- `system_health_monitor.py` - Health monitoring
- `scripts/preflight_check.py` - Pre-market validation
- `scripts/l2_watchdog.py` - L2 collector watchdog
- `scripts/trading_report.py` - Trade performance reports

**L2 Scalping System**:
- `l2_scalping/src/main.py` - Main entry point
- `l2_scalping/src/execution/order_manager.py` - Order execution
- `l2_scalping/src/data/l2_feed.py` - L2 data feed
- `l2_scalping/src/signals/l2_signals.py` - Signal generation
- `l2_scalping/config/strategy.yaml` - Strategy config
- `l2_scalping/config/risk.yaml` - Risk config

**L2 Collection (qx-l2)**:
- `qx-l2/configs/maximum_l2.yaml` - L2 config
- `qx-l2/src/` - L2 collection logic

**Data Storage**:
- `data/daily_sip/` - Daily SIP universes
- `data/l2_maximum/features/` - L2 features (parquet)
- `logs/` - Service logs

---

### 4.2 Intraday Stack (Paper Trading)
**Location**: `/home/jacobw/intraday_stack/`

**Systemd Services**:
- `scripts/paper_trade.py` - Main trading loop
- `scripts/refresh_sip.py` - SIP refresh
- `scripts/start_paper_trading.sh` - Service startup

**Core Modules**:
- `src/journal/event_store.py` - Trade logging (SQLite)
- `src/notifications/ntfy_notifier.py` - NTFY notifications
- `src/universe/polygon_sip_universe.py` - SIP loading
- `src/signals/candidate_generator.py` - Signal generation
- `src/execution/ibkr_live_adapter.py` - IBKR adapter

**Data Storage**:
- `data/journal/events.db` - Trade journal (SQLite)
- `data/daily_sip/` - SIP universes (shared)
- `logs/paper_*.log` - Trading logs

---

### 4.3 External Data Sources
**IBKR Gateway**:
- Host: `127.0.0.1:7497`
- Client IDs: 10, 11 (l2-scalping), 15 (intraday-paper), 521 (l2-collector), 998 (preflight)
- Data: L2 order books, market data, order execution

**Polygon API**:
- Endpoint: `https://api.polygon.io`
- Data: Daily OHLCV, SIP scoring
- Key: `ZBxeJYOn0_e0UcPgEYLA90CQ9S28_EfU`

**Gold Data (GCS Mount)**:
- Path: `/home/jacobw/gcs-mount/gold/stocks/1m/`
- Data: 1796 symbols, 1-minute bars, historical training data

---

## 5. CONFIGURATION FILES

### 5.1 Systemd Services
```
/etc/systemd/system/
├── trading-orchestrator.service
├── trading-orchestrator.timer
├── preflight-check.service
├── preflight-check.timer
├── l2-collector.service
├── l2-collector.timer
├── l2-scalping.service
├── l2-watchdog.service
├── intraday-paper.service
├── intraday-paper.timer
├── intraday-sip.service
├── intraday-sip.timer
├── system-health-monitor.service
├── system-health-monitor.timer
└── polygon.env (API key)
```

### 5.2 Application Configs
```
/home/jacobw/quantstack/
├── l2_scalping/config/strategy.yaml
├── l2_scalping/config/risk.yaml
└── qx-l2/configs/maximum_l2.yaml

/home/jacobw/intraday_stack/
└── (configs embedded in Python)
```

---

## 6. NOTIFICATION CHANNELS (NTFY)

| Channel | Purpose | Trigger |
|---------|---------|---------|
| `jacobw-trading-status` | System status updates | Orchestrator, health monitor |
| `jacobw-trading-alerts` | Errors and failures | Health monitor, services |
| `jacobw-trading-trades` | Trade executions | Intraday-paper, l2-scalping |

---

## 7. DATABASE SCHEMA

### 7.1 Trade Journal (SQLite)
**Location**: `/home/jacobw/intraday_stack/data/journal/events.db`

**Tables**:
- `trades` - Trade records (entry/exit, P&L, system tracking)
- `orders` - Order submissions
- `fills` - Order fills
- `decisions` - Trading decisions
- `risk_events` - Risk violations

---

## 8. TIMER SCHEDULE (Manila Time)

| Time | Service | Purpose |
|------|---------|---------|
| 20:00 | preflight-check | Pre-market validation |
| 21:00 | trading-orchestrator | SIP generation |
| 21:45 | intraday-sip | SIP refresh |
| 22:25 | l2-collector, intraday-paper | Start trading |
| 22:30 | Market open | Trading begins |
| Every 5min | system-health-monitor | Health checks |

---

## 9. CRITICAL PATHS

### 9.1 SIP Generation Path
```
trading-orchestrator.timer (21:00)
  ↓
bulletproof_orchestrator.py
  ↓
multi_session_sip_generator.py
  ↓
Polygon API (1796 symbols)
  ↓
/home/jacobw/intraday_stack/data/daily_sip/date=YYYY-MM-DD/sip_universe.json
  ↓
l2-collector, l2-scalping, intraday-paper (load at startup)
```

### 9.2 Trade Execution Path
```
intraday-paper.py (trading loop)
  ↓
candidate_generator.py (signals)
  ↓
IBKR Gateway (client 15)
  ↓
Order execution
  ↓
event_store.py (log trade)
  ↓
ntfy_notifier.py (send alert)
  ↓
jacobw-trading-trades (NTFY)
```

### 9.3 Health Monitoring Path
```
system-health-monitor.timer (every 5min)
  ↓
system_health_monitor.py
  ↓
Check: l2-collector, l2-scalping, l2-watchdog
  ↓
Scan: journalctl for CRITICAL errors
  ↓
Check: IBKR Gateway connectivity
  ↓
ntfy_notifier.py (if issues)
  ↓
jacobw-trading-alerts (NTFY)
```

---

## 10. RESILIENCE & RECOVERY

### 10.1 Auto-Recovery Mechanisms
- **L2 Watchdog**: Monitors l2-collector, auto-restarts on failure
- **Async Reconnect**: l2-scalping reconnects on IBKR disconnect
- **Health Monitor**: Detects CRITICAL errors, sends alerts
- **Systemd Restart**: Services configured with `Restart=always`

### 10.2 Manual Intervention Points
- Gateway API settings (TWS AND Gateway both need config)
- Stale client connections (restart Gateway to clear)
- Preflight failures (check IBKR connectivity)

---

## 11. MONITORING & DEBUGGING

### 11.1 Log Locations
```
/home/jacobw/quantstack/logs/
├── orchestrator.log
├── orchestrator_audit.log
└── (service logs via journalctl)

/home/jacobw/intraday_stack/logs/
├── paper_YYYYMMDD.log
├── sip.log
└── (service logs via journalctl)
```

### 11.2 Useful Commands
```bash
# Check all services
systemctl status l2-collector l2-scalping intraday-paper

# View real-time logs
journalctl -u l2-scalping -f

# Check SIP universe
cat /home/jacobw/intraday_stack/data/daily_sip/date=$(date +%F)/sip_universe.json | jq

# Generate trade report
python scripts/trading_report.py --date $(date +%F)

# Check IBKR clients
# (View in Gateway GUI)
```

---

## 12. DEPENDENCIES SUMMARY

### 12.1 Python Packages
- `ib_insync` - IBKR API
- `pandas` - Data processing
- `numpy` - Numerical computing
- `requests` - HTTP client
- `pytz` - Timezone handling
- `sqlalchemy` - ORM
- `pydantic` - Data validation

### 12.2 External Services
- IBKR Gateway (7497)
- Polygon API
- NTFY (https://ntfy.sh)
- GCS Mount (gold data)

### 12.3 System Dependencies
- Python 3.11+
- Systemd
- SQLite3
- Bash

---

## 13. TOTAL SYSTEM STATISTICS

| Metric | Value |
|--------|-------|
| Systemd Services | 8 |
| Python Files | 1,486 |
| Configuration Files | 15+ |
| Database Tables | 5 |
| NTFY Channels | 3 |
| IBKR Client IDs | 5 |
| SIP Symbols Tested | 1,796 |
| SIP Symbols Qualified | ~4-20 |
| L2 Features Per Snapshot | 32 |
| Max Concurrent L2 Symbols | 3 |
| Trade Journal Records | 21+ |

