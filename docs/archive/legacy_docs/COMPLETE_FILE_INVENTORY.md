# Complete File Inventory - Trading System

## Active System Files (Production Code Only)

### Quantstack Core System

**Orchestration & Monitoring**
- `bulletproof_orchestrator.py` - SIP generation orchestrator
- `trading_orchestrator.py` - Legacy orchestrator (backup)
- `system_health_monitor.py` - Health monitoring service
- `scripts/preflight_check.py` - Pre-market validation
- `scripts/l2_watchdog.py` - L2 collector watchdog
- `scripts/trading_report.py` - Trade performance reports

**L2 Scalping System**
- `l2_scalping/src/main.py` - Main entry point
- `l2_scalping/src/execution/order_manager.py` - Order execution & reconnection
- `l2_scalping/src/data/l2_feed.py` - L2 data feed subscription
- `l2_scalping/src/data/sip_integration.py` - SIP universe loading
- `l2_scalping/src/signals/l2_signals.py` - L2 signal generation
- `l2_scalping/src/signals/context_filter.py` - Signal filtering
- `l2_scalping/src/risk/risk_manager.py` - Risk management
- `l2_scalping/src/scheduler.py` - Trading scheduler
- `l2_scalping/src/reporting/performance_reporter.py` - Performance reporting
- `l2_scalping/src/reporting/trade_journal.py` - Trade logging
- `l2_scalping/config/strategy.yaml` - Strategy configuration
- `l2_scalping/config/risk.yaml` - Risk configuration

**L2 Collection (qx-l2)**
- `qx-l2/src/qx_l2/cli.py` - CLI interface
- `qx-l2/src/qx_l2/collector.py` - L2 collection logic
- `qx-l2/src/qx_l2/config.py` - Configuration management
- `qx-l2/src/qx_l2/features.py` - Feature engineering (32 features)
- `qx-l2/src/qx_l2/journal.py` - Collection metadata
- `qx-l2/src/qx_l2/scheduler.py` - Collection scheduling
- `qx-l2/src/qx_l2/storage.py` - Parquet storage
- `qx-l2/src/qx_l2/symbols.py` - Symbol management
- `qx-l2/configs/maximum_l2.yaml` - L2 configuration

**SIP Generation**
- `multi_session_sip_generator.py` - Multi-session SIP generation
- `scripts/generate_daily_sip_universe.py` - Daily SIP generation

---

### Intraday Stack (Paper Trading)

**Main Trading System**
- `scripts/paper_trade.py` - Main trading loop
- `scripts/refresh_sip.py` - SIP refresh service
- `scripts/start_paper_trading.sh` - Service startup script

**Core Modules**
- `src/journal/event_store.py` - Trade journal (SQLite)
- `src/notifications/ntfy_notifier.py` - NTFY notifications
- `src/universe/polygon_sip_universe.py` - SIP universe loading
- `src/signals/candidate_generator.py` - Signal generation
- `src/execution/ibkr_live_adapter.py` - IBKR adapter
- `src/execution/order_manager.py` - Order execution
- `src/execution/exits.py` - Exit logic
- `src/marketdata/ibkr_client.py` - IBKR market data
- `src/marketdata/ibkr_bars_1m.py` - 1-minute bars
- `src/marketdata/ibkr_quotes.py` - Quote streaming
- `src/risk/position_sizing.py` - Position sizing
- `src/risk/daily_risk_manager.py` - Daily risk management
- `src/risk/cost_gates.py` - Cost filtering
- `src/decision/cost_adjusted_ranker.py` - Trade ranking
- `src/strategies/reversal_entry.py` - Reversal strategy
- `src/strategies/exit_manager.py` - Exit management
- `src/reporting/daily_paper_report.py` - Daily reporting
- `src/integration/paper_trading_orchestrator.py` - Orchestration
- `src/configuration/loader.py` - Configuration loading

**Utilities**
- `src/utils/time.py` - Time utilities
- `src/utils/rolling.py` - Rolling window utilities
- `src/features/intraday_features.py` - Feature engineering
- `src/indicators/technical.py` - Technical indicators

---

### Configuration Files

**Quantstack**
- `l2_scalping/config/strategy.yaml` - L2 scalping strategy config
- `l2_scalping/config/risk.yaml` - L2 scalping risk config
- `qx-l2/configs/maximum_l2.yaml` - L2 collection config

**Intraday Stack**
- (Configs embedded in Python, no separate YAML files)

---

### Systemd Services & Timers

**Service Files** (in `/etc/systemd/system/`)
- `trading-orchestrator.service` - SIP generation service
- `trading-orchestrator.timer` - SIP generation timer (21:00 Manila)
- `preflight-check.service` - Pre-flight validation service
- `preflight-check.timer` - Pre-flight timer (20:00 Manila)
- `l2-collector.service` - L2 collection service
- `l2-collector.timer` - L2 collection timer (22:25 Manila)
- `l2-scalping.service` - L2 scalping service
- `l2-watchdog.service` - L2 watchdog service
- `intraday-paper.service` - Paper trading service
- `intraday-paper.timer` - Paper trading timer (22:25 Manila)
- `intraday-sip.service` - SIP refresh service
- `intraday-sip.timer` - SIP refresh timer (21:45 Manila)
- `system-health-monitor.service` - Health monitor service
- `system-health-monitor.timer` - Health monitor timer (every 5 min)
- `polygon.env` - Polygon API key environment

---

### Data Storage Locations

**SIP Universe**
- `/home/jacobw/intraday_stack/data/daily_sip/date=YYYY-MM-DD/sip_universe.json`

**L2 Features**
- `/home/jacobw/quantstack/data/l2_maximum/features/date=YYYY-MM-DD/symbol=XXX/*.parquet`

**Trade Journal**
- `/home/jacobw/intraday_stack/data/journal/events.db` (SQLite)

**Service Logs**
- `/home/jacobw/quantstack/logs/orchestrator.log`
- `/home/jacobw/quantstack/logs/orchestrator_audit.log`
- `/home/jacobw/intraday_stack/logs/paper_YYYYMMDD.log`
- `/home/jacobw/intraday_stack/logs/sip.log`

---

## File Statistics

| Category | Count |
|----------|-------|
| Quantstack system files | 45 |
| Intraday stack system files | 35 |
| Configuration files | 3 |
| Systemd services/timers | 14 |
| **Total active system files** | **97** |

---

## Critical Dependencies

### Python Packages
- `ib_insync` - IBKR API
- `pandas` - Data processing
- `numpy` - Numerical computing
- `requests` - HTTP client
- `pytz` - Timezone handling
- `sqlalchemy` - ORM
- `pydantic` - Data validation
- `pyarrow` - Parquet I/O

### External Services
- IBKR Gateway (127.0.0.1:7497)
- Polygon API (https://api.polygon.io)
- NTFY (https://ntfy.sh)
- GCS Mount (/home/jacobw/gcs-mount/gold/stocks/1m/)

### System Dependencies
- Python 3.11+
- Systemd
- SQLite3
- Bash

---

## Entry Points by Service

| Service | Entry Point | Type |
|---------|------------|------|
| trading-orchestrator | `bulletproof_orchestrator.py` | Python |
| preflight-check | `scripts/preflight_check.py` | Python |
| l2-collector | `/home/jacobw/.local/bin/l2-collect` | Binary (qx-l2) |
| l2-scalping | `l2_scalping/src/main.py` | Python |
| l2-watchdog | `scripts/l2_watchdog.py` | Python |
| intraday-paper | `scripts/start_paper_trading.sh` | Bash |
| intraday-sip | `scripts/refresh_sip.py` | Python |
| system-health-monitor | `system_health_monitor.py` | Python |

---

## Module Dependency Graph

```
trading-orchestrator
├── multi_session_sip_generator.py
│   ├── Polygon API
│   └── Gold data directory
├── IBKR Gateway (health check)
└── NTFY notifications

l2-collector (qx-l2)
├── IBKR Gateway (client 521)
├── SIP universe (daily_sip/sip_universe.json)
├── Feature engineering (32 features)
└── Parquet storage

l2-scalping
├── IBKR Gateway (clients 10, 11)
├── SIP universe (daily_sip/sip_universe.json)
├── L2 signals (microstructure)
├── Risk management
├── Order execution
└── Trade journal

intraday-paper
├── IBKR Gateway (client 15)
├── SIP universe (daily_sip/sip_universe.json)
├── Polygon API (historical bars)
├── Signal generation (reversal)
├── Risk management
├── Order execution
├── Trade journal (SQLite)
└── NTFY notifications

system-health-monitor
├── Systemd services (is-active)
├── Journalctl logs (CRITICAL errors)
├── IBKR Gateway (connectivity)
└── NTFY alerts
```

---

## Total System Scope

- **97 active system files** (production code only)
- **8 systemd services** (orchestration & execution)
- **8 systemd timers** (scheduling)
- **3 configuration files** (YAML)
- **1 environment file** (API keys)
- **1 SQLite database** (trade journal)
- **1 JSON artifact** (daily SIP universe)
- **Parquet storage** (L2 features)

