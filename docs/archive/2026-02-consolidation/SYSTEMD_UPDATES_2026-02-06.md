# Systemd Configuration Updates - 2026-02-06

## Changes Implemented

### 1. L2 VWAP Reversion Service Standardization
- **Created**: `/home/jacobw/quantstack/l2_vwap_reversion/start_vwap_reversion.sh`
  - Market hours validation (09:20-16:00 ET)
  - SIP dependency check
  - IBKR Gateway readiness gate (waits for `IBKR_GATEWAY_PORT`, default `7494`; exits non-zero if not ready so systemd retries)
  - Consistent with l2-scalping and intraday-paper patterns

- **Updated**: `/etc/systemd/system/l2-vwap-reversion.service`
  - Added audit wrapper: `audit_wrapper.sh l2-vwap-reversion`
  - Uses startup script instead of direct Python execution
  - Added TZ=America/New_York environment variable
  - Maintains resource limits and security hardening

### 2. Intraday Paper Service Hardening
- **Updated**: `/etc/systemd/system/intraday-paper.service`
  - Added resource limits: `MemoryMax=1G`, `CPUQuota=50%`
  - Added security hardening: `NoNewPrivileges=true`, `PrivateTmp=true`
  - Changed restart policy: `Restart=on-failure` (was `no`)
  - Added `RestartSec=30` for consistent behavior

### 3. Timer Cleanup
- **Removed**: `/etc/systemd/system/l2-vwap-reversion.timer` (duplicate)
- **Kept**: `~/.config/systemd/user/l2-vwap-reversion.timer` (09:20 ET)
- **Result**: Single timer at 09:20 ET (user-level), no conflicts

### 4. Backups Created
- `/etc/systemd/system/l2-vwap-reversion.service.backup`
- `/etc/systemd/system/intraday-paper.service.backup`

### 5. Boot-Time Startup Disabled
- **Disabled**: `position-monitor.service`, `l2-scalping.service`, `l2-health-monitor.service`
- **Reason**: Prevents 5-minute timeout failures when IBKR Gateway is not running at boot
- **Impact**: Services still start via timers during market hours (no functional change)
- **Fixes**: Boot/shutdown error messages about failed dependencies

## Service Configuration Summary

| Service | Audit Wrapper | Startup Script | Market Hours | Resource Limits | Restart Policy |
|---------|---------------|----------------|--------------|-----------------|----------------|
| l2-scalping | ✅ | ✅ | ✅ (09:25) | ✅ | always |
| l2-vwap-reversion | ✅ | ✅ | ✅ (09:20) | ✅ | on-failure |
| intraday-paper | ✅ | ✅ | ✅ (09:27) | ✅ | on-failure |

## Timer Schedule (All times ET)

**Start Sequence:**
- 09:00 - preflight-check
- 09:10 - intraday-sip
- 09:20 - l2-vwap-reversion (user-level timer; do not `Requires=l2-scalping` at user-level to avoid double-starting scalping in two scopes)
- 09:28 - intraday-paper
- 09:40 - market-open-health-check

**Stop Sequence:**
- 15:55 - emergency-eod-close
- 17:00 - l2-vwap-reversion-stop
- 17:01 - l2-scalping-stop
- 17:02 - intraday-paper-stop
- 17:10 - daily-trade-report

## Verification Commands

```bash
# Check timer schedule
systemctl list-timers | grep -E "(l2-|intraday-)"
systemctl --user list-timers | grep l2-vwap

# Verify service configuration
systemctl cat l2-vwap-reversion.service
systemctl cat intraday-paper.service

# Test startup scripts
/home/jacobw/quantstack/l2_vwap_reversion/start_vwap_reversion.sh
```

## Notes

- All services now use consistent patterns: audit wrapper + startup script + market hours validation
- Resource limits prevent runaway processes (1GB RAM, 50% CPU per service)
- Security hardening applied uniformly across all trading services
- l2-vwap-reversion starts before l2-scalping timer (09:20 vs 09:26). Ensure l2-scalping starts exactly once (avoid both system and user scope running simultaneously).
- **Boot-time startup disabled**: Services only start via timers during market hours (prevents IBKR Gateway timeout failures on boot/shutdown)
