# Repository Migration Analysis
**Date**: 2026-02-03  
**Purpose**: Analyze systemd_map findings and prepare for clean repo migration

## Executive Summary

Analyzed complete system map to identify retired services, zombie processes, and missing files before migrating to new properly-organized repository.

**Key Findings**:
- ✅ l2-collector: Properly retired (integrated into l2-scalping)
- ⚠️ l2-watchdog: Zombie service (5700+ failed restarts) - needs immediate disable
- ✅ paper_trading.yaml: Found (systemd map was incorrect)
- ℹ️ intraday-paper.env: Not needed (env vars in systemd units)

## Critical Issue: Zombie l2-watchdog Service

**Problem**: l2-watchdog.service is enabled but script is missing, causing infinite restart loop.

**Evidence**:
```
Feb 03 11:33:23 systemd[1]: l2-watchdog.service: Scheduled restart job, restart counter is at 5756.
Feb 03 11:33:23 python[1333992]: can't open file '/home/jacobw/quantstack/scripts/l2_watchdog.py': [Errno 2] No such file or directory
```

**Root Cause**: 
- l2-watchdog monitored l2-collector service
- l2-collector was retired (L2 collection moved into l2-scalping)
- l2-watchdog script moved to archive but service not disabled

**Immediate Action Required**:
```bash
sudo systemctl stop l2-watchdog.service
sudo systemctl disable l2-watchdog.service
sudo rm /etc/systemd/system/l2-watchdog.service
sudo systemctl daemon-reload
```

## Service Status Summary

| Service | Status | Action for New Repo |
|---------|--------|---------------------|
| intraday-sip | ✅ Active | Copy |
| intraday-paper | ✅ Active | Copy |
| l2-scalping | ✅ Active | Copy |
| l2-vwap-reversion | ✅ Active | Copy |
| l2-health-monitor | ✅ Active | Copy |
| daily-trade-report | ✅ Active | Copy |
| l2-collector | ❌ Retired | Exclude |
| l2-watchdog | ❌ Zombie | Exclude |

## File Verification Results

### 1. paper_trading.yaml
- **Systemd Map**: Marked as "NEEDS CONFIRMATION - not found"
- **Actual Status**: ✅ EXISTS at `/home/jacobw/intraday_stack/configs/paper_trading.yaml`
- **Action**: Update systemd map

### 2. intraday-paper.env
- **Systemd Map**: Referenced in systemd unit
- **Actual Status**: ❌ Missing (never existed)
- **Impact**: None - environment variables set directly in systemd unit files
- **Action**: Document that separate .env file not used

### 3. l2_watchdog.py
- **Systemd Map**: Referenced in ExecStart
- **Actual Status**: ❌ Missing (moved to `archive/cleanup_20260120/scripts/`)
- **Impact**: High - causing zombie service
- **Action**: Disable service

### 4. l2-collector.service
- **Systemd Map**: Referenced
- **Actual Status**: ❌ Retired (moved to `archive/l2-collector-deprecated/`)
- **Impact**: None - properly retired
- **Action**: Remove from new repo

## Architecture Issues Identified

### Issue 1: Mixed Systemd Locations

**Current State**:
- Global (`/etc/systemd/system/`): intraday-sip, intraday-paper, l2-health-monitor, l2-watchdog, daily-trade-report, stop timers
- User (`~/.config/systemd/user/`): l2-scalping, l2-vwap-reversion

**Problems**:
- Inconsistent management (some need sudo, some don't)
- Confusion about which systemctl command to use
- Different permission models

**Recommendation**: Consolidate ALL services to user systemd in new repo

### Issue 2: Scattered File Organization

**Current State**:
- Services mixed with shared libraries
- Configs in multiple locations
- Scripts scattered across directories
- No clear service boundaries

**Recommendation**: Service-based directory structure (see below)

## Recommended New Repo Structure

```
quantstack-v2/
├── services/
│   ├── intraday-sip/
│   │   ├── scripts/
│   │   │   ├── generate_daily_sip.sh
│   │   │   └── generate_daily_sip_universe.py
│   │   ├── systemd/
│   │   │   ├── intraday-sip.service
│   │   │   └── intraday-sip.timer
│   │   └── README.md
│   │
│   ├── intraday-paper/
│   │   ├── src/                    # All intraday_stack/src modules
│   │   ├── scripts/
│   │   │   ├── start_paper_trading.sh
│   │   │   ├── paper_trade.py
│   │   │   └── ibkr_preflight.py
│   │   ├── configs/
│   │   │   └── paper_trading.yaml
│   │   ├── systemd/
│   │   │   ├── intraday-paper.service
│   │   │   ├── intraday-paper.timer
│   │   │   └── intraday-paper-stop.timer
│   │   └── README.md
│   │
│   ├── l2-scalping/
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── position_manager.py
│   │   │   ├── order_tracker.py
│   │   │   ├── fill_processor.py
│   │   │   ├── scheduler.py
│   │   │   ├── data/
│   │   │   ├── execution/
│   │   │   ├── signals/
│   │   │   ├── risk/
│   │   │   └── reporting/
│   │   ├── config/
│   │   │   ├── strategy.yaml
│   │   │   └── ibkr.yaml
│   │   ├── systemd/
│   │   │   ├── l2-scalping.service
│   │   │   └── l2-scalping-stop.timer
│   │   └── README.md
│   │
│   ├── l2-vwap-reversion/
│   │   ├── src/
│   │   │   ├── main.py
│   │   │   ├── strategy.py
│   │   │   ├── l2_filter.py
│   │   │   ├── vwap.py
│   │   │   ├── data/
│   │   │   ├── execution/
│   │   │   └── reporting/
│   │   ├── config/
│   │   │   ├── strategy.yaml
│   │   │   └── ibkr.yaml
│   │   ├── systemd/
│   │   │   ├── l2-vwap-reversion.service
│   │   │   ├── l2-vwap-reversion.timer
│   │   │   └── l2-vwap-reversion-stop.timer
│   │   └── README.md
│   │
│   └── monitoring/
│       ├── l2-health-monitor/
│       │   ├── l2_health_monitor.py
│       │   ├── clear_ibkr_depth_subscriptions.py
│       │   ├── systemd/
│       │   │   └── l2-health-monitor.service
│       │   └── README.md
│       │
│       └── daily-trade-report/
│           ├── daily_trade_report.py
│           ├── fill_truth_report.py
│           ├── systemd/
│           │   ├── daily-trade-report.service
│           │   └── daily-trade-report.timer
│           └── README.md
│
├── shared/
│   ├── qx-broker/              # IBKR integration
│   ├── qx-l2/                  # L2 data handling
│   ├── cpapi/                  # Trade DB, audit, client ID
│   └── configs/
│       ├── ibkr_gateway.yaml
│       └── polygon_sip_config.yaml
│
├── scripts/
│   ├── audit_wrapper.sh
│   ├── reconcile_trades.py
│   ├── preflight_check.py
│   ├── market_open_health_check.py
│   ├── emergency_eod_close.py
│   ├── close_all_positions.py
│   ├── query_audit.py
│   └── ibkr/
│       ├── start_ibkr_gateway.sh
│       └── wait_for_ibkr_gateway.sh
│
├── data/
│   ├── daily_sip/              # SIP universe parquet files
│   ├── l2/                     # L2 data storage
│   └── journal/                # Trade journals
│
├── logs/
│   ├── audit/                  # Audit logs
│   ├── services/               # Service-specific logs
│   └── reconciliation/         # Trade reconciliation reports
│
├── docs/
│   ├── README.md
│   ├── ARCHITECTURE.md
│   ├── SYSTEM_GUIDE.md
│   ├── DEPLOYMENT.md
│   ├── TRADE_RECONCILIATION.md
│   ├── AUDIT_LOGGING.md
│   └── TROUBLESHOOTING.md
│
├── install/
│   ├── setup.sh                # Main installation script
│   ├── systemd_install.sh      # Install all systemd units
│   ├── requirements.txt
│   └── README.md
│
└── tests/
    ├── integration/
    └── unit/
```

## Migration Checklist

### Phase 1: Cleanup Current System
- [ ] Disable l2-watchdog service
- [ ] Remove l2-watchdog systemd unit
- [ ] Verify l2-collector fully retired
- [ ] Document current working state

### Phase 2: Prepare New Repo
- [ ] Create new repo structure
- [ ] Copy active services only
- [ ] Consolidate systemd units to user location
- [ ] Update all paths in systemd units
- [ ] Create installation scripts

### Phase 3: Migrate Shared Dependencies
- [ ] Copy qx-broker with proper package structure
- [ ] Copy qx-l2 with proper package structure
- [ ] Copy cpapi with proper package structure
- [ ] Update import paths in all services

### Phase 4: Testing
- [ ] Test each service independently
- [ ] Test systemd timer scheduling
- [ ] Test service dependencies
- [ ] Test stop timers
- [ ] Test audit logging
- [ ] Test trade reconciliation

### Phase 5: Documentation
- [ ] Update SYSTEM_GUIDE.md
- [ ] Create DEPLOYMENT.md
- [ ] Document installation process
- [ ] Document service management
- [ ] Create troubleshooting guide

## Benefits of New Structure

1. **Clear Service Boundaries**: Each service self-contained with code, configs, systemd units
2. **Consistent Management**: All user systemd, no sudo required
3. **Easy Installation**: Automated scripts for setup
4. **Better Testing**: Service isolation enables independent testing
5. **Clean Dependencies**: Explicit shared/ directory
6. **No Legacy Code**: Retired services excluded
7. **Proper Documentation**: Service-level READMEs + system docs

## Next Steps

1. **Immediate**: Disable l2-watchdog zombie service
2. **Short-term**: Create new repo structure and begin migration
3. **Medium-term**: Test migrated services in parallel with current system
4. **Long-term**: Cutover to new repo, archive old quantstack

## References

- systemd_map.md - Complete system inventory
- SYSTEM_GUIDE.md - Current system documentation
- AGENTS.md - Development guidelines
