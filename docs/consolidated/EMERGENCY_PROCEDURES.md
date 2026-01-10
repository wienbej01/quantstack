# EMERGENCY PROCEDURES

**Version**: 2026-01-10  
**Critical Reference**: Keep accessible during trading hours

## Emergency Contacts & Alerts

### Immediate Alerts
- **NTFY Channel**: https://ntfy.sh/jacobw-trading-alerts
- **Phone Notifications**: Enabled via NTFY app
- **System Owner**: jacobw

### Alert Escalation
1. **Level 1**: NTFY notification
2. **Level 2**: System log entry
3. **Level 3**: Service shutdown (if critical)

## Emergency Scenarios

### 1. POSITIONS STUCK OPEN AT EOD

**Symptoms**: Open positions after 4:00 PM ET

**Immediate Actions**:
```bash
# 1. Check emergency EOD status
journalctl -u emergency-eod-close.service --since today

# 2. Manual position check
python3 -c "
from journal.event_store import EventStore
es = EventStore('/home/jacobw/intraday_stack/data/journal/events.db')
open_trades = es.get_open_trades()
print(f'OPEN POSITIONS: {len(open_trades)}')
for trade in open_trades:
    print(f'  {trade[\"symbol\"]} {trade[\"direction\"]} @ {trade[\"entry_price\"]:.2f}')
"

# 3. Force close all positions
python3 /home/jacobw/quantstack/close_open_positions.py

# 4. Verify closure
python3 -c "
from journal.event_store import EventStore
es = EventStore('/home/jacobw/intraday_stack/data/journal/events.db')
print(f'Remaining open: {len(es.get_open_trades())}')
"
```

**Root Causes**:
- IBKR Gateway disconnection during EOD flatten
- Primary EOD flatten failed
- Emergency backup system failed

**Prevention**: Dual-layer EOD system (implemented)

### 2. IBKR GATEWAY CONNECTION FAILURE

**Symptoms**: Services running but no trades, connection errors

**Immediate Actions**:
```bash
# 1. Check Gateway process
ps aux | grep -i gateway

# 2. Test connectivity
python3 /home/jacobw/quantstack/scripts/check_portal_status.py

# 3. Check for zombie connections
netstat -an | grep CLOSE_WAIT | wc -l

# 4. If >10 zombies, restart Gateway (manual)
# - Close IBKR Gateway application
# - Wait 30 seconds
# - Restart Gateway
# - Reconfigure API settings

# 5. Restart trading services
sudo systemctl restart l2-collector l2-scalping intraday-paper
```

**Root Causes**:
- Gateway API settings disabled
- Client ID conflicts
- Zombie connection accumulation
- Farm disconnects

**Prevention**: Connection protocol (implemented)

### 3. SYSTEM SERVICES DOWN

**Symptoms**: Services inactive, no trading activity

**Immediate Actions**:
```bash
# 1. Check service status
systemctl status l2-collector l2-scalping intraday-paper l2-watchdog

# 2. Check for failed services
systemctl --failed

# 3. View recent errors
journalctl --since "1 hour ago" | grep -E "ERROR|CRITICAL" | tail -10

# 4. Restart failed services
sudo systemctl restart <failed-service>

# 5. If all services failed, full restart
sudo systemctl restart l2-collector l2-scalping intraday-paper l2-watchdog
```

**Root Causes**:
- System resource exhaustion
- Configuration errors
- Dependency failures
- File permission issues

**Prevention**: Health monitoring (implemented)

### 4. RUNAWAY TRADING (EXCESSIVE ORDERS)

**Symptoms**: Unusual number of orders, rapid position changes

**Immediate Actions**:
```bash
# 1. STOP ALL TRADING IMMEDIATELY
sudo systemctl stop l2-scalping intraday-paper

# 2. Check recent trades
python3 /home/jacobw/quantstack/scripts/trading_report.py --date $(date +%F) | tail -20

# 3. Check current positions
python3 -c "
from journal.event_store import EventStore
es = EventStore('/home/jacobw/intraday_stack/data/journal/events.db')
open_trades = es.get_open_trades()
print(f'Current positions: {len(open_trades)}')
"

# 4. Cancel all pending orders via IBKR Gateway GUI

# 5. Close positions if needed
python3 /home/jacobw/quantstack/close_open_positions.py

# 6. Investigate root cause before restarting
journalctl -u l2-scalping -u intraday-paper --since "1 hour ago" | grep -E "ORDER|TRADE"
```

**Root Causes**:
- Logic errors in trading algorithms
- Stale price data causing repeated entries
- Risk management failures
- Configuration errors

**Prevention**: Position limits, order throttling

### 5. DATA CORRUPTION OR LOSS

**Symptoms**: Missing trade data, corrupted database, invalid P&L

**Immediate Actions**:
```bash
# 1. Stop all services to prevent further corruption
sudo systemctl stop l2-collector l2-scalping intraday-paper

# 2. Backup current database
cp /home/jacobw/intraday_stack/data/journal/events.db \
   /home/jacobw/intraday_stack/data/journal/events_backup_$(date +%Y%m%d_%H%M%S).db

# 3. Check database integrity
sqlite3 /home/jacobw/intraday_stack/data/journal/events.db "PRAGMA integrity_check;"

# 4. Check recent trades
sqlite3 /home/jacobw/intraday_stack/data/journal/events.db \
  "SELECT COUNT(*) FROM trades WHERE DATE(entry_time) = '$(date +%F)';"

# 5. If corruption detected, restore from backup
# (Manual process - identify last good backup)

# 6. Restart services only after data integrity confirmed
sudo systemctl start l2-collector l2-scalping intraday-paper
```

**Root Causes**:
- Disk space exhaustion
- Concurrent database access
- System crashes during writes
- File system errors

**Prevention**: Regular backups, integrity checks

### 6. SYSTEM RESOURCE EXHAUSTION

**Symptoms**: High CPU/memory usage, slow response, service failures

**Immediate Actions**:
```bash
# 1. Check system resources
top -n 1 | head -20
df -h
free -h

# 2. Identify resource hogs
ps aux --sort=-%cpu | head -10
ps aux --sort=-%mem | head -10

# 3. Check disk space
df -h /home/jacobw/quantstack/data/
df -h /home/jacobw/intraday_stack/data/

# 4. Clean up if needed
# - Archive old logs: journalctl --vacuum-time=7d
# - Remove old L2 data: find /home/jacobw/quantstack/data/l2_maximum/ -mtime +30 -delete
# - Clean temp files: rm -rf /tmp/*

# 5. Restart services if resources freed
sudo systemctl restart l2-collector l2-scalping intraday-paper
```

**Root Causes**:
- Memory leaks in trading applications
- Excessive log file growth
- L2 data accumulation
- System process issues

**Prevention**: Resource monitoring, cleanup automation

## Emergency Shutdown Procedures

### Graceful Shutdown
```bash
# 1. Stop new trading
sudo systemctl stop l2-scalping intraday-paper

# 2. Allow current trades to complete (wait 5 minutes)
sleep 300

# 3. Force close any remaining positions
python3 /home/jacobw/quantstack/close_open_positions.py

# 4. Stop data collection
sudo systemctl stop l2-collector l2-watchdog

# 5. Stop orchestration
sudo systemctl stop trading-orchestrator

# 6. Verify all services stopped
systemctl status l2-collector l2-scalping intraday-paper l2-watchdog trading-orchestrator
```

### Emergency Shutdown (Immediate)
```bash
# 1. STOP ALL SERVICES IMMEDIATELY
sudo systemctl stop l2-collector l2-scalping intraday-paper l2-watchdog trading-orchestrator

# 2. Force close positions
python3 /home/jacobw/quantstack/close_open_positions.py

# 3. Cancel all orders via IBKR Gateway GUI

# 4. Document incident
echo "Emergency shutdown at $(date): REASON" >> /home/jacobw/quantstack/logs/emergency.log
```

## Recovery Procedures

### System Recovery Checklist
```bash
# 1. Verify system health
python3 /home/jacobw/quantstack/scripts/definitive_e2e_test.py

# 2. Check IBKR Gateway connectivity
python3 /home/jacobw/quantstack/scripts/check_portal_status.py

# 3. Verify no open positions
python3 -c "
from journal.event_store import EventStore
es = EventStore('/home/jacobw/intraday_stack/data/journal/events.db')
print(f'Open positions: {len(es.get_open_trades())}')
"

# 4. Check SIP universe availability
cat /home/jacobw/intraday_stack/data/daily_sip/date=$(date +%F)/sip_universe.json | jq '.symbols | length'

# 5. Start services in order
sudo systemctl start trading-orchestrator
sleep 30
sudo systemctl start l2-collector
sleep 30
sudo systemctl start l2-watchdog
sleep 30
sudo systemctl start l2-scalping intraday-paper

# 6. Verify all services active
systemctl status l2-collector l2-scalping intraday-paper l2-watchdog trading-orchestrator
```

### Post-Incident Analysis
```bash
# 1. Generate incident report
python3 /home/jacobw/quantstack/scripts/trading_report.py --date $(date +%F) --export incident_trades.csv

# 2. Collect relevant logs
journalctl --since "2 hours ago" > incident_logs_$(date +%Y%m%d_%H%M%S).log

# 3. Check system metrics
# - Resource usage during incident
# - Error patterns
# - Service restart frequency

# 4. Document lessons learned
echo "Incident $(date +%Y%m%d): SUMMARY" >> /home/jacobw/quantstack/docs/LESSONS_LEARNED.md
```

## Emergency Contacts & Escalation

### Internal Escalation
1. **System Owner**: jacobw (immediate)
2. **System Logs**: All incidents logged automatically
3. **NTFY Alerts**: Real-time notifications

### External Escalation
1. **IBKR Support**: If Gateway issues persist
2. **System Administrator**: If infrastructure issues
3. **Risk Management**: If trading limits exceeded

## Emergency Tools & Scripts

### Quick Access Scripts
```bash
# Emergency position closer
/home/jacobw/quantstack/close_open_positions.py

# System health check
/home/jacobw/quantstack/scripts/definitive_e2e_test.py

# IBKR connectivity test
/home/jacobw/quantstack/scripts/check_portal_status.py

# Trading report
/home/jacobw/quantstack/scripts/trading_report.py

# Emergency EOD check
/home/jacobw/quantstack/scripts/emergency_eod_close.py
```

### Emergency Commands Reference
```bash
# Stop all trading
sudo systemctl stop l2-scalping intraday-paper

# Check positions
python3 -c "from journal.event_store import EventStore; es = EventStore('/home/jacobw/intraday_stack/data/journal/events.db'); print(f'Open: {len(es.get_open_trades())}')"

# Force close positions
python3 /home/jacobw/quantstack/close_open_positions.py

# Check service status
systemctl status l2-collector l2-scalping intraday-paper

# View recent errors
journalctl --since "1 hour ago" | grep ERROR

# Restart services
sudo systemctl restart l2-collector l2-scalping intraday-paper
```

## Prevention Measures (Implemented)

### 1. Automated Risk Controls
- ✅ EOD position flattening (3:45 PM ET)
- ✅ Emergency backup closer (3:55 PM ET)
- ✅ Position sync every 5 minutes
- ✅ Stale price detection

### 2. System Monitoring
- ✅ Health checks every 5 minutes
- ✅ Service watchdog (L2 systems)
- ✅ Connection monitoring
- ✅ Resource usage tracking

### 3. Alert Systems
- ✅ NTFY real-time alerts
- ✅ Service failure notifications
- ✅ Emergency EOD alerts
- ✅ System health warnings

### 4. Data Protection
- ✅ Database integrity checks
- ✅ Trade journal backup
- ✅ Configuration version control
- ✅ Log rotation and archival

## Emergency Preparedness

### Regular Drills
- **Monthly**: Practice emergency shutdown
- **Weekly**: Test position closing scripts
- **Daily**: Verify alert systems

### Documentation Updates
- **After each incident**: Update procedures
- **Monthly**: Review and refine processes
- **Quarterly**: Full procedure validation

## Status: ✅ READY

Emergency procedures are documented, tested, and ready for deployment.

**Last Updated**: 2026-01-10  
**Next Drill**: Weekly (every Friday after market close)

---

*Keep this document accessible during all trading hours. Practice emergency procedures regularly.*
