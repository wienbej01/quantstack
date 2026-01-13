# Complete System Guide

**Quantstack Trading System - Production Operations Manual**
**Version**: 3.1 (IBKR Platform Migration Complete)
**Date**: 2026-01-13
**Status**: ✅ **PRODUCTION** - Platform-Based Architecture

## Latest: IBKR API Platform Migration Complete (2026-01-13)

**🚨 MAJOR UPGRADE: Completed migration from socket-based ib_insync (port 7497) to centralized IBKR API Platform (ports 5000/8000)**
**✅ NEW ARCHITECTURE: All services now connect through REST-based platform, eliminating connection issues**

### Migration Status: COMPLETE

**Problem with Previous Approach:**
- Socket-based ib_insync connections prone to stale connections and timeouts
- Individual connection management in each service with complex client ID coordination
- Service failures due to Gateway connection issues and zombie connections

**New Platform Architecture:**
- **Centralized Platform**: Single IBKR API Platform service (port 8000) 
- **REST-based Interface**: No socket connections, eliminates stale connection issues
- **Client Portal Gateway**: Browser-based authentication (port 5000)
- **Service Registry**: Automatic service registration and health monitoring
- **Unified Authentication**: Single point for IBKR Gateway authentication
- **Built-in Recovery**: Automatic reconnection and error handling

### Current Working Setup

**1. Start Client Portal Gateway**:
```bash
cd /home/jacobw/quantstack/cpapi/gateway
nohup bin/run.sh root/conf.yaml > gateway_startup.log 2>&1 &
```

**2. Browser Authentication**:
- Open: https://localhost:5000
- Login with IBKR credentials + 2FA
- Session valid ~24 hours

**3. Verify Platform Health**:
```bash
curl -s http://127.0.0.1:8000/health | jq .
# Should show: "authenticated": true
```

**4. All Services Now Use Platform**:
- l2-collector: Port 8000 (was 7497)
- l2-scalping: Port 8000 (was 7497) 
- intraday-paper: Port 8000 (was 7497)

## System Overview

The Quantstack trading system is a fully automated, platform-based trading infrastructure running on Manila VPS (UTC+8) with NY market hours operation (America/New_York timezone at service level).

**Architecture**: Centralized IBKR API Platform with REST-based connections to all trading services, replacing legacy socket-based ib_insync connections.

## System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        MANILA VPS (UTC+8)                                   │
│                   Trading Hours: America/New_York                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┴───────────────┐
                    │                               │
            ┌───────▼────────┐            ┌────────▼────────┐
            │  NordVPN       │            │  Client Portal  │
            │  (VPN Service) │◄───────────►│  Gateway        │
            └────────────────┘            │  (Port 5000)    │
                    │                     │  Browser Auth   │
                    └───────────────┬─────┴─────────────────┘
                                    │
                    ┌───────────────▼────────────────┐
                    │   IBKR API Platform (Port 8000) │
                    │   ibkr-platform.service         │
                    │   /home/jacobw/quantstack/      │
                    │   cpapi/platform.py             │
                    └───────────────┬────────────────┘
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
┌───────▼────────┐        ┌────────▼─────────┐      ┌─────────▼────────┐
│  L2 Collector  │        │  L2 Scalping     │      │ Intraday Paper   │
│  l2-collector  │        │  l2-scalping     │      │ intraday-paper   │
│  .service      │        │  .service        │      │  .service        │
├────────────────┤        ├──────────────────┤      ├──────────────────┤
│ qx-l2/src/     │        │ l2_scalping/src/ │      │ intraday_stack/  │
│ collector.py   │        │ main.py          │      │ scripts/         │
│ features.py    │        │ l2_feed.py       │      │ paper_trade_     │
│ storage.py     │        │ order_manager.py │      │   platform.py    │
└────────┬───────┘        └────────┬─────────┘      └────────┬─────────┘
         │                         │                          │
         │         ┌───────────────┴──────────────┐           │
         │         │                              │           │
         │    ┌────▼──────┐              ┌────────▼────────┐  │
         │    │ SIP Data  │              │  SIP Generation │  │
         │    │ Loading   │              │  (Daily 09:10)  │  │
         │    └────┬──────┘              └────────┬────────┘  │
         │         │                              │           │
         └─────────┴──────────────────────────────┴───────────┘
                                    │
                    ┌───────────────▼────────────────┐
                    │   Monitoring & Alerting        │
                    ├─────────────────────────────────┤
                    │ • system_health_monitor.py     │
                    │ • bulletproof_orchestrator.py  │
                    │ • scripts/l2_watchdog.py       │
                    │ • trading_notifications.py     │
                    └───────────────┬────────────────┘
                                    │
                    ┌───────────────▼────────────────┐
                    │   NTFY Notification Channels   │
                    ├─────────────────────────────────┤
                    │ • jacobw-trading-alerts        │
                    │ • jacobw-trading-status        │
                    │ • jacobw-trading-trades        │
                    └─────────────────────────────────┘
```

## System Components Summary

| Component | Service | Location | Purpose |
|-----------|---------|----------|---------|
| **IBKR Platform** | `ibkr-platform.service` | `/home/jacobw/quantstack/cpapi/` | Centralized IBKR API (Port 8000) |
| **L2 Collector** | `l2-collector.service` | `/home/jacobw/quantstack/qx-l2/` | L2 market data collection |
| **L2 Scalping** | `l2-scalping.service` | `/home/jacobw/quantstack/l2_scalping/` | High-frequency scalping |
| **Intraday Paper** | `intraday-paper.service` | `/home/jacobw/intraday_stack/` | ML-based paper trading |
| **SIP Generator** | `intraday-sip.service` | `/home/jacobw/intraday_stack/scripts/` | Daily universe selection |
| **Health Monitor** | `system-health-monitor.service` | `/home/jacobw/quantstack/` | Platform health monitoring |
| **L2 Watchdog** | `l2-watchdog.service` | `/home/jacobw/quantstack/scripts/` | L2 collector watchdog |
| **Orchestrator** | `trading-orchestrator.service` | `/home/jacobw/quantstack/` | System orchestration |
| **Preflight** | `preflight-check.service` | `/home/jacobw/quantstack/scripts/` | Pre-market validation |

## Repository Structure

```
/home/jacobw/quantstack/          # Main trading system
├── cpapi/                         # IBKR API Platform
│   ├── platform.py                # FastAPI server
│   ├── platform_client.py         # HTTP client
│   ├── trading_notifications.py   # NTFY notifications
│   └── gateway/                   # Client Portal Gateway
├── qx-l2/                         # L2 Data Collector
│   ├── src/qx_l2/
│   │   ├── collector.py
│   │   ├── features.py
│   │   └── storage.py
│   └── configs/maximum_l2.yaml
├── l2_scalping/                   # L2 Scalping System
│   ├── src/
│   │   ├── main.py
│   │   ├── data/l2_feed.py
│   │   ├── execution/order_manager.py
│   │   └── signals/
│   └── config/
├── systemd/                       # Local systemd units
├── scripts/                       # Core scripts
├── logs/                          # Application logs
└── data/                          # Data storage

/home/jacobw/intraday_stack/       # ML Paper Trading
├── scripts/
│   ├── paper_trade_platform.py
│   ├── generate_daily_sip_universe.py
│   └── ibkr_preflight.py
├── src/
│   ├── signals/candidate_generator.py
│   ├── execution/
│   └── universe/
└── data/
    ├── journal/events.db
    └── daily_sip/
```

---

## 1. INFRASTRUCTURE LAYER

### 1.1 VPN Connection (NordVPN)
**Service**: `nordvpnd.service`
**Purpose**: Secure connection to IBKR from Manila VPS
**Status**: `active (running)`

**Systemd Unit**:
```bash
/usr/lib/systemd/system/nordvpnd.service
```

**Dependencies**:
- `ibkr-gateway.service` depends on `nordvpnd.service`
- Required before IBKR Gateway startup

**Verification**:
```bash
# Check VPN status
systemctl status nordvpnd.service

# Verify IP (should show Manila)
curl ifconfig.me

# Check connection
nordvpn status
```

**Process Flow**:
```
nordvpnd.service (system-managed)
  ↓
Manila VPS IP established
  ↓
IBKR Gateway can connect via VPN
```

---

### 1.2 IBKR Gateway Management

#### A. Client Portal Gateway
**Service**: `ibkr-gateway.service` (currently inactive, replaced by platform)
**Location**: `/home/jacobw/quantstack/cpapi/gateway/`
**Port**: 5000 (HTTPS)
**Backend**: IBKR Client Portal Gateway

**Startup Script**: `/home/jacobw/quantstack/scripts/start_ibkr_gateway.sh`
**Wait Script**: `/home/jacobw/quantstack/scripts/wait_for_ibkr_gateway.sh`

**Key Files**:
- `gateway/bin/run.sh` - Gateway startup script
- `gateway/root/conf.yaml` - Gateway configuration
- `gateway.log` - Gateway runtime logs

**Dependencies**:
- `nordvpnd.service` (VPN required)
- `xvfb.service` (Virtual display for GUI)

**Authentication**: Browser-based login required
```bash
# Start Gateway
cd /home/jacobw/quantstack/cpapi/gateway
bin/run.sh root/conf.yaml

# Browser login
firefox https://localhost:5000
# Login with IBKR credentials + 2FA
```

#### B. Gateway Manager
**Service**: `gateway-manager.service`
**Script**: `/home/jacobw/quantstack/scripts/gateway_manager.py`
**Purpose**: Automated gateway health monitoring and recovery

**Alert Script**: `/home/jacobw/quantstack/scripts/gateway_failure_alert.sh`

---

### 1.3 IBKR API Platform (Core Infrastructure)
**Service**: `ibkr-platform.service`
**Status**: ✅ **ACTIVE** (Port 8000)
**Backend**: Client Portal Gateway (port 5000)

**Entry Point**:
```python
# Location: /home/jacobw/quantstack/cpapi/platform.py
# Service runs as: python3 -m cpapi.platform
```

**Key Files**:
| File | Purpose |
|------|---------|
| `cpapi/platform.py` | FastAPI server (main platform) |
| `cpapi/platform_client.py` | HTTP client for services |
| `cpapi/client.py` | CPAPI client wrapper |
| `cpapi/trading_notifications.py` | NTFY notifications |
| `cpapi/check_gateway.py` | Gateway health checks |
| `cpapi/PLATFORM_ARCHITECTURE.md` | Architecture documentation |

**API Endpoints**:
```bash
# Health check
curl http://127.0.0.1:8000/health

# Service registration
POST /services/register
POST /services/{id}/heartbeat

# IBKR Operations
GET  /api/accounts
GET  /api/market-data/snapshot
GET  /api/market-data/historical
POST /api/orders/place
GET  /api/positions/{account}
GET  /api/portfolio/{account}
```

**Service Management**:
```bash
# Check status
systemctl status ibkr-platform.service

# View logs
journalctl -u ibkr-platform.service -f

# Health check
curl -s http://127.0.0.1:8000/health | jq .

# Restart (all services auto-register)
systemctl restart ibkr-platform.service
```

**Registered Services** (via `/health` endpoint):
- `l2_collector` - L2 Data Collector
- `l2_scalping` - L2 Scalping System
- `intraday_paper` - Intraday Paper Trading

---

## 2. DATA COLLECTION LAYER

### 2.1 L2 Data Collector
**Service**: `l2-collector.service`
**Status**: ✅ **ACTIVE**
**Binary**: `/home/jacobw/.local/bin/l2-collect`

**Entry Point**:
```bash
l2-collect --config qx-l2/configs/maximum_l2.yaml --daemon
```

**Key Files**:
| File | Purpose |
|------|---------|
| `qx-l2/src/qx_l2/cli.py` | CLI entry point |
| `qx-l2/src/qx_l2/collector.py` | Main collection logic |
| `qx-l2/src/qx_l2/features.py` | Feature engineering (32 features) |
| `qx-l2/src/qx_l2/symbols.py` | Symbol management |
| `qx-l2/src/qx_l2/storage.py` | Parquet storage |
| `qx-l2/src/qx_l2/journal.py` | Collection journal |
| `qx-l2/src/qx_l2/scheduler.py` | Market hours scheduler |
| `qx-l2/configs/maximum_l2.yaml` | Configuration |

**Data Storage**:
```
/home/jacobw/quantstack/data/l2_maximum/features/
└── date=YYYY-MM-DD/
    └── symbol={TICKER}/
        └── {TIMESTAMP}.parquet
```

**Process Flow**:
```
l2-collector.service (systemd)
  ↓
qx_l2.cli (main)
  ↓
IBKRPlatformClient (register "l2_collector")
  ↓
Subscribe to L2 market data (client 521)
  ↓
Feature engineering (32 features/snapshot)
  ↓
Parquet storage (data/l2_maximum/)
```

**Configuration** (`maximum_l2.yaml`):
```yaml
# Symbols loaded from daily SIP
symbols: []  # Auto-loaded from sip_universe.json

# Market data via platform
platform:
  base_url: http://127.0.0.1:8000
  service_id: l2_collector
  service_name: "L2 Data Collector"

# Feature engineering
features:
  - order_book_imbalance
  - bid_ask_spread
  - depth_features
  # ... 32 total features
```

---

## 3. TRADING EXECUTION LAYER

### 3.1 L2 Scalping System
**Service**: `l2-scalping.service`
**Status**: ⚠️ **AUTO-RESTART** (connection issues)
**Location**: `/home/jacobw/quantstack/l2_scalping/`

**Entry Point**: `start_scalping.sh` → `src/main.py`

**Key Files**:
| File | Purpose |
|------|---------|
| `src/main.py` | Main trading loop |
| `src/data/l2_feed.py` | L2 data feed via platform |
| `src/execution/order_manager.py` | Order execution (IBKRPlatformClient) |
| `src/signals/l2_signals.py` | Signal generation (OBI momentum) |
| `src/signals/context_filter.py` | Context-aware filtering |
| `src/signals/pattern_rules.py` | Pattern-based rules |
| `src/risk/risk_manager.py` | Risk management |
| `config/strategy.yaml` | Strategy configuration |
| `config/risk.yaml` | Risk configuration |
| `config/ibkr.yaml` | IBKR connection settings |

**Process Flow**:
```
l2-scalping.service (systemd)
  ↓
start_scalping.sh → src/main.py
  ↓
Load config (strategy, risk, ibkr)
  ↓
IBKRPlatformClient (register "l2_scalping")
  ↓
Load SIP symbols (data.sip_integration)
  ↓
L2DataFeed (market data subscription)
  ↓
L2SignalGenerator (OBI + pattern rules)
  ↓
ContextFilter (regime filtering)
  ↓
RiskManager (position sizing, stops)
  ↓
IBKROrderManager (order execution)
  ↓
TradeJournal (logging)
  ↓
NTFY notifications (trading_notifications.py)
```

**Strategy Configuration** (`strategy.yaml`):
```yaml
strategy:
  name: "L2_OBI_Momentum_Scalper"
  version: "2.0"

  # OBI thresholds
  obi_entry_threshold: 0.8
  obi_extreme_threshold: 0.9
  min_confidence: 0.3

  # Timing
  default_hold_seconds: 300  # 5 minutes
  max_hold_seconds: 600

# Pattern rules (3 parallel rules)
pattern_rules:
  rule1_enabled: true  # OBI momentum + depth
  rule2_enabled: true  # Bid depth + OBI change
  rule3_enabled: true  # High OBI + depth

# Context gates
context_gates:
  hard:
    block_vol_expansion: true
    block_bb_squeeze: true
```

---

### 3.2 Intraday Paper Trading
**Service**: `intraday-paper.service`
**Status**: ❌ **FAILED** (preflight check failing)
**Location**: `/home/jacobw/intraday_stack/`

**Entry Point**: `scripts/start_paper_trading.sh` → `scripts/paper_trade_platform.py`

**Key Files**:
| File | Purpose |
|------|---------|
| `scripts/paper_trade_platform.py` | Main trading loop (platform-based) |
| `scripts/generate_daily_sip.sh` | SIP generation wrapper |
| `scripts/generate_daily_sip_universe.py` | SIP generation logic |
| `scripts/refresh_sip.py` | Mid-day SIP refresh |
| `scripts/ibkr_preflight.py` | Pre-flight validation |
| `src/journal/event_store.py` | Trade journal (SQLite) |
| `src/notifications/ntfy_notifier.py` | NTFY notifications |
| `src/universe/polygon_sip_universe.py` | SIP universe loading |
| `src/signals/candidate_generator.py` | Signal generation |

**Process Flow**:
```
intraday-paper.service (systemd)
  ↓
start_paper_trading.sh
  ↓
Preflight check (ibkr_preflight.py)
  ↓
paper_trade_platform.py (main loop)
  ↓
Load SIP universe (polygon_sip_universe.py)
  ↓
CandidateGenerator (signals)
  ↓
IBKRPlatformClient (paper account)
  ↓
Order execution (paper trading)
  ↓
EventStore (SQLite logging)
  ↓
NTFY notifications
```

**Data Storage**:
```
/home/jacobw/intraday_stack/data/
├── journal/
│   └── events.db  # SQLite trade journal
└── daily_sip/
    └── date=YYYY-MM-DD/
        └── sip_universe.json
```

---

## 4. SCHEDULING & AUTOMATION

### 4.1 Timer Schedule (Manila/ET)

| Manila Time | ET Time | Timer | Service | Purpose |
|-------------|---------|-------|---------|---------|
| 20:00 | 07:00 AM | `preflight-check.timer` | preflight-check | Pre-market validation |
| 21:00 | 08:00 AM | `trading-orchestrator.timer` | trading-orchestrator | System monitoring |
| 22:10 | 09:10 AM | `intraday-sip.timer` | intraday-sip | Daily SIP generation |
| Every 5min | Every 5min | `system-health-monitor.timer` | system-health-monitor | Health checks |

**Timer Configuration**:

**A. Pre-flight Check** (`preflight-check.timer`):
```ini
[Timer]
OnCalendar=Mon..Fri 07:00:00 America/New_York
Persistent=true
```
**Script**: `/home/jacobw/quantstack/scripts/preflight_check.py`

**B. Trading Orchestrator** (`trading-orchestrator.timer`):
```ini
[Timer]
OnCalendar=Mon..Fri 08:00:00 America/New_York
Persistent=true
```
**Script**: `/home/jacobw/quantstack/bulletproof_orchestrator.py`

**C. Daily SIP** (`intraday-sip.timer`):
```ini
[Timer]
OnCalendar=Mon-Fri 09:10:00 America/New_York
Persistent=true
```
**Script**: `/home/jacobw/intraday_stack/scripts/generate_daily_sip.sh`

**D. Health Monitor** (`system-health-monitor.timer`):
```ini
[Timer]
OnCalendar=*:0/5  # Every 5 minutes
Persistent=false
```
**Script**: `/home/jacobw/quantstack/system_health_monitor.py`

---

## 5. MONITORING & ALERTING

### 5.1 Health Monitor
**Service**: `system-health-monitor.service`
**Script**: `/home/jacobw/quantstack/system_health_monitor.py`

**Monitors**:
- IBKR Platform health and authentication
- Critical services: `ibkr-platform`, `l2-collector`, `l2-scalping`
- Journalctl CRITICAL error scanning
- Service recovery detection

**State File**: `/tmp/platform_health_state.json`

**Monitoring Window**: 07:00 - 16:30 ET (weekdays only)

### 5.2 L2 Watchdog
**Service**: `l2-watchdog.service`
**Script**: `/home/jacobw/quantstack/scripts/l2_watchdog.py`

**Monitors**:
- L2 collector service health
- Gateway crash detection (pattern matching)
- Data flow freshness (file timestamps)
- Auto-restart on failure

**Error Patterns**:
```python
fatal_patterns = [
    r"Connection refused",
    r"Connection reset",
    r"Disconnected unexpectedly",
    r"Error 504",  # Gateway timeout
    r"Error 1100",  # Connectivity lost
]
```

### 5.3 NTFY Notifications

**Channels**:
| Channel | Purpose |
|---------|---------|
| `jacobw-trading-alerts` | Errors, failures, recovery |
| `jacobw-trading-status` | System status, health |
| `jacobw-trading-trades` | Trade entries, exits, P&L |

**Module**: `/home/jacobw/quantstack/cpapi/trading_notifications.py`

**Functions**:
```python
send_trade_notification(action, symbol, strategy, direction, price, quantity, pnl, exit_reason)
send_position_update(symbol, unrealized_pnl, strategy)
send_daily_summary(total_pnl, trades_count, win_rate)
send_system_status(message, priority)
```

**Usage Examples**:
```bash
# Test alert
curl -d "Test message" ntfy.sh/jacobw-trading-alerts

# Subscribe on phone
# https://ntfy.sh/jacobw-trading-alerts
```

---

## 6. SYSTEM FILE INVENTORY

### 6.1 Systemd Service Units

**Location**: `/etc/systemd/system/`

**Services**:
```
ibkr-platform.service         # IBKR API Platform (port 8000)
ibkr-gateway.service          # IBKR Gateway (port 5000, inactive)
gateway-manager.service       # Gateway health monitor
l2-collector.service          # L2 data collection
l2-scalping.service           # L2 scalping trading
l2-watchdog.service           # L2 collector watchdog
intraday-paper.service        # Intraday paper trading
intraday-sip.service          # Daily SIP generation
preflight-check.service       # Pre-market validation
trading-orchestrator.service  # System orchestrator
system-health-monitor.service # Health monitoring
nordvpnd.service             # VPN (system-managed)
xvfb.service                 # Virtual display
```

**Local Service Files** (managed by user):
```
/home/jacobw/quantstack/systemd/l2-collector.service
/home/jacobw/quantstack/systemd/l2-watchdog.service
/home/jacobw/quantstack/systemd/ml-paper-trading.service
/home/jacobw/quantstack/systemd/emergency-eod-close.service
/home/jacobw/quantstack/systemd/ibkr-gateway-ready.service
/home/jacobw/quantstack/systemd/ibkr-gateway.service
/home/jacobw/quantstack/cpapi/ibkr-platform.service
/home/jacobw/quantstack/l2_scalping/l2-scalping.service
```

**Timers**:
```
system-health-monitor.timer   # Every 5 minutes
preflight-check.timer         # 07:00 ET
trading-orchestrator.timer    # 08:00 ET
intraday-sip.timer            # 09:10 ET
```

**Local Timer Files**:
```
/home/jacobw/quantstack/systemd/l2-collector.timer
/home/jacobw/quantstack/systemd/ml-paper-trading.timer
/home/jacobw/quantstack/systemd/emergency-eod-close.timer
```

**Drop-in Configurations**:
```
l2-collector.service.d/
  └── alerts.conf             # Failure alerts
l2-scalping.service.d/
  └── alerts.conf             # Failure alerts
intraday-paper.service.d/
  ├── alerts.conf             # Failure alerts
  └── override.conf           # Service overrides
```

### 6.2 Configuration Files

**Platform**:
```
/home/jacobw/quantstack/cpapi/
├── platform.py               # FastAPI server
├── platform_client.py        # HTTP client
├── client.py                 # CPAPI wrapper
├── trading_notifications.py  # NTFY module
├── check_gateway.py          # Health checks
└── gateway/                  # Client Portal Gateway
    ├── bin/run.sh
    ├── root/conf.yaml
    └── logs/
```

**L2 Collector**:
```
/home/jacobw/quantstack/qx-l2/
├── configs/maximum_l2.yaml
├── src/qx_l2/
│   ├── cli.py
│   ├── collector.py
│   ├── features.py
│   ├── symbols.py
│   ├── storage.py
│   └── journal.py
└── scripts/
```

**L2 Scalping**:
```
/home/jacobw/quantstack/l2_scalping/
├── src/main.py               # Entry point
├── src/data/
│   ├── l2_feed.py
│   └── sip_integration.py
├── src/execution/
│   └── order_manager.py
├── src/signals/
│   ├── l2_signals.py
│   ├── context_filter.py
│   └── pattern_rules.py
├── src/risk/risk_manager.py
├── config/
│   ├── strategy.yaml
│   ├── risk.yaml
│   └── ibkr.yaml
└── start_scalping.sh
```

**Intraday Paper**:
```
/home/jacobw/intraday_stack/
├── scripts/
│   ├── paper_trade_platform.py
│   ├── start_paper_trading.sh
│   ├── generate_daily_sip.sh
│   ├── generate_daily_sip_universe.py
│   ├── refresh_sip.py
│   └── ibkr_preflight.py
├── src/journal/event_store.py
├── src/notifications/ntfy_notifier.py
└── src/signals/candidate_generator.py
```

### 6.3 Core Scripts and Entry Points

**Orchestration & Monitoring**:
```
/home/jacobw/quantstack/bulletproof_orchestrator.py        # Main system orchestrator
/home/jacobw/quantstack/trading_orchestrator.py            # Legacy orchestrator
/home/jacobw/quantstack/system_health_monitor.py           # Platform health monitor
/home/jacobw/quantstack/multi_session_sip_generator.py     # Multi-session SIP generator
```

**SIP Generation**:
```
/home/jacobw/intraday_stack/scripts/generate_daily_sip.sh
/home/jacobw/intraday_stack/scripts/generate_daily_sip_universe.py
/home/jacobw/intraday_stack/scripts/refresh_sip.py
```

**Gateway & Platform**:
```
/home/jacobw/quantstack/scripts/start_ibkr_gateway.sh
/home/jacobw/quantstack/scripts/wait_for_ibkr_gateway.sh
/home/jacobw/quantstack/scripts/gateway_manager.py
/home/jacobw/quantstack/scripts/gateway_failure_alert.sh
/home/jacobw/quantstack/cpapi/check_gateway.py
```

**L2 System Scripts**:
```
/home/jacobw/quantstack/scripts/l2_watchdog.py              # L2 collector watchdog
/home/jacobw/quantstack/scripts/install_l2_systemd.sh      # L2 systemd installer
/home/jacobw/quantstack/scripts/monitor_l2_live.sh         # L2 live monitor
/home/jacobw/quantstack/l2_scalping/start_scalping.sh      # L2 scalping startup
```

**Trading Scripts**:
```
/home/jacobw/quantstack/start_live_system.sh                # Start all trading services
/home/jacobw/quantstack/scripts/start_trading_services.sh   # Start trading services
/home/jacobw/quantstack/scripts/service_failure_alert.sh    # Service failure notifications
/home/jacobw/intraday_stack/scripts/start_paper_trading.sh  # Paper trading startup
/home/jacobw/intraday_stack/scripts/paper_trade_platform.py # Paper trading main
```

**Preflight & Validation**:
```
/home/jacobw/quantstack/scripts/preflight_check.py         # Pre-market validation
/home/jacobw/intraday_stack/scripts/ibkr_preflight.py      # IBKR preflight checks
```

**Training & Backtesting** (development/research):
```
/home/jacobw/quantstack/scripts/run_full_training_pipeline.sh
/home/jacobw/quantstack/scripts/run_rolling_pipeline.sh
/home/jacobw/quantstack/scripts/run_stage1_training.sh
/home/jacobw/quantstack/scripts/run_stage2_training.sh
```

### 6.4 Data Storage Locations

**L2 Data**:
```
/home/jacobw/quantstack/data/l2_maximum/features/
└── date=YYYY-MM-DD/
    └── symbol={TICKER}/
        └── {TIMESTAMP}.parquet
```

**SIP Universe** (Intraday Stack):
```
/home/jacobw/intraday_stack/data/daily_sip/
└── date=YYYY-MM-DD/
    └── sip_universe.json
```

**Trade Journal**:
```
/home/jacobw/intraday_stack/data/journal/events.db  # SQLite
```

**Platform Health State**:
```
/tmp/platform_health_state.json  # Recovery tracking
```

**Gateway Configuration**:
```
/home/jacobw/quantstack/cpapi/gateway/root/conf.yaml
```

**Logs**:
```
# Application logs
/home/jacobw/quantstack/logs/
├── orchestrator.log                # Main orchestrator logs
└── orchestrator_audit.log          # Orchestrator audit trail

/home/jacobw/quantstack/l2_scalping/logs/
└── scalping_system.log             # L2 scalping system logs

/home/jacobw/intraday_stack/logs/
└── paper_YYYYMMDD.log              # Paper trading daily logs

# Watchdog logs
/home/jacobw/quantstack/logs/l2_watchdog.log  # L2 watchdog logs

# Systemd logs (journalctl)
journalctl -u [service-name]
journalctl -u ibkr-platform.service -f
journalctl -u l2-collector.service -f
journalctl -u l2-scalping.service -f
journalctl -u intraday-paper.service -f
```

### 6.5 NTFY Notification System

**Notification Module**:
```
/home/jacobw/quantstack/cpapi/trading_notifications.py
```

**Functions Available**:
```python
send_trade_notification(action, symbol, strategy, direction, price, quantity, pnl, exit_reason)
send_position_update(symbol, unrealized_pnl, strategy)
send_daily_summary(total_pnl, trades_count, win_rate)
send_system_status(message, priority)
```

**NTFY Channels**:
| Channel | Purpose | Usage |
|---------|---------|-------|
| `jacobw-trading-alerts` | Errors, failures, recovery | Critical alerts |
| `jacobw-trading-status` | System status, health | Status updates |
| `jacobw-trading-trades` | Trade entries, exits, P&L | Trade notifications |

**Test Commands**:
```bash
# Test alert channel
curl -d "Test message" ntfy.sh/jacobw-trading-alerts

# Subscribe on phone
# https://ntfy.sh/jacobw-trading-alerts
```

---

## 7. PROCESS FLOWS

### 7.1 Daily Startup Sequence

**Pre-Market (07:00 ET)**:
```
preflight-check.timer (20:00 Manila)
  ↓
scripts/preflight_check.py
  ├→ Check IBKR Gateway connectivity
  ├→ Validate Polygon API
  ├→ Check service status
  └→ Report to NTFY
```

**Orchestrator (08:00 ET)**:
```
trading-orchestrator.timer (21:00 Manila)
  ↓
bulletproof_orchestrator.py
  ├→ multi_session_sip_generator.py
  │   ├→ Polygon API (1796 symbols)
  │   ├→ Gold data validation
  │   └→ Scoring & ranking
  ├→ Gateway health checks
  ├→ Service monitoring
  └→ NTFY status updates
```

**SIP Generation (09:10 ET)**:
```
intraday-sip.timer (22:10 Manila)
  ↓
scripts/generate_daily_sip.sh
  ↓
scripts/generate_daily_sip_universe.py
  ├→ Load 1796 symbols
  ├→ Apply filters (price, volume, score)
  ├→ Output ~4-20 qualified symbols
  └→ Write to data/daily_sip/
```

### 7.2 Trading Execution Flow

**L2 Scalping**:
```
l2-scalping.service (22:25 Manila)
  ↓
Load config (strategy.yaml, risk.yaml)
  ↓
Register with IBKR Platform
  ↓
Load SIP symbols (sip_integration.py)
  ↓
L2DataFeed.subscribe()
  ↓
Main loop (during market hours):
  ├→ Receive L2 snapshot
  ├→ Compute features (32)
  ├→ Generate signals (OBI + patterns)
  ├→ Apply context filters
  ├→ Validate signals
  ├→ Risk checks
  ├→ Place order via platform
  ├→ Log trade (journal)
  └→ Send NTFY notification
```

**Intraday Paper**:
```
intraday-paper.service (22:27 Manila)
  ↓
Preflight validation
  ↓
Load SIP universe
  ↓
Register with IBKR Platform
  ↓
Main loop (during market hours):
  ├→ Scan universe for signals
  ├→ Generate candidates
  ├→ Validate entries
  ├→ Place paper orders
  ├→ Track positions
  ├→ Exit logic (target/stop/time)
  ├→ Log to SQLite
  └→ Send NTFY notifications
```

### 7.3 Monitoring Flow

**Health Monitor (Every 5 min)**:
```
system-health-monitor.timer
  ↓
system_health_monitor.py
  ├→ Check platform health (HTTP)
  ├→ Check authentication status
  ├→ Check critical services (systemctl)
  ├→ Scan journalctl for CRITICAL errors
  ├→ Detect service recovery
  └→ Send NTFY alerts if issues
```

**L2 Watchdog (Continuous)**:
```
l2-watchdog.service
  ↓
scripts/l2_watchdog.py
  ├→ Monitor l2-collector logs
  ├→ Detect fatal patterns
  ├→ Check gateway crash indicators
  ├→ Verify data flow (file timestamps)
  ├→ Auto-restart if needed
  └→ Send recovery notifications
```

---

## 8. TROUBLESHOOTING

### 8.1 Platform Issues

**Problem**: Platform not authenticated
```bash
# Check gateway status
curl -k -s https://localhost:5000/v1/api/iserver/auth/status

# Check platform
curl -s http://127.0.0.1:8000/health | jq .authenticated

# Re-login via browser
firefox https://localhost:5000

# Restart platform
systemctl restart ibkr-platform.service
```

**Problem**: Services can't connect to platform
```bash
# Check platform health
curl -s http://127.0.0.1:8000/health | jq .

# Check registered services
curl -s http://127.0.0.1:8000/health | jq .services

# Restart service (will auto-register)
systemctl restart l2-collector.service
```

### 8.2 Service Failures

**L2 Collector**:
```bash
# Check service
systemctl status l2-collector.service

# View logs
journalctl -u l2-collector.service -n 50

# Check data flow
ls -la /home/jacobw/quantstack/data/l2_maximum/features/date=$(date +%F)/

# Restart
systemctl restart l2-collector.service
```

**L2 Scalping**:
```bash
# Check service
systemctl status l2-scalping.service

# View logs
tail -f /home/jacobw/quantstack/l2_scalping/logs/scalping_system.log

# Check SIP symbols
cat /home/jacobw/quantstack/data/daily_sip/sip_universe_$(date +%Y-%m-%d).txt
```

**Intraday Paper**:
```bash
# Check preflight
/home/jacobw/intraday_stack/.venv/bin/python \
  /home/jacobw/intraday_stack/scripts/ibkr_preflight.py --check-ibkr --check-polygon

# Check logs
tail -f /home/jacobw/intraday_stack/logs/paper_$(date +%Y%m%d).log

# Check SIP universe
cat /home/jacobw/intraday_stack/data/daily_sip/sip_universe_$(date +%Y-%m-%d).txt
```

---

## 9. QUICK REFERENCE

### 9.1 System Status Commands
```bash
# All trading services
systemctl status ibkr-platform l2-collector l2-scalping intraday-paper l2-watchdog

# Platform health
curl -s http://127.0.0.1:8000/health | jq .

# Registered services
curl -s http://127.0.0.1:8000/health | jq .services

# VPN status
systemctl status nordvpnd
nordvpn status
```

### 9.2 Log Commands
```bash
# Platform
journalctl -u ibkr-platform.service -f

# Services
journalctl -u l2-collector.service -f
journalctl -u l2-scalping.service -f
journalctl -u intraday-paper.service -f

# Applications
tail -f /home/jacobw/quantstack/l2_scalping/logs/scalping_system.log
tail -f /home/jacobw/intraday_stack/logs/paper_$(date +%Y%m%d).log
```

### 9.3 Restart Commands
```bash
# Platform (services auto-register)
systemctl restart ibkr-platform.service

# Individual services
systemctl restart l2-collector.service
systemctl restart l2-scalping.service
systemctl restart intraday-paper.service
systemctl restart l2-watchdog.service
```

---

**Last Updated**: 2026-01-13
**Next Review**: 2026-02-13

### Migration Benefits Achieved
- ✅ **No More Stale Connections**: REST-based interface eliminates socket issues completely
- ✅ **Centralized Management**: Single platform handles all IBKR connections
- ✅ **Service Simplification**: Removed complex ib_insync connection management from all services
- ✅ **Better Reliability**: Platform handles reconnection and error recovery automatically
- ✅ **Easier Debugging**: REST endpoints provide clear error messages and status

### Services Successfully Migrated
- ✅ **l2-collector**: Now uses IBKRPlatformClient for market data
- ✅ **l2-scalping**: Migrated to platform client for orders and data
- ✅ **intraday-paper**: Uses platform client for paper trading
- ✅ **l2-watchdog**: Enhanced monitoring with recovery detection

### Legacy Code Archived
- 📁 **18 socket-based files** moved to `archive/socket_based_ibkr/`
- 🗑️ **Obsolete gateway services** disabled and removed
- 📚 **Documentation updated** to reflect new platform architecture

### System Architecture

```
VPN (Manila) → IBKR API Platform (8000) → Client Portal Gateway (5000) → IBKR
                      ↓
    L2 Collector + L2 Scalping + Intraday Paper + L2 Watchdog
                      ↓
              Trading Notifications (NTFY)
```

**Platform Components:**
- **`cpapi/platform.py`** - FastAPI server with unified IBKR endpoints
- **`cpapi/platform_client.py`** - HTTP client replacing ib_insync in all services
- **`cpapi/trading_notifications.py`** - Comprehensive trading activity notifications
- **`ibkr-platform.service`** - Systemd service for platform management

**Migration Pattern Applied:**
```python
# BEFORE (socket-based - REMOVED)
# from ib_insync import IB
# ib = IB()
# ib.connect('127.0.0.1', 7497, clientId=521)

# AFTER (platform-based - CURRENT)
from cpapi.platform_client import IBKRPlatformClient
client = IBKRPlatformClient("service-id", "Service Name")
client.register(["market-data", "orders"])
```

---

## 1. VPN Connection & Infrastructure

### VPN Setup
- **Provider**: [Your VPN provider]
- **Server**: Manila, Philippines (UTC+8)
- **Purpose**: Stable connection to IBKR, consistent timezone
- **Status Check**: `curl ifconfig.me` (should show Manila IP)

### System Specifications
- **OS**: Ubuntu Linux
- **Timezone**: Manila (UTC+8) - System level
- **Trading Timezone**: America/New_York - Service level
- **Python**: 3.11+ with virtual environments

### Network Requirements
- **Stable connection**: <50ms latency to IBKR
- **Bandwidth**: Minimum 10Mbps for L2 data
- **Ports**: 5000 (Client Portal), 8000 (Platform)

---

## 2. IBKR API Platform (Core Infrastructure)

### Platform Service - **PRODUCTION READY**
- **Service**: `ibkr-platform.service` ✅ **RUNNING**
- **Port**: 8000 (HTTP REST API)
- **Backend**: Client Portal Gateway (port 5000)
- **Purpose**: Centralized IBKR connection management
- **Status**: **Migration complete** - All services connected

### API Endpoints Available
**Service Management:**
- `POST /services/register` - Register service with platform
- `POST /services/{id}/heartbeat` - Service heartbeat
- `GET /health` - Platform health and authentication status

**IBKR Operations:**
- `GET /api/accounts` - Get IBKR accounts
- `POST /api/market-data/snapshot` - Market data snapshots
- `GET /api/market-data/historical` - Historical data
- `POST /api/orders/place` - Place orders
- `GET /api/positions/{account}` - Get positions
- `GET /api/portfolio/{account}` - Portfolio summary

### Client Portal Gateway
- **Location**: `/home/jacobw/quantstack/cpapi/gateway/`
- **Port**: 5000 (HTTPS)
- **Authentication**: Browser login required (IBKR credentials + 2FA)
- **Session**: ~24 hours, resets at midnight
- **Status**: **Authenticated and stable**

### Daily Startup Sequence
1. **Start Client Portal Gateway**:
   ```bash
   cd /home/jacobw/quantstack/cpapi/gateway
   bin/run.sh root/conf.yaml
   ```

2. **Browser Authentication**:
   ```bash
   firefox https://localhost:5000
   # Login with IBKR credentials + 2FA
   ```

3. **Verify Platform**:
   ```bash
   curl http://127.0.0.1:8000/health | jq .authenticated
   # Should return: true
   ```

### Platform Management
```bash
# Service control
systemctl status ibkr-platform.service
systemctl restart ibkr-platform.service

# Health check
curl -s http://127.0.0.1:8000/health | jq .

# View registered services
curl -s http://127.0.0.1:8000/health | jq .services
```

---

## 3. Trading Services - **ALL MIGRATED TO PLATFORM**

### L2 Data Collector ✅ **MIGRATED**
- **Service**: `l2-collector.service`
- **Purpose**: NYSE Level 2 market depth collection
- **Client**: Uses `IBKRPlatformClient` (no more socket connections)
- **Data**: Order book snapshots, depth analysis
- **Storage**: `/home/jacobw/quantstack/data/l2_maximum/`
- **Status**: **Production ready** with platform integration

```bash
# Service control
systemctl status l2-collector.service
systemctl restart l2-collector.service

# View logs
journalctl -u l2-collector.service -f

# Check platform registration
curl -s http://127.0.0.1:8000/health | jq .services.l2_collector
```

### L2 Scalping System ✅ **MIGRATED**
- **Service**: `l2-scalping.service`
- **Purpose**: High-frequency scalping based on L2 signals
- **Client**: Uses `IBKRPlatformClient` for orders and market data
- **Strategy**: Order book imbalance, microstructure patterns
- **Risk**: Max 1% per position, 100 shares cap
- **Status**: **Production ready** with enhanced reliability

```bash
# Service control
systemctl status l2-scalping.service
systemctl restart l2-scalping.service

# View trading logs
tail -f /home/jacobw/quantstack/l2_scalping/logs/scalping_system.log

# Check positions via platform
curl -s http://127.0.0.1:8000/api/positions/DUN575068 | jq .
```

### Intraday Paper Trading ✅ **MIGRATED**
- **Service**: `intraday-paper.service`
- **Purpose**: ML-based intraday trading strategies
- **Client**: Uses `IBKRPlatformClient` for paper trading
- **Mode**: Paper trading (IBKR paper account)
- **Universe**: Daily SIP-selected symbols
- **Status**: **Production ready** with platform integration

```bash
# Service control
systemctl status intraday-paper.service
systemctl restart intraday-paper.service

# View paper trades
tail -f /home/jacobw/intraday_stack/logs/paper_$(date +%Y%m%d).log

# Check portfolio via platform
curl -s http://127.0.0.1:8000/api/portfolio/DUN575068 | jq .
```

### L2 Watchdog ✅ **ENHANCED**
- **Service**: `l2-watchdog.service`
- **Purpose**: Monitor all services and platform health
- **Enhancement**: Now includes recovery detection and platform monitoring
- **Notifications**: NTFY alerts for failures and recoveries
- **Status**: **Enhanced** with platform awareness

---

## 4. Automated Scheduling (NY Market Hours)

### Timer Schedule
| Service | Manila Time | NY Time | Purpose |
|---------|-------------|---------|---------|
| **preflight-check** | 20:00 | 07:00 AM | Pre-market validation |
| **trading-orchestrator** | 21:00 | 08:00 AM | System monitoring |
| **intraday-sip** | 22:10 | 09:10 AM | Daily universe selection |
| **intraday-paper** | 22:27 | 09:27 AM | Paper trading start |
| **system-health-monitor** | Every 5min | Every 5min | Health checks |

### Timer Management
```bash
# View all timers
systemctl list-timers | grep -E "(trading|l2|intraday|preflight|health)"

# Check specific timer
systemctl status intraday-sip.timer

# Manual trigger
systemctl start intraday-sip.service
```

### Daily SIP Generation
- **Service**: `intraday-sip.service`
- **Time**: 09:10 AM ET (20 minutes before market open)
- **Purpose**: Select daily trading universe from 1,700+ symbols
- **Output**: `/home/jacobw/intraday_stack/data/daily_sip/date=$(date +%F)/`

---

## 5. Monitoring & Alerting

### Health Monitoring
- **Service**: `system-health-monitor.service`
- **Frequency**: Every 5 minutes during market hours
- **Scope**: Service status, platform health, authentication

### L2 Watchdog
- **Service**: `l2-watchdog.service`
- **Purpose**: Monitor L2 collector health and auto-recovery
- **Actions**: Service restart, connection recovery

### NTFY Notifications ✅ **ENHANCED**
- **Channels**:
  - `jacobw-trading-alerts` - Errors and failures (enhanced with recovery detection)
  - `jacobw-trading-status` - System status updates (platform health included)
  - `jacobw-trading-trades` - **NEW**: Trade executions with P&L details

**Trading Notifications Include:**
- **Entry**: Symbol, direction, price, quantity, system
- **Exit**: Symbol, P&L, exit reason (TARGET/STOP/EXIT), system
- **Recovery**: Service recovery detection and alerts

```bash
# Test notifications
curl -d "Platform migration complete - System test from $(hostname)" ntfy.sh/jacobw-trading-alerts

# Subscribe on phone
# https://ntfy.sh/jacobw-trading-alerts
# https://ntfy.sh/jacobw-trading-status  
# https://ntfy.sh/jacobw-trading-trades
```

### Log Locations
```bash
# Platform logs
journalctl -u ibkr-platform.service -f

# Service logs
journalctl -u l2-collector.service -f
journalctl -u l2-scalping.service -f
journalctl -u intraday-paper.service -f

# Application logs
tail -f /home/jacobw/quantstack/l2_scalping/logs/scalping_system.log
tail -f /home/jacobw/intraday_stack/logs/paper_$(date +%Y%m%d).log
```

---

## 6. Daily Operations

### Pre-Market Checklist (07:00 AM ET) ✅ **AUTOMATED**
1. **VPN Status**: Verify Manila connection
2. **Gateway Authentication**: Check browser login status  
3. **Platform Health**: Verify API platform running and authenticated
4. **Service Registration**: Confirm all services registered with platform
5. **SIP Generation**: Confirm universe selection completed (09:10 AM ET)

```bash
# Quick system check (UPDATED for platform)
curl -s http://127.0.0.1:8000/health | jq .
systemctl status ibkr-platform l2-collector l2-scalping intraday-paper l2-watchdog

# Check service registration
curl -s http://127.0.0.1:8000/health | jq .services

# Verify authentication
curl -s http://127.0.0.1:8000/health | jq .authenticated
```

### Market Hours Monitoring (09:30 AM - 04:00 PM ET) ✅ **ENHANCED**
- **Platform**: Monitor authentication status and service health
- **Services**: All services now report to centralized platform
- **Trades**: Monitor execution via NTFY notifications with P&L
- **Data**: Verify L2 collection active via platform endpoints
- **Recovery**: Automatic detection and alerts for service recovery

### Post-Market Review (After 04:00 PM ET) ✅ **IMPROVED**
- **Performance**: Review trade journal with system attribution
- **Data Quality**: Check L2 collection statistics via platform
- **Logs**: Review platform and service logs for issues
- **Platform Status**: Verify platform ready for next day
- **Preparation**: All services auto-register on startup

---

## 7. Troubleshooting ✅ **PLATFORM-ENHANCED**

### Platform Issues

**Problem**: Platform not authenticated
```bash
# Check gateway status
curl -k -s https://localhost:5000/v1/api/iserver/auth/status

# Check platform authentication
curl -s http://127.0.0.1:8000/health | jq .authenticated

# If false, re-login via browser
firefox https://localhost:5000

# Restart platform after authentication
systemctl restart ibkr-platform.service
```

**Problem**: Services can't connect to platform
```bash
# Check platform health and registered services
curl -s http://127.0.0.1:8000/health | jq .

# Check service logs for connection errors
journalctl -u l2-collector.service -n 20

# Restart problematic service (will auto-register)
systemctl restart l2-collector.service

# Verify service registered
curl -s http://127.0.0.1:8000/health | jq .services
```

### Service Failures ✅ **IMPROVED DIAGNOSTICS**

**Problem**: L2 collector stopped
```bash
# Check service status
systemctl status l2-collector.service

# Check platform registration
curl -s http://127.0.0.1:8000/health | jq .services.l2_collector

# View recent logs
journalctl -u l2-collector.service -n 50

# Restart service (auto-registers with platform)
systemctl restart l2-collector.service
```

**Problem**: No trades executing
```bash
# Check platform authentication
curl -s http://127.0.0.1:8000/api/auth/status

# Check account status via platform
curl -s http://127.0.0.1:8000/api/accounts

# Check service registration
curl -s http://127.0.0.1:8000/health | jq .services

# Check service logs
journalctl -u l2-scalping.service -f
journalctl -u intraday-paper.service -f
```

### Data Issues ✅ **PLATFORM-INTEGRATED**

**Problem**: No L2 data collection
```bash
# Check L2 collector service and platform registration
systemctl status l2-collector.service
curl -s http://127.0.0.1:8000/health | jq .services.l2_collector

# Check data directory
ls -la /home/jacobw/quantstack/data/l2_maximum/features/date=$(date +%F)/

# Test platform market data access
curl -s http://127.0.0.1:8000/api/market-data/snapshot \
  -H "Content-Type: application/json" \
  -d '{"conids": [265598]}'

# Check service heartbeat
curl -s http://127.0.0.1:8000/health | jq '.services.l2_collector.last_heartbeat'
```

---

## 8. Emergency Procedures ✅ **PLATFORM-OPTIMIZED**

### System Failure Recovery
1. **Check VPN**: Ensure Manila connection active
2. **Restart Gateway**: Kill and restart Client Portal Gateway
3. **Re-authenticate**: Browser login to https://localhost:5000
4. **Restart Platform**: `systemctl restart ibkr-platform.service`
5. **Verify Platform**: `curl -s http://127.0.0.1:8000/health | jq .authenticated`
6. **Restart Services**: All services will auto-register with platform
7. **Verify Registration**: `curl -s http://127.0.0.1:8000/health | jq .services`

### Position Management ✅ **PLATFORM-INTEGRATED**
```bash
# Check current positions via platform
curl -s http://127.0.0.1:8000/api/positions/DUN575068 | jq .

# Check open orders via platform
curl -s http://127.0.0.1:8000/api/orders | jq .

# Check portfolio summary
curl -s http://127.0.0.1:8000/api/portfolio/DUN575068 | jq .

# Emergency position close (if needed)
# Use platform endpoints or manual intervention through IBKR Client Portal
```

### Data Recovery ✅ **ENHANCED**
```bash
# Check recent data
ls -la /home/jacobw/quantstack/data/l2_maximum/features/

# Check platform service registration
curl -s http://127.0.0.1:8000/health | jq .services

# Restart data collection (auto-registers)
systemctl restart l2-collector.service

# Verify collection resumed and registered
tail -f /home/jacobw/quantstack/logs/l2_collector.log
curl -s http://127.0.0.1:8000/health | jq .services.l2_collector
```

---

## 9. Performance Monitoring

### Key Metrics
- **Platform Uptime**: >99.5% during market hours
- **Authentication**: Stable 24-hour sessions
- **L2 Data**: >95% capture rate
- **Trade Execution**: <500ms average latency
- **Service Health**: All services running

### Daily Reports
```bash
# System health summary
curl -s http://127.0.0.1:8000/health | jq .

# L2 collection stats
ls -la /home/jacobw/quantstack/data/l2_maximum/features/date=$(date +%F)/ | wc -l

# Trading performance
# (Custom reporting scripts as needed)
```

---

## 10. Maintenance

### Weekly Tasks
- **Log Rotation**: Clean old log files
- **Data Cleanup**: Archive old L2 data
- **System Updates**: Apply security patches (off-hours)
- **Performance Review**: Analyze system metrics

### Monthly Tasks
- **Strategy Review**: Analyze trading performance
- **System Optimization**: Review and optimize configurations
- **Backup Verification**: Ensure data backups working
- **Documentation Updates**: Update procedures as needed

---

## Quick Reference

### Essential Commands ✅ **PLATFORM-UPDATED**
```bash
# System status (all migrated services)
systemctl status ibkr-platform l2-collector l2-scalping intraday-paper l2-watchdog

# Platform health and service registration
curl -s http://127.0.0.1:8000/health | jq .

# Check authenticated status
curl -s http://127.0.0.1:8000/health | jq .authenticated

# View registered services
curl -s http://127.0.0.1:8000/health | jq .services

# Service logs
journalctl -u ibkr-platform.service -f

# Emergency restart (services auto-register)
systemctl restart ibkr-platform.service
systemctl restart l2-collector.service
systemctl restart l2-scalping.service
systemctl restart intraday-paper.service
```

### Key Files ✅ **UPDATED**
- **Platform**: `/home/jacobw/quantstack/cpapi/` (platform.py, platform_client.py)
- **Archived Legacy**: `/home/jacobw/quantstack/archive/socket_based_ibkr/` (18 files)
- **L2 Data**: `/home/jacobw/quantstack/data/l2_maximum/`
- **Logs**: `/var/log/journal/` (systemd) + application logs
- **Config**: `/etc/systemd/system/` (services)
- **Trading Notifications**: `/home/jacobw/quantstack/cpapi/trading_notifications.py`

### Support Contacts
- **IBKR Support**: For account/connection issues
- **VPN Provider**: For connectivity issues
- **System Admin**: For infrastructure issues

---

## Complete File Inventory Index

### By System Component

**1. IBKR API Platform** (`/home/jacobw/quantstack/cpapi/`)
- `platform.py` - FastAPI server (main)
- `platform_client.py` - HTTP client for services
- `client.py` - CPAPI wrapper
- `trading_notifications.py` - NTFY notification module
- `check_gateway.py` - Gateway health checks
- `test_platform.py` - Platform tests
- `ibkr-platform.service` - Systemd service file

**2. L2 Data Collector** (`/home/jacobw/quantstack/qx-l2/`)
- `src/qx_l2/cli.py` - CLI entry point
- `src/qx_l2/collector.py` - Main collection logic
- `src/qx_l2/features.py` - Feature engineering (32 features)
- `src/qx_l2/symbols.py` - Symbol management
- `src/qx_l2/storage.py` - Parquet storage
- `src/qx_l2/journal.py` - Collection journal
- `src/qx_l2/scheduler.py` - Market hours scheduler
- `configs/maximum_l2.yaml` - Configuration

**3. L2 Scalping System** (`/home/jacobw/quantstack/l2_scalping/`)
- `src/main.py` - Main trading loop
- `src/data/l2_feed.py` - L2 data feed via platform
- `src/data/sip_integration.py` - SIP symbol loading
- `src/execution/order_manager.py` - Order execution
- `src/signals/l2_signals.py` - Signal generation (OBI)
- `src/signals/context_filter.py` - Context-aware filtering
- `src/signals/pattern_rules.py` - Pattern-based rules
- `src/risk/risk_manager.py` - Risk management
- `config/strategy.yaml` - Strategy configuration
- `config/risk.yaml` - Risk configuration
- `config/ibkr.yaml` - IBKR connection settings
- `start_scalping.sh` - Startup script
- `l2-scalping.service` - Systemd service file

**4. Intraday Paper Trading** (`/home/jacobw/intraday_stack/`)
- `scripts/paper_trade_platform.py` - Main trading loop
- `scripts/generate_daily_sip.sh` - SIP generation wrapper
- `scripts/generate_daily_sip_universe.py` - SIP generation logic
- `scripts/refresh_sip.py` - Mid-day SIP refresh
- `scripts/ibkr_preflight.py` - Pre-flight validation
- `scripts/start_paper_trading.sh` - Startup script
- `src/journal/event_store.py` - Trade journal (SQLite)
- `src/signals/candidate_generator.py` - Signal generation
- `data/journal/events.db` - SQLite database
- `data/daily_sip/date=*/sip_universe.json` - SIP universe files

**5. SIP Generation System** (`/home/jacobw/quantstack/`)
- `multi_session_sip_generator.py` - Multi-session SIP generator
- `bulletproof_orchestrator.py` - Main system orchestrator

**6. Monitoring & Alerting** (`/home/jacobw/quantstack/`)
- `system_health_monitor.py` - Platform health monitoring
- `scripts/l2_watchdog.py` - L2 collector watchdog
- `scripts/preflight_check.py` - Pre-market validation
- `cpapi/trading_notifications.py` - NTFY notifications
- `logs/orchestrator.log` - Orchestrator logs
- `logs/orchestrator_audit.log` - Orchestrator audit trail
- `logs/l2_watchdog.log` - Watchdog logs
- `/tmp/platform_health_state.json` - Recovery tracking state

**7. Systemd Services** (`/etc/systemd/system/` & local)
- `/etc/systemd/system/ibkr-platform.service`
- `/etc/systemd/system/l2-collector.service`
- `/etc/systemd/system/l2-scalping.service`
- `/etc/systemd/system/l2-watchdog.service`
- `/etc/systemd/system/intraday-paper.service`
- `/etc/systemd/system/intraday-sip.service`
- `/etc/systemd/system/preflight-check.service`
- `/etc/systemd/system/trading-orchestrator.service`
- `/etc/systemd/system/system-health-monitor.service`
- Local files in `/home/jacobw/quantstack/systemd/`

**8. Systemd Timers**
- `/etc/systemd/system/system-health-monitor.timer` (Every 5 min)
- `/etc/systemd/system/preflight-check.timer` (07:00 ET)
- `/etc/systemd/system/trading-orchestrator.timer` (08:00 ET)
- `/etc/systemd/system/intraday-sip.timer` (09:10 ET)
- Local files in `/home/jacobw/quantstack/systemd/`

**9. Scripts** (`/home/jacobw/quantstack/scripts/`)
- `start_ibkr_gateway.sh` - Gateway startup
- `wait_for_ibkr_gateway.sh` - Gateway wait
- `gateway_manager.py` - Gateway manager
- `gateway_failure_alert.sh` - Gateway alerts
- `service_failure_alert.sh` - Service alerts
- `install_l2_systemd.sh` - L2 installer
- `monitor_l2_live.sh` - L2 live monitor
- `start_trading_services.sh` - Trading startup
- `start_live_system.sh` - Full system startup
- `preflight_check.py` - Preflight check

**10. Configuration Files**
- `/home/jacobw/quantstack/cpapi/gateway/root/conf.yaml` - Gateway config
- `/home/jacobw/quantstack/qx-l2/configs/maximum_l2.yaml` - L2 collector config
- `/home/jacobw/quantstack/l2_scalping/config/strategy.yaml` - Strategy config
- `/home/jacobw/quantstack/l2_scalping/config/risk.yaml` - Risk config
- `/home/jacobw/quantstack/l2_scalping/config/ibkr.yaml` - IBKR config

**11. Data Storage**
- `/home/jacobw/quantstack/data/l2_maximum/features/` - L2 parquet data
- `/home/jacobw/intraday_stack/data/journal/events.db` - Trade journal
- `/home/jacobw/intraday_stack/data/daily_sip/` - SIP universe files
- `/tmp/platform_health_state.json` - Health tracking state

**12. NTFY Channels**
- `jacobw-trading-alerts` - Critical alerts
- `jacobw-trading-status` - Status updates
- `jacobw-trading-trades` - Trade notifications

---

**Document Version**: 3.0 (Complete System Documentation)
**Last Updated**: 2026-01-13
**Next Review**: 2026-02-13
