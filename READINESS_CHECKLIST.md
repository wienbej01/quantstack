# System Readiness Checklist - 2026-01-09

## Pre-Market Checklist (Today)

### 20:00 Manila (7:00 AM ET) - Pre-Flight Check
- [ ] Automated pre-flight validation runs
- [ ] Check for NTFY alerts (only sent on failure)
- [ ] If alerts received, investigate immediately

### 20:30 Manila (7:30 AM ET) - Manual Gateway Start
- [ ] Start IBKR Gateway manually
- [ ] Verify connection on port 7497: `nc -zv 127.0.0.1 7497`
- [ ] Check Gateway logs for any errors

### 21:00 Manila (8:00 AM ET) - Orchestrator Run
- [ ] Trading orchestrator runs automatically
- [ ] Generates SIP universe for today
- [ ] Check NTFY for status updates
- [ ] Verify SIP file created with ~20 symbols

### 22:25 Manila (9:25 AM ET) - Services Start
- [ ] L2 collector starts automatically
- [ ] Intraday paper trading starts
- [ ] L2 scalping waits for market open (22:30)

### 22:30 Manila (9:30 AM ET) - Market Open
- [ ] Monitor first 15 minutes of trading
- [ ] Check service logs for any errors
- [ ] Verify trades are being attempted

## System Status (Current)

### Services Running ✅
- l2-collector: active
- l2-scalping: active (waiting for market hours)
- l2-watchdog: active

### Timers Active ✅
- preflight-check.timer: 20:00 Manila
- trading-orchestrator.timer: 21:00 Manila
- l2-collector.timer: 22:25 Manila
- intraday-paper.timer: 22:25 Manila
- system-health-monitor.timer: Every 5min (market hours only)

### Data Ready ✅
- SIP universe: 235 symbols from 2026-01-08
- L2 data: 90,837 records from yesterday
- Config files: All valid YAML
- API access: Polygon ✅, NTFY ✅

### Tests Passed ✅
- Definitive E2E test: 47/47 tests passed
- Component validation: All imports and signatures work
- No mock data in production code
- All method calls validated

## Manual Commands

```bash
# Check all services
systemctl status l2-collector l2-scalping l2-watchdog

# Check timers
systemctl list-timers | grep -E "(preflight|trading|l2|intraday)"

# Run pre-flight manually
python scripts/preflight_check.py

# Run comprehensive test
python scripts/definitive_e2e_test.py

# Check IBKR Gateway
nc -zv 127.0.0.1 7497

# View orchestrator logs
tail -f logs/orchestrator.log

# View l2-scalping logs
journalctl -u l2-scalping -f
```

## NTFY Channels

- `jacobw-trading-alerts`: Failures and issues only
- `jacobw-trading-status`: Orchestrator status updates
- `jacobw-trading-data`: Data collection updates
- `jacobw-trading-trades`: Trade executions

## Emergency Contacts

If system fails during market hours:
1. Check NTFY alerts for specific error
2. Check service status: `systemctl status l2-scalping`
3. Check logs: `journalctl -u l2-scalping -n 50`
4. Restart if needed: `sudo systemctl restart l2-scalping`

## Success Criteria

- [ ] Pre-flight passes at 20:00 Manila
- [ ] SIP generated at 21:00 Manila
- [ ] Services start at 22:25 Manila
- [ ] First trade attempted by 22:35 Manila
- [ ] No critical NTFY alerts during session
