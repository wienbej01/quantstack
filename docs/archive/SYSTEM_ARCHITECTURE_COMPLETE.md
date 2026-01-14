# Complete System Architecture & Component Map

**Quantstack Trading System - Comprehensive Technical Documentation**
**Version**: 3.0 (Platform-Based Architecture)
**Date**: 2026-01-13
**Status**: Production

## Executive Summary

The Quantstack trading system is a fully automated, platform-based trading infrastructure running on Manila VPS. The system consists of 13 systemd services orchestrating VPN connectivity, IBKR gateway management, data collection, SIP generation, L2 microstructure analysis, and live paper trading. All components communicate via the centralized IBKR API Platform (port 8000), Polygon API, and NTFY notifications.

---

## 1. SYSTEMD SERVICES (Complete Inventory)

### 1.1 Infrastructure Services

#### A. NordVPN Daemon
**Service Unit**: `/usr/lib/systemd/system/nordvpnd.service`
**Socket Unit**: `/usr/lib/systemd/system/nordvpnd.socket`
**Status**: `active (running)`
**Purpose**: Secure VPN connection for IBKR access

**Dependencies**:
- Required by: `ibkr-gateway.service`

**Verification**:
```bash
systemctl status nordvpnd.service
nordvpn status
curl ifconfig.me  # Should show Manila IP
```

#### B. X Virtual Framebuffer
**Service Unit**: `/etc/systemd/system/xvfb.service`
**Purpose**: Virtual display for IBKR Gateway GUI

**Dependencies**:
- Required by: `ibkr-gateway.service`

---

### 1.2 IBKR Infrastructure Services

#### A. IBKR Client Portal Gateway
**Service Unit**: `/etc/systemd/system/ibkr-gateway.service`
**Status**: `inactive` (replaced by platform, kept for backup)
**Port**: 5000 (HTTPS)
**Location**: `/home/jacobw/quantstack/cpapi/gateway/`

**Service File Contents**:
```ini
[Unit]
Description=IBKR Gateway (IBC-managed)
After=network-online.target nordvpnd.service xvfb.service
Wants=network-online.target nordvpnd.service xvfb.service

[Service]
Type=simple
User=jacobw
Group=jacobw
WorkingDirectory=/home/jacobw/quantstack
Environment=TZ=America/New_York
Environment=DISPLAY=:99
Environment=PATH=/home/jacobw/.local/bin:/home/jacobw/quantstack/.venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/home/jacobw/quantstack/scripts/start_ibkr_gateway.sh
Restart=on-failure
RestartSec=30
StandardOutput=journal
StandardError=journal
TimeoutStartSec=300
TimeoutStopSec=60

[Install]
WantedBy=multi-user.target
```

**Key Files**:
```
/home/jacobw/quantstack/cpapi/gateway/
├── bin/run.sh                    # Gateway startup script
├── root/conf.yaml                # Gateway configuration
├── clientportal.gw.zip          # Gateway distribution
├── logs/                         # Gateway logs
└── gateway.log                   # Runtime log

/home/jacobw/quantstack/scripts/
├── start_ibkr_gateway.sh         # Startup wrapper
├── wait_for_ibkr_gateway.sh      # Wait for ready state
└── gateway_failure_alert.sh      # Failure notifications
```

**Drop-in Configuration**:
```
/etc/systemd/system/ibkr-gateway.service.d/
└── resilience.conf               # Resilience settings
```

#### B. Gateway Manager
**Service Unit**: `/etc/systemd/system/gateway-manager.service`
**Purpose**: Automated gateway health monitoring and recovery

**Service File Contents**:
```ini
[Unit]
Description=IBKR Gateway Manager Daemon
After=network.target xvfb.service
Wants=xvfb.service

[Service]
Type=simple
User=root
Environment=TZ=America/New_York
ExecStart=/home/jacobw/quantstack/.venv/bin/python /home/jacobw/quantstack/scripts/gateway_manager.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Script**: `/home/jacobw/quantstack/scripts/gateway_manager.py`

#### C. IBKR API Platform (Primary)
**Service Unit**: `/etc/systemd/system/ibkr-platform.service`
**Status**: `active (running)`
**Port**: 8000 (HTTP REST API)
**Backend**: Client Portal Gateway (port 5000)

**Service File Contents**:
```ini
[Unit]
Description=IBKR API Platform Service
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=jacobw
Group=jacobw
WorkingDirectory=/home/jacobw/quantstack
Environment=PATH=/home/jacobw/.local/bin:/home/jacobw/quantstack/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=TZ=America/New_York
ExecStart=/usr/bin/python3 -m cpapi.platform
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

# Resource limits
MemoryMax=512M
CPUQuota=25%

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**Key Files**:
```
/home/jacobw/quantstack/cpapi/
├── __init__.py
├── platform.py                  # FastAPI server (main)
├── platform_client.py           # HTTP client for services
├── client.py                    # CPAPI wrapper
├── trading_notifications.py     # NTFY notification module
├── check_gateway.py             # Gateway health checks
├── test_platform.py             # Platform tests
├── test_cpapi_connections.py    # Connection tests
├── PLATFORM_ARCHITECTURE.md     # Architecture docs
├── ibkr-platform.service        # Service file
└── gateway/                     # Client Portal Gateway
    ├── bin/run.sh
    ├── root/conf.yaml
    └── logs/
```

**API Endpoints**:
```
Health & Service Management:
  GET  /health                          # Platform health + registered services
  POST /services/register               # Register service with platform
  POST /services/{id}/heartbeat         # Service heartbeat

IBKR Operations:
  GET  /api/accounts                    # List IBKR accounts
  GET  /api/market-data/snapshot        # Market data snapshot
  GET  /api/market-data/historical      # Historical bar data
  POST /api/orders/place                # Place order
  GET  /api/orders                      # List open orders
  GET  /api/positions/{account}         # Get positions
  GET  /api/portfolio/{account}         # Portfolio summary
```

---

### 1.3 Data Collection Services

#### A. L2 Data Collector
**Service Unit**: `/etc/systemd/system/l2-collector.service`
**Timer Unit**: `/etc/systemd/system/l2-collector.timer`
**Status**: `active (running)`
**Binary**: `/home/jacobw/.local/bin/l2-collect`

**Service File Contents**:
```ini
[Unit]
Description=L2 Data Collector (Daily Daemon)
After=network.target

[Service]
Type=simple
User=jacobw
WorkingDirectory=/home/jacobw/quantstack
Environment=PATH=/home/jacobw/.local/bin:/home/jacobw/quantstack/.venv/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONPATH=/home/jacobw/quantstack:/home/jacobw/quantstack/qx-l2/src
Environment=TZ=America/New_York
ExecStart=/home/jacobw/.local/bin/l2-collect --config qx-l2/configs/maximum_l2.yaml --daemon
Restart=on-failure
RestartSec=60
StandardOutput=journal
StandardError=journal
TimeoutStartSec=30
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
```

**Drop-in Configuration**:
```
/etc/systemd/system/l2-collector.service.d/
└── alerts.conf
    [Service]
    ExecStopPost=/home/jacobw/quantstack/scripts/service_failure_alert.sh l2-collector
```

**Key Files**:
```
/home/jacobw/quantstack/qx-l2/
├── src/qx_l2/
│   ├── __init__.py
│   ├── cli.py                      # CLI entry point
│   ├── collector.py                # Main collection logic
│   ├── features.py                 # Feature engineering (32 features)
│   ├── symbols.py                  # Symbol management
│   ├── storage.py                  # Parquet storage
│   ├── journal.py                  # Collection journal
│   ├── scheduler.py                # Market hours scheduler
│   └── config.py                   # Configuration loader
├── configs/
│   └── maximum_l2.yaml             # Collector configuration
├── scripts/
│   ├── run_collector.py            # Standalone runner
│   ├── analyze_data.py             # Data analysis
│   └── export_dataset.py           # Dataset export
└── monitor_l2.py                   # Monitoring script

/home/jacobw/.local/bin/
└── l2-collect                      # Entry point (symlink to qx_l2.cli)
```

**Configuration** (`qx-l2/configs/maximum_l2.yaml`):
```yaml
# Platform connection
platform:
  base_url: http://127.0.0.1:8000
  service_id: l2_collector
  service_name: "L2 Data Collector"
  capabilities: ["market-data", "snapshot"]

# Symbol management (auto-loaded from SIP)
symbols: []

# Data collection
collection:
  max_concurrent: 3
  snapshot_interval_ms: 100
  market_depth: 5

# Feature engineering
features:
  - order_book_imbalance
  - bid_ask_spread
  - total_depth
  - depth_ratio
  - spread_crossing
  - price_level_distribution
  # ... 32 total features

# Storage
storage:
  base_path: ./data/l2_maximum/features
  format: parquet
  partition: ["date", "symbol"]
```

**Data Storage**:
```
/home/jacobw/quantstack/data/l2_maximum/features/
└── date=YYYY-MM-DD/
    └── symbol={TICKER}/
        └── {TIMESTAMP}.parquet
```

---

#### B. L2 Collector Watchdog
**Service Unit**: `/etc/systemd/system/l2-watchdog.service`
**Status**: `active (running)`
**Purpose**: Monitor L2 collector health and auto-recovery

**Service File Contents**:
```ini
[Unit]
Description=L2 Collector Watchdog Monitor
After=network.target
Wants=l2-collector.service

[Service]
Type=simple
User=jacobw
WorkingDirectory=/home/jacobw/quantstack
Environment=PATH=/home/jacobw/.local/bin:/home/jacobw/quantstack/.venv/bin:/usr/bin:/bin
ExecStart=/home/jacobw/quantstack/.venv/bin/python /home/jacobw/quantstack/scripts/l2_watchdog.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Script**: `/home/jacobw/quantstack/scripts/l2_watchdog.py`

**Error Patterns Monitored**:
```python
fatal_patterns = [
    r"Connection refused",
    r"Connection reset",
    r"Disconnected unexpectedly",
    r"Failed to connect",
    r"API connection lost",
    r"Peer closed connection",
    r"Error 504",  # Gateway timeout
    r"Error 1100",  # Connectivity lost
]

gateway_crash_patterns = [
    r"Error 317.*Market depth data has been RESET",
    r"Peer closed connection",
    r"Connection reset by peer",
    r"Socket connection broken",
]
```

---

### 1.4 Trading Execution Services

#### A. L2 Scalping System
**Service Unit**: `/etc/systemd/system/l2-scalping.service`
**Timer Unit**: `/etc/systemd/system/l2-scalping.timer`
**Status**: `activating (auto-restart)` (connection issues)
**Location**: `/home/jacobw/quantstack/l2_scalping/`

**Service File Contents**:
```ini
[Unit]
Description=L2 Scalping Trading System
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=jacobw
Group=jacobw
WorkingDirectory=/home/jacobw/quantstack/l2_scalping
ExecStart=/home/jacobw/quantstack/l2_scalping/start_scalping.sh
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

# Resource limits
MemoryMax=1G
CPUQuota=50%

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**Drop-in Configuration**:
```
/etc/systemd/system/l2-scalping.service.d/
└── alerts.conf
    [Service]
    ExecStopPost=/home/jacobw/quantstack/scripts/service_failure_alert.sh l2-scalping
```

**Key Files**:
```
/home/jacobw/quantstack/l2_scalping/
├── src/
│   ├── __init__.py
│   ├── main.py                      # Main trading loop
│   ├── data/
│   │   ├── __init__.py
│   │   ├── l2_feed.py               # L2 data feed via platform
│   │   └── sip_integration.py       # SIP symbol loading
│   ├── execution/
│   │   ├── __init__.py
│   │   └── order_manager.py         # Order execution (platform client)
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── l2_signals.py            # OBI momentum signals
│   │   ├── context_filter.py        # Context-aware filtering
│   │   └── pattern_rules.py         # Pattern-based rules
│   ├── risk/
│   │   ├── __init__.py
│   │   └── risk_manager.py          # Risk management
│   ├── reporting/
│   │   ├── __init__.py
│   │   ├── performance_reporter.py  # Performance tracking
│   │   └── trade_journal.py         # Trade logging
│   └── scheduler.py                 # Market hours scheduler
├── config/
│   ├── strategy.yaml                # Strategy configuration
│   ├── risk.yaml                    # Risk configuration
│   └── ibkr.yaml                    # IBKR connection settings
├── data/                            # Local trade data
├── logs/                            # Application logs
│   └── scalping_system.log
├── analysis/                        # Analysis scripts
├── tests/
├── start_scalping.sh                # Entry point
└── README.md
```

**Strategy Configuration** (`config/strategy.yaml`):
```yaml
strategy:
  name: "L2_OBI_Momentum_Scalper"
  version: "2.0"

  # OBI thresholds
  obi_entry_threshold: 0.8
  obi_extreme_threshold: 0.9
  min_confidence: 0.3
  max_spread_multiple: 2.0
  confirm_k: 2

  # Calibration
  calibration_window_points: 240
  min_calibration_points: 60

  # Timing
  default_hold_seconds: 300
  max_hold_seconds: 600
  min_time_between_trades_ms: 1000

# Pattern-based rules
pattern_rules:
  rule1_enabled: true
  rule1_d_obi_30s: 0.2
  rule1_depth_ask: 25000

  rule2_enabled: true
  rule2_depth_bid: 25000
  rule2_d_obi_15s: 0.1

  rule3_enabled: true
  rule3_obi_1: 0.1
  rule3_depth_ask: 30000

# Context gates
context_gates:
  hard:
    block_vol_expansion: true
    block_bb_squeeze: true
    block_vol_contraction: false

# Schedule
schedule:
  start_time: "09:30"
  end_time: "16:00"
  timezone: "America/New_York"
```

---

#### B. Intraday Paper Trading
**Service Unit**: `/etc/systemd/system/intraday-paper.service`
**Timer Unit**: `/etc/systemd/system/intraday-paper.timer`
**Status**: `failed` (preflight check failing)
**Location**: `/home/jacobw/intraday_stack/`

**Service File Contents**:
```ini
[Unit]
Description=Intraday Paper Trading System
After=network.target

[Service]
Type=simple
User=jacobw
WorkingDirectory=/home/jacobw/intraday_stack
ExecStart=/home/jacobw/intraday_stack/scripts/start_paper_trading.sh
Restart=no
TimeoutStopSec=30

[Install]
WantedBy=multi-user.target
```

**Drop-in Configurations**:
```
/etc/systemd/system/intraday-paper.service.d/
├── alerts.conf
│   [Service]
│   ExecStopPost=/home/jacobw/quantstack/scripts/service_failure_alert.sh intraday-paper
└── override.conf
```

**Key Files**:
```
/home/jacobw/intraday_stack/
├── scripts/
│   ├── paper_trade_platform.py      # Main trading loop (platform-based)
│   ├── start_paper_trading.sh       # Service entry point
│   ├── generate_daily_sip.sh        # SIP generation wrapper
│   ├── generate_daily_sip_universe.py  # SIP generation logic
│   ├── refresh_sip.py               # Mid-day SIP refresh
│   ├── ibkr_preflight.py            # Pre-flight validation
│   └── check_gold_data.py           # Gold data validation
├── src/
│   ├── journal/
│   │   └── event_store.py           # SQLite trade journal
│   ├── notifications/
│   │   └── ntfy_notifier.py         # NTFY notifications
│   ├── universe/
│   │   └── polygon_sip_universe.py  # SIP loading
│   └── signals/
│       └── candidate_generator.py   # Signal generation
├── data/
│   ├── journal/
│   │   └── events.db                # SQLite database
│   └── daily_sip/
│       └── date=YYYY-MM-DD/
│           └── sip_universe.json
└── logs/
    └── paper_YYYYMMDD.log
```

**Startup Script** (`scripts/start_paper_trading.sh`):
```bash
#!/bin/bash
cd /home/jacobw/intraday_stack
export PATH="/home/jacobw/intraday_stack/.venv/bin:$PATH"
export PYTHONPATH="/home/jacobw/intraday_stack/src:$PYTHONPATH"

if [ -z "$POLYGON_API_KEY" ] && [ -f /home/jacobw/.bashrc ]; then
    POLYGON_API_KEY=$(sed -n "s/^export POLYGON_API_KEY=['\\\"]\\{0,1\\}\\([^'\\\"]\\+\\)['\\\"]\\{0,1\\}$/\\1/p" /home/jacobw/.bashrc | head -n 1)
    export POLYGON_API_KEY
fi

DATE=$(date +%Y%m%d)
LOG="logs/paper_${DATE}.log"
PYTHON="/home/jacobw/intraday_stack/.venv/bin/python"

echo "=== Session Start: $(date) ===" >> $LOG

# Preflight check
$PYTHON scripts/ibkr_preflight.py --check-ibkr --check-polygon >> $LOG 2>&1
if [ $? -ne 0 ]; then
    echo "PREFLIGHT FAILED" >> $LOG
    exit 1
fi

# Run paper trading
$PYTHON scripts/paper_trade_platform.py --paper >> $LOG 2>&1
echo "=== Session End: $(date) ===" >> $LOG
```

---

### 1.5 Scheduling Services

#### A. Pre-Flight Check
**Service Unit**: `/etc/systemd/system/preflight-check.service`
**Timer Unit**: `/etc/systemd/system/preflight-check.timer`
**Schedule**: Mon..Fri 07:00:00 America/New_York (20:00 Manila)

**Service File Contents**:
```ini
[Unit]
Description=Pre-Flight Trading System Validation
After=network.target

[Service]
Type=oneshot
User=jacobw
WorkingDirectory=/home/jacobw/quantstack
Environment=TZ=America/New_York
ExecStart=/home/jacobw/quantstack/.venv/bin/python /home/jacobw/quantstack/scripts/preflight_check.py
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Timer File Contents**:
```ini
[Unit]
Description=Pre-Flight Check Timer (1 hour before orchestrator)
Requires=preflight-check.service

[Timer]
OnCalendar=Mon..Fri 07:00:00 America/New_York
Persistent=true
AccuracySec=1min

[Install]
WantedBy=timers.target
```

**Script**: `/home/jacobw/quantstack/scripts/preflight_check.py`

---

#### B. Trading Orchestrator
**Service Unit**: `/etc/systemd/system/trading-orchestrator.service`
**Timer Unit**: `/etc/systemd/system/trading-orchestrator.timer`
**Schedule**: Mon..Fri 08:00:00 America/New_York (21:00 Manila)

**Service File Contents**:
```ini
[Unit]
Description=Trading System Orchestrator
After=network.target

[Service]
Type=oneshot
User=jacobw
WorkingDirectory=/home/jacobw/quantstack
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/etc/systemd/system/polygon.env
ExecStart=/home/jacobw/quantstack/.venv/bin/python /home/jacobw/quantstack/bulletproof_orchestrator.py
StandardOutput=append:/home/jacobw/quantstack/logs/orchestrator.log
StandardError=append:/home/jacobw/quantstack/logs/orchestrator.log
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
```

**Timer File Contents**:
```ini
[Unit]
Description=Trading System Orchestrator Timer (Pre-Market)
Requires=trading-orchestrator.service

[Timer]
OnCalendar=Mon..Fri 08:00:00 America/New_York
Persistent=true
AccuracySec=1min

[Install]
WantedBy=timers.target
```

**Key Files**:
```
/home/jacobw/quantstack/
├── bulletproof_orchestrator.py     # Current orchestrator
├── trading_orchestrator.py         # Legacy (backup)
└── logs/
    ├── orchestrator.log
    └── orchestrator_audit.log
```

**Environment File**: `/etc/systemd/system/polygon.env`
```
POLYGON_API_KEY=ZBxeJYOn0_e0UcPgEYLA90CQ9S28_EfU
```

---

#### C. Daily SIP Generation
**Service Unit**: `/etc/systemd/system/intraday-sip.service`
**Timer Unit**: `/etc/systemd/system/intraday-sip.timer`
**Schedule**: Mon..Fri 09:10:00 America/New_York (22:10 Manila)

**Service File Contents**:
```ini
[Unit]
Description=Generate Daily SIP Universe (Full Process)
After=network.target

[Service]
Type=oneshot
User=jacobw
WorkingDirectory=/home/jacobw/intraday_stack
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/jacobw/intraday_stack/scripts/generate_daily_sip.sh
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Timer File Contents**:
```ini
[Unit]
Description=Daily SIP Universe Refresh (20 min before market open)

[Timer]
OnCalendar=Mon-Fri 09:10:00 America/New_York
Persistent=true

[Install]
WantedBy=timers.target
```

**Drop-in Configuration**:
```
/etc/systemd/system/intraday-sip.service.d/
└── override.conf
```

**Startup Script** (`scripts/generate_daily_sip.sh`):
```bash
#!/bin/bash
cd /home/jacobw/intraday_stack

DATE=$(date -d "today" +%Y-%m-%d)
LOG="logs/sip_generation_$(date +%Y%m%d).log"

echo "=== SIP Generation Start: $(date) ===" >> $LOG

/home/jacobw/intraday_stack/.venv/bin/python scripts/generate_daily_sip_universe.py \
    --date $DATE \
    --data-source polygon \
    --min-price 2.0 \
    --max-price 200.0 \
    --min-dv-pre 5000000 \
    --score-floor 0.70 \
    --workers 8 >> $LOG 2>&1

EXIT_CODE=$?
echo "=== SIP Generation End: $(date), Exit Code: $EXIT_CODE ===" >> $LOG
exit $EXIT_CODE
```

---

#### D. System Health Monitor
**Service Unit**: `/etc/systemd/system/system-health-monitor.service`
**Timer Unit**: `/etc/systemd/system/system-health-monitor.timer`
**Schedule**: Every 5 minutes (*:0/5)

**Service File Contents**:
```ini
[Unit]
Description=Trading System Health Monitor
After=network.target

[Service]
Type=oneshot
User=jacobw
WorkingDirectory=/home/jacobw/quantstack
Environment=TZ=America/New_York
ExecStart=/home/jacobw/quantstack/.venv/bin/python /home/jacobw/quantstack/system_health_monitor.py
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

**Timer File Contents**:
```ini
[Unit]
Description=Trading System Health Monitor (Market Hours Only)
Requires=system-health-monitor.service

[Timer]
OnCalendar=*:0/5
Persistent=false
AccuracySec=1min

[Install]
WantedBy=timers.target
```

**Script**: `/home/jacobw/quantstack/system_health_monitor.py`

**State File**: `/tmp/platform_health_state.json`

---

### 1.6 Emergency Services

#### A. Emergency EOD Close
**Service Unit**: `/etc/systemd/system/emergency-eod-close.service`
**Timer Unit**: `/etc/systemd/system/emergency-eod-close.timer`
**Purpose**: Emergency position closure at end of day

---

## 2. TIMER SCHEDULE SUMMARY

| Timer | Schedule (ET) | Schedule (Manila) | Service | Purpose |
|-------|---------------|-------------------|---------|---------|
| `preflight-check.timer` | 07:00 | 20:00 | preflight-check | Pre-market validation |
| `trading-orchestrator.timer` | 08:00 | 21:00 | trading-orchestrator | System monitoring |
| `intraday-sip.timer` | 09:10 | 22:10 | intraday-sip | Daily SIP generation |
| `system-health-monitor.timer` | Every 5min | Every 5min | system-health-monitor | Health checks |
| `l2-collector.timer` | N/A | N/A | l2-collector | Manual trigger |
| `l2-scalping.timer` | N/A | N/A | l2-scalping | Manual trigger |
| `intraday-paper.timer` | N/A | N/A | intraday-paper | Manual trigger |
| `emergency-eod-close.timer` | 16:00 | 05:00 | emergency-eod-close | Emergency close |

---

## 3. CONFIGURATION FILES INVENTORY

### 3.1 Platform Configuration

**IBKR API Platform**:
```
/home/jacobw/quantstack/cpapi/
├── platform.py                    # FastAPI server configuration
├── platform_client.py             # Client configuration
├── client.py                      # CPAPI settings
├── trading_notifications.py       # NTFY configuration
├── check_gateway.py               # Health check settings
└── gateway/
    └── root/conf.yaml             # Gateway configuration
```

**Platform Settings** (from `platform.py`):
```python
# Server configuration
HOST = "0.0.0.0"
PORT = 8000

# Gateway connection
GATEWAY_URL = "https://localhost:5000"
GATEWAY_TIMEOUT = 30

# Service registry
SERVICE_HEARTBEAT_INTERVAL = 30
SERVICE_HEARTBEAT_TIMEOUT = 120
```

---

### 3.2 L2 Collector Configuration

**File**: `/home/jacobw/quantstack/qx-l2/configs/maximum_l2.yaml`

```yaml
# Platform settings
platform:
  base_url: http://127.0.0.1:8000
  service_id: l2_collector
  service_name: "L2 Data Collector"
  capabilities: ["market-data", "snapshot"]

# Symbol configuration
symbols: []  # Auto-loaded from SIP

# Collection settings
collection:
  max_concurrent_symbols: 3
  snapshot_interval_ms: 100
  market_depth_levels: 5
  exchange: "NYSE"

# Feature engineering
features:
  enabled: true
  list:
    - order_book_imbalance
    - bid_ask_spread
    - total_bid_depth
    - total_ask_depth
    - depth_ratio
    - spread_crossing
    - mid_price
    - vwap
    - price_momentum_5s
    - price_momentum_15s
    - price_momentum_30s
    - obi_momentum_5s
    - obi_momentum_15s
    - obi_momentum_30s
    - depth_trend_bid
    - depth_trend_ask
    - volatility_10s
    - volatility_30s
    - volume_pressure
    - large_trade_ratio
    - top_of_book_imbalance
    - depth_skew
    - price_range_1m
    - price_range_5m
    - relative_volume
    - time_since_last_trade
    - bid_levels_count
    - ask_levels_count
    - spread_velocity
    - depth_velocity
    - order_flow_rate
    - institutional_activity
    - retail_activity
    - market_sentiment

# Storage configuration
storage:
  base_path: ./data/l2_maximum/features
  format: parquet
  compression: snappy
  partition_by: ["date", "symbol"]
  file_naming: "timestamp"

# Schedule
schedule:
  start_time: "09:30"
  end_time: "16:00"
  timezone: "America/New_York"
```

---

### 3.3 L2 Scalping Configuration

**File**: `/home/jacobw/quantstack/l2_scalping/config/strategy.yaml`

```yaml
strategy:
  name: "L2_OBI_Momentum_Scalper"
  version: "2.0"

  # OBI thresholds
  obi_entry_threshold: 0.8
  obi_extreme_threshold: 0.9
  min_confidence: 0.3
  max_spread_multiple: 2.0
  confirm_k: 2

  # Calibration
  calibration_window_points: 240
  min_calibration_points: 60

  # Timing
  default_hold_seconds: 300
  max_hold_seconds: 600
  min_time_between_trades_ms: 1000

# Pattern-based rules
pattern_rules:
  rule1_enabled: true
  rule1_d_obi_30s: 0.2
  rule1_depth_ask: 25000

  rule2_enabled: true
  rule2_depth_bid: 25000
  rule2_d_obi_15s: 0.1

  rule3_enabled: true
  rule3_obi_1: 0.1
  rule3_depth_ask: 30000

# Context gates
context_gates:
  hard:
    block_vol_expansion: true
    block_bb_squeeze: true
    block_vol_contraction: false
  soft:
    vol_expansion_threshold: 1.5
    bb_squeeze_threshold: 0.1
    vol_contraction_threshold: 0.5

# Schedule
schedule:
  start_time: "09:30"
  end_time: "16:00"
  timezone: "America/New_York"
  warmup_minutes: 30
```

**File**: `/home/jacobw/quantstack/l2_scalping/config/risk.yaml`

```yaml
risk:
  # Position sizing
  max_position_value: 1000
  max_positions: 3
  position_sizing_method: "fixed"

  # Stop loss
  stop_loss_pct: 0.01
  stop_loss_atr_multiple: 1.5

  # Take profit
  take_profit_pct: 0.015
  take_profit_atr_multiple: 2.0

  # Circuit breaker
  circuit_breaker:
    enabled: true
    max_daily_loss: 100
    max_consecutive_losses: 3
    cooldown_minutes: 30
```

**File**: `/home/jacobw/quantstack/l2_scalping/config/ibkr.yaml`

```yaml
ibkr:
  # Platform connection
  platform:
    base_url: http://127.0.0.1:8000
    service_id: l2_scalping
    service_name: "L2 Scalping System"
    capabilities: ["market-data", "orders"]

  # Account
  account:
    account_id: "DUN575068"
    initial_capital: 100000

  # Market data
  market_data:
    symbols: []  # Auto-loaded from SIP
    snapshot_interval: 0.1

  # Orders
  orders:
    order_type: "MKT"
    time_in_force: "DAY"
    outside_rth: false
```

---

### 3.4 Intraday Paper Configuration

Configuration is embedded in Python scripts:

**File**: `/home/jacobw/intraday_stack/scripts/paper_trade_platform.py`

```python
# Platform settings
PLATFORM_URL = "http://127.0.0.1:8000"
SERVICE_ID = "intraday_paper"
SERVICE_NAME = "Intraday Paper Trading"

# Account
PAPER_ACCOUNT_ID = "DUN575068"

# Strategy parameters
STRATEGY_PARAMS = {
    "entry_threshold": 0.7,
    "exit_threshold": 0.3,
    "hold_time_minutes": 60,
}
```

**File**: `/home/jacobw/intraday_stack/scripts/generate_daily_sip_universe.py`

```python
# SIP generation parameters
SIP_CONFIG = {
    "min_price": 2.0,
    "max_price": 200.0,
    "min_dv_pre": 5000000,
    "score_floor": 0.70,
    "max_symbols": 20,
    "workers": 8,
}
```

---

## 4. DATA STORAGE LOCATIONS

### 4.1 L2 Market Data

**Location**: `/home/jacobw/quantstack/data/l2_maximum/features/`

**Structure**:
```
data/l2_maximum/features/
├── date=2025-01-13/
│   ├── symbol=SPY/
│   │   ├── 20250113_093000.parquet
│   │   ├── 20250113_093100.parquet
│   │   └── ...
│   ├── symbol=QQQ/
│   └── symbol=IWM/
└── date=2025-01-12/
    └── ...
```

**Parquet Schema**:
```
timestamp: int64 (nanoseconds)
symbol: string
bid_price: float
ask_price: float
bid_size: int
ask_size: int
total_bid_depth: float
total_ask_depth: float
order_book_imbalance: float
# ... 32 total features
```

**Data Retention**: Daily partitions, managed by storage policy

---

### 4.2 SIP Universe Data

**Location**: `/home/jacobw/intraday_stack/data/daily_sip/`

**Structure**:
```
data/daily_sip/
├── date=2025-01-13/
│   └── sip_universe.json
├── date=2025-01-12/
│   └── sip_universe.json
└── ...
```

**JSON Schema**:
```json
{
  "date": "2025-01-13",
  "generated_at": "2025-01-13T09:10:00Z",
  "symbols": [
    {
      "symbol": "SPY",
      "score": 0.85,
      "price": 450.25,
      "volume": 50000000,
      "dv_pre": 22500000000
    }
  ],
  "total_symbols": 4,
  "universe_size": 1796
}
```

**Legacy Format**: Text files in `/home/jacobw/quantstack/data/daily_sip/`

---

### 4.3 Trade Journal

**Location**: `/home/jacobw/intraday_stack/data/journal/events.db`

**SQLite Schema**:

```sql
-- Trades table
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_price REAL,
    quantity INTEGER NOT NULL,
    pnl REAL,
    system TEXT NOT NULL,
    exit_reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Orders table
CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER,
    symbol TEXT NOT NULL,
    order_type TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price REAL,
    status TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    filled_at TEXT,
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);

-- Decisions table
CREATE TABLE decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    signal_value REAL NOT NULL,
    action TEXT NOT NULL,
    reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Risk events table
CREATE TABLE risk_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

---

### 4.4 Log Files

**Application Logs**:
```
/home/jacobw/quantstack/logs/
├── orchestrator.log              # Orchestrator output
└── orchestrator_audit.log        # Orchestrator audit trail

/home/jacobw/quantstack/l2_scalping/logs/
├── scalping_system.log           # L2 scalping system
└── performance_report.log        # Performance reports

/home/jacobw/intraday_stack/logs/
├── paper_YYYYMMDD.log            # Paper trading daily logs
├── sip_generation_YYYYMMDD.log   # SIP generation logs
└── sip.log                       # General SIP logs
```

**Systemd Logs** (journalctl):
```bash
# Platform logs
journalctl -u ibkr-platform.service

# Service logs
journalctl -u l2-collector.service
journalctl -u l2-scalping.service
journalctl -u intraday-paper.service
journalctl -u l2-watchdog.service

# Orchestrator logs
journalctl -u trading-orchestrator.service
journalctl -u preflight-check.service

# Health monitor logs
journalctl -u system-health-monitor.service

# All trading logs
journalctl | grep -E "(trading|l2|intraday|ibkr|platform)"
```

---

## 5. NTFY NOTIFICATION CHANNELS

**Channels**:
```
jacobw-trading-alerts    # Errors, failures, recovery
jacobw-trading-status    # System status, health
jacobw-trading-trades    # Trade entries, exits, P&L
```

**Module**: `/home/jacobw/quantstack/cpapi/trading_notifications.py`

**Functions**:
```python
send_trade_notification(
    action: str,          # "ENTRY" or "EXIT"
    symbol: str,
    strategy: str,
    direction: str,       # "LONG" or "SHORT"
    price: float,
    quantity: int,
    pnl: Optional[float] = None,
    exit_reason: Optional[str] = None
)

send_position_update(
    symbol: str,
    unrealized_pnl: float,
    strategy: str
)

send_daily_summary(
    total_pnl: float,
    trades_count: int,
    win_rate: float
)

send_system_status(
    message: str,
    priority: int = 3
)
```

**Usage**:
```bash
# Test alerts
curl -d "Test message" ntfy.sh/jacobw-trading-alerts

# Subscribe on phone
# https://ntfy.sh/jacobw-trading-alerts
# https://ntfy.sh/jacobw-trading-status
# https://ntfy.sh/jacobw-trading-trades
```

---

## 6. PROCESS FLOWS

### 6.1 System Startup Flow

```
1. VPN Connection (nordvpnd.service - boot)
   ↓
2. IBKR Gateway (manual start or ibkr-gateway.service)
   ├→ Start gateway: cd /home/jacobw/quantstack/cpapi/gateway && bin/run.sh root/conf.yaml
   ├→ Browser login: firefox https://localhost:5000
   └→ Verify authentication
   ↓
3. IBKR API Platform (ibkr-platform.service - enabled)
   ├→ python3 -m cpapi.platform
   ├→ Listen on port 8000
   └→ Connect to Gateway (port 5000)
   ↓
4. L2 Collector (l2-collector.service - enabled, auto-start)
   ├→ Register with platform
   ├→ Load SIP symbols
   └→ Start collection
   ↓
5. L2 Watchdog (l2-watchdog.service - enabled)
   ├→ Monitor collector health
   └→ Auto-restart on failure
```

---

### 6.2 Daily Trading Flow

**Pre-Market (07:00 ET)**:
```
preflight-check.timer
  ↓
scripts/preflight_check.py
  ├→ Check IBKR Gateway connectivity
  ├→ Validate Polygon API
  ├→ Check service status
  └→ Send NTFY status
```

**Orchestrator (08:00 ET)**:
```
trading-orchestrator.timer
  ↓
bulletproof_orchestrator.py
  ├→ multi_session_sip_generator.py
  │   ├→ Polygon API (1796 symbols)
  │   ├→ Apply filters (price, volume, score)
  │   ├→ Rank by score
  │   └→ Output ~4-20 symbols
  ├→ Gateway health checks
  ├→ Service monitoring
  └→ Send NTFY summary
```

**SIP Generation (09:10 ET)**:
```
intraday-sip.timer
  ↓
scripts/generate_daily_sip.sh
  ↓
scripts/generate_daily_sip_universe.py
  ├→ Load 1796 NYSE symbols
  ├→ Fetch Polygon data
  ├→ Apply filters:
  │   - Price: $2 - $200
  │   - DV: >$5M
  │   - Score: >0.70
  ├→ Score and rank
  ├→ Select top 4-20
  └→ Write to data/daily_sip/
```

**Trading (09:30 ET - 16:00 ET)**:

*L2 Scalping*:
```
l2-scalping.service (manual start)
  ↓
start_scalping.sh → src/main.py
  ↓
Load config (strategy.yaml, risk.yaml, ibkr.yaml)
  ↓
Register with platform (l2_scalping)
  ↓
Load SIP symbols (data.sip_integration)
  ↓
L2DataFeed.subscribe()
  ↓
Main loop:
  ├→ Receive L2 snapshot
  ├→ Compute 32 features
  ├→ Generate signals:
  │   - OBI momentum rule
  │   - Pattern rule 1 (OBI + depth)
  │   - Pattern rule 2 (Bid depth + OBI change)
  │   - Pattern rule 3 (High OBI + depth)
  ├→ Apply context filters:
  │   - Block vol expansion
  │   - Block BB squeeze
  ├→ Validate signals
  ├→ Risk checks
  ├→ Place order via platform
  ├→ Track positions
  ├→ Exit logic (target/stop/time)
  ├→ Log trade
  └→ Send NTFY notification
```

*Intraday Paper*:
```
intraday-paper.service (manual start)
  ↓
start_paper_trading.sh
  ↓
Preflight check
  ↓
paper_trade_platform.py
  ↓
Load SIP universe
  ↓
Register with platform (intraday_paper)
  ↓
Main loop:
  ├→ Scan universe for signals
  ├→ Generate candidates
  ├→ Validate entries
  ├→ Place paper orders
  ├→ Track positions
  ├→ Exit logic
  ├→ Log to SQLite
  └→ Send NTFY notification
```

**Monitoring (Every 5 min)**:
```
system-health-monitor.timer
  ↓
system_health_monitor.py
  ├→ Check platform health (HTTP)
  ├→ Check authentication
  ├→ Check critical services (systemctl)
  ├→ Scan journalctl for CRITICAL
  ├→ Detect service recovery
  └→ Send NTFY alerts
```

---

### 6.3 Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    EXTERNAL DATA SOURCES                    │
├─────────────────────────────────────────────────────────────┤
│  NordVPN → IBKR Gateway (5000) → IBKR API Platform (8000)  │
│  Polygon API → SIP Generation                              │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  DATA COLLECTION LAYER                      │
├─────────────────────────────────────────────────────────────┤
│  L2 Collector → L2 Snapshots → 32 Features → Parquet       │
├─────────────────────────────────────────────────────────────┤
│  SIP Generator → 1796 Symbols → Filters → 4-20 Qualified   │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    DATA STORAGE LAYER                       │
├─────────────────────────────────────────────────────────────┤
│  /data/l2_maximum/features/ → Parquet files (L2 data)      │
│  /data/daily_sip/ → JSON files (SIP universe)              │
│  /data/journal/events.db → SQLite (trade journal)          │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                   TRADING LAYER                             │
├─────────────────────────────────────────────────────────────┤
│  L2 Scalping → L2 Signals → Orders → P&L → NTFY           │
│  Intraday Paper → Reversal → Orders → P&L → NTFY          │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                  MONITORING LAYER                           │
├─────────────────────────────────────────────────────────────┤
│  Health Monitor → Platform health → Service status → NTFY  │
│  L2 Watchdog → Collector health → Auto-restart → NTFY      │
└─────────────────────────────────────────────────────────────┘
```

---

## 7. FILE INVENTORY SUMMARY

### 7.1 Systemd Units (Complete)

**Services**: 15 units
```
/usr/lib/systemd/system/
├── nordvpnd.service              # VPN
└── nordvpnd.socket

/etc/systemd/system/
├── xvfb.service                  # Virtual display
├── ibkr-gateway.service          # IBKR Gateway
├── gateway-manager.service       # Gateway monitor
├── ibkr-platform.service         # API Platform
├── l2-collector.service          # L2 collection
├── l2-watchdog.service           # L2 watchdog
├── l2-scalping.service           # L2 scalping
├── intraday-paper.service        # Paper trading
├── intraday-sip.service          # SIP generation
├── preflight-check.service       # Pre-market check
├── trading-orchestrator.service  # Orchestrator
├── system-health-monitor.service # Health monitor
└── emergency-eod-close.service   # Emergency close
```

**Timers**: 8 units
```
/etc/systemd/system/
├── system-health-monitor.timer
├── preflight-check.timer
├── trading-orchestrator.timer
├── intraday-sip.timer
├── l2-collector.timer
├── l2-scalping.timer
├── intraday-paper.timer
└── emergency-eod-close.timer
```

**Drop-ins**: 5 directories
```
/etc/systemd/system/
├── ibkr-gateway.service.d/
│   └── resilience.conf
├── l2-collector.service.d/
│   └── alerts.conf
├── l2-scalping.service.d/
│   └── alerts.conf
└── intraday-paper.service.d/
    ├── alerts.conf
    └── override.conf
```

---

### 7.2 Python Scripts (Core)

**Platform**:
```
/home/jacobw/quantstack/cpapi/
├── platform.py                   # FastAPI server (11844 bytes)
├── platform_client.py            # HTTP client (10195 bytes)
├── client.py                     # CPAPI wrapper (11434 bytes)
├── trading_notifications.py      # NTFY module (4615 bytes)
├── check_gateway.py              # Health checks (1276 bytes)
├── test_platform.py              # Platform tests (1752 bytes)
└── test_cpapi_connections.py     # Connection tests (5589 bytes)
```

**L2 Collector**:
```
/home/jacobw/quantstack/qx-l2/src/qx_l2/
├── cli.py                        # CLI entry
├── collector.py                  # Collection logic
├── features.py                   # Feature engineering
├── symbols.py                    # Symbol management
├── storage.py                    # Parquet storage
├── journal.py                    # Collection journal
├── scheduler.py                  # Market scheduler
└── config.py                     # Config loader
```

**L2 Scalping**:
```
/home/jacobw/quantstack/l2_scalping/src/
├── main.py                       # Trading loop
├── data/l2_feed.py               # L2 feed
├── data/sip_integration.py       # SIP loader
├── execution/order_manager.py    # Order execution
├── signals/l2_signals.py         # OBI signals
├── signals/context_filter.py     # Context filter
├── signals/pattern_rules.py      # Pattern rules
├── risk/risk_manager.py          # Risk management
└── reporting/trade_journal.py    # Trade logging
```

**Intraday Paper**:
```
/home/jacobw/intraday_stack/
├── scripts/paper_trade_platform.py
├── scripts/generate_daily_sip_universe.py
├── scripts/refresh_sip.py
├── scripts/ibkr_preflight.py
├── src/journal/event_store.py
├── src/notifications/ntfy_notifier.py
└── src/signals/candidate_generator.py
```

**Orchestration**:
```
/home/jacobw/quantstack/
├── bulletproof_orchestrator.py
├── trading_orchestrator.py
└── scripts/preflight_check.py
```

**Monitoring**:
```
/home/jacobw/quantstack/
├── system_health_monitor.py
└── scripts/l2_watchdog.py
```

---

### 7.3 Configuration Files (Complete)

**Platform**:
```
/home/jacobw/quantstack/cpapi/
└── gateway/root/conf.yaml         # Gateway config
```

**L2 Collector**:
```
/home/jacobw/quantstack/qx-l2/
└── configs/maximum_l2.yaml
```

**L2 Scalping**:
```
/home/jacobw/quantstack/l2_scalping/config/
├── strategy.yaml
├── risk.yaml
└── ibkr.yaml
```

**Systemd**:
```
/etc/systemd/system/
└── polygon.env                    # Polygon API key
```

---

### 7.4 Data Locations (Complete)

**L2 Data**:
```
/home/jacobw/quantstack/data/l2_maximum/features/
└── date=YYYY-MM-DD/
    └── symbol={TICKER}/
        └── {TIMESTAMP}.parquet
```

**SIP Universe**:
```
/home/jacobw/intraday_stack/data/daily_sip/
└── date=YYYY-MM-DD/
    └── sip_universe.json

/home/jacobw/quantstack/data/daily_sip/
└── sip_universe_YYYY-MM-DD.txt   # Legacy format
```

**Trade Journal**:
```
/home/jacobw/intraday_stack/data/journal/events.db
```

**Logs**:
```
/home/jacobw/quantstack/logs/
├── orchestrator.log
└── orchestrator_audit.log

/home/jacobw/quantstack/l2_scalping/logs/
└── scalping_system.log

/home/jacobw/intraday_stack/logs/
├── paper_YYYYMMDD.log
└── sip_generation_YYYYMMDD.log

journalctl -u [service-name]
```

---

## 8. EXTERNAL DEPENDENCIES

### 8.1 IBKR Gateway
- **Location**: `/home/jacobw/quantstack/cpapi/gateway/`
- **Port**: 5000 (HTTPS)
- **Download**: IBKR Client Portal Gateway
- **Authentication**: Browser-based (2FA required)

### 8.2 Polygon API
- **Endpoint**: `https://api.polygon.io`
- **API Key**: `ZBxeJYOn0_e0UcPgEYLA90CQ9S28_EfU`
- **Usage**: SIP generation, historical data

### 8.3 NTFY
- **Endpoint**: `https://ntfy.sh`
- **Channels**: 3 channels for alerts, status, trades

### 8.4 NordVPN
- **Service**: `nordvpnd.service`
- **Purpose**: Secure connection to IBKR

---

## 9. SYSTEM STATISTICS

**Services**: 15 total
- Infrastructure: 3 (VPN, Gateway, Platform)
- Data Collection: 2 (L2 collector, Watchdog)
- Trading: 2 (L2 scalping, Intraday paper)
- Scheduling: 5 (Preflight, Orchestrator, SIP, Health, EOD)
- Support: 3 (Gateway manager, Xvfb, Emergency)

**Timers**: 8 total
- Automated: 4 (Preflight, Orchestrator, SIP, Health)
- Manual: 4 (L2 collector, L2 scalping, Paper, EOD)

**Python Scripts**: 50+ core scripts
**Configuration Files**: 15+ YAML/config files
**Data Locations**: 5 main directories
**Log Locations**: 4 main directories
**NTFY Channels**: 3 channels
**IBKR Accounts**: 1 (DUN575068)
**SIP Symbols Tested**: 1,796
**SIP Symbols Qualified**: ~4-20 daily
**L2 Features**: 32 per snapshot
**Max Concurrent L2**: 3 symbols

---

**Last Updated**: 2026-01-13
**Version**: 3.0
**Architecture**: Platform-Based (REST API)

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

