# Resource Usage Analysis - Fill Capture System

## Current Configuration

### IBKR API Call Frequency

**UnifiedFillProcessor** (per service):
- **Event subscription**: `ib.execDetailsEvent` - passive, no polling
- **Poll loop**: Every 2 seconds (backs off to 5s after 30s idle)
- **Reconcile loop**: Every 15 minutes (900s)

**Total API calls per service**:
- Normal: ~30 calls/minute (2s polling)
- Idle: ~12 calls/minute (5s polling)
- Reconcile: 1 call every 15 minutes

**With 3 services running** (l2-scalping, l2-vwap, intraday-paper):
- Peak: ~90 calls/minute
- Idle: ~36 calls/minute

**IBKR Rate Limits**:
- Market data: 60 requests/second
- Order placement: 50 orders/second
- Historical data: 60 requests/10 minutes

**Verdict**: ✅ **SAFE** - Well below IBKR limits

---

## Memory Usage

### Per Service Baseline
- Python process: ~50-100 MB
- ib_insync: ~20-30 MB
- PostgreSQL connection pool (2-10 conns): ~5-10 MB per connection
- WAL buffer: Negligible (<1 MB)

### Fill Capture Overhead
- **Fill callback**: 0 MB (just a log statement)
- **WAL write**: ~1 KB per fill
- **Database insert**: ~2 KB per fill

### Expected Memory Growth
- **100 fills/day**: ~300 KB (WAL + DB)
- **1000 fills/day**: ~3 MB (WAL + DB)

**With systemd limits**:
- MemoryMax=1G per service
- 3 services = 3GB max total
- System has 29GB RAM

**Verdict**: ✅ **SAFE** - Plenty of headroom

---

## CPU Usage

### Per Service Baseline
- Idle: 0-2% CPU
- Active trading: 5-10% CPU

### Fill Capture Overhead
- **Fill callback**: <0.1% (just a log)
- **WAL write**: <0.5% (file append + fsync)
- **Database insert**: <1% (single INSERT)

### Expected CPU Load
- **Per fill**: ~1-2% CPU spike for <100ms
- **100 fills/hour**: ~2-3% average CPU
- **With 3 services**: ~6-9% average CPU during active trading

**With systemd limits**:
- CPUQuota=50% per service
- 3 services = 150% max total (1.5 cores)
- System has 8 cores

**Verdict**: ✅ **SAFE** - Well within limits

---

## Logging Volume

### Current Logging
**Per fill** (3 log lines):
1. `FILL [source]:` - UnifiedFillProcessor._process_fill()
2. `FILL INSERTED:` - UnifiedFillProcessor._insert_execution()
3. `FILL CALLBACK:` - VWAPReversionSystem._on_fill()

**Log size per fill**: ~300 bytes × 3 = ~900 bytes

### Expected Volume
- **100 fills/day**: ~90 KB logs
- **1000 fills/day**: ~900 KB logs

**journalctl storage**:
- Default: 4GB max
- Rotation: 1 month

**Verdict**: ✅ **SAFE** - Negligible impact

---

## Optimizations Already in Place

### 1. Adaptive Polling
```python
def _poll_sleep_interval(self) -> float:
    if idle_for >= self._poll_idle_after_sec:
        return max(self._poll_idle_interval_sec, self._poll_interval_sec)
    return self._poll_interval_sec
```
- Backs off to 5s polling after 30s idle
- Reduces API calls by 60% during quiet periods

### 2. Database Connection Pooling
```python
self.pool = ThreadedConnectionPool(minconn=2, maxconn=10, ...)
```
- Reuses connections instead of creating new ones
- Prevents connection exhaustion

### 3. WAL Deduplication
```python
ON CONFLICT (exec_id) DO NOTHING
```
- Database-level deduplication prevents duplicate inserts
- Safe to process same fill multiple times

### 4. Systemd Resource Limits
```ini
MemoryMax=1G
CPUQuota=50%
```
- Hard limits prevent runaway processes
- System will kill service if limits exceeded

---

## Potential Issues & Mitigations

### Issue 1: Log Spam During High-Frequency Trading
**Scenario**: 1000 fills in 1 minute (extreme)  
**Impact**: 3000 log lines/minute = 50 lines/second  
**Mitigation**: Already in place - journalctl handles this fine

**If needed**: Add log level control
```python
if logger.isEnabledFor(logging.DEBUG):
    logger.debug(f"FILL [source]: ...")
```

### Issue 2: WAL File Growth
**Scenario**: 10,000 fills/day  
**Impact**: ~10 MB WAL file  
**Mitigation**: Already in place - daily rotation (new file per day)

**If needed**: Add WAL archival
```bash
# Cron job to compress old WAL files
find /home/jacobw/quantstack/logs/wal -name "fills_*.jsonl" -mtime +7 -exec gzip {} \;
```

### Issue 3: Database Connection Pool Exhaustion
**Scenario**: 3 services × 10 max connections = 30 connections  
**Impact**: Could hit PostgreSQL max_connections=100  
**Mitigation**: Already in place - connection pooling with putconn()

**If needed**: Reduce maxconn to 5 per service
```python
self.pool = ThreadedConnectionPool(minconn=2, maxconn=5, ...)
```

### Issue 4: IBKR Rate Limiting
**Scenario**: All 3 services polling simultaneously  
**Impact**: 90 calls/minute = 1.5 calls/second  
**Mitigation**: Already safe - well below 60 req/sec limit

**If needed**: Stagger polling intervals
```python
# l2-scalping: poll at 0, 2, 4, 6... seconds
# l2-vwap: poll at 0.5, 2.5, 4.5, 6.5... seconds
# intraday-paper: poll at 1, 3, 5, 7... seconds
```

---

## Monitoring Commands

### Real-Time Resource Usage
```bash
# CPU and memory per service
systemctl status l2-vwap-reversion.service | grep -E "Memory|CPU"

# Total system load
top -b -n 1 | head -20

# PostgreSQL connections
psql -d trading -U jacobw -c "SELECT count(*) FROM pg_stat_activity WHERE datname='trading';"
```

### Log Volume
```bash
# Logs per minute
journalctl -u l2-vwap-reversion.service --since "1 minute ago" | wc -l

# WAL file size
ls -lh /home/jacobw/quantstack/logs/wal/fills_$(date +%Y%m%d).jsonl
```

### IBKR API Call Rate
```bash
# Count "FILL [POLL]:" messages (indicates polling)
journalctl -u l2-vwap-reversion.service --since "1 minute ago" | grep "FILL \[POLL\]" | wc -l
```

---

## Recommended Limits (If Issues Arise)

### Conservative Settings
```bash
# Set environment variables before service start
export IBKR_FILL_POLL_INTERVAL_SEC=5.0        # Reduce from 2s to 5s
export IBKR_FILL_POLL_IDLE_INTERVAL_SEC=10.0  # Reduce from 5s to 10s
export IBKR_FILL_RECONCILE_INTERVAL_SEC=1800  # Reduce from 900s to 30min
export IBKR_FILL_WAL_FLUSH_INTERVAL_SEC=5.0   # Reduce from 2s to 5s
```

### Aggressive Settings (If System Struggles)
```bash
export IBKR_FILL_POLL_INTERVAL_SEC=10.0       # Poll every 10s
export IBKR_FILL_POLL_IDLE_INTERVAL_SEC=30.0  # Idle poll every 30s
export IBKR_FILL_RECONCILE_INTERVAL_SEC=3600  # Reconcile every hour
export IBKR_FILL_WAL_FLUSH_INTERVAL_SEC=10.0  # Flush every 10s
```

**Note**: Event subscription (`execDetailsEvent`) is still active and will capture fills immediately. Polling is just a backup.

---

## Conclusion

**Current configuration is SAFE**:
- ✅ IBKR API calls: 90/min peak (well below 3600/min limit)
- ✅ Memory: ~300 MB per service (3GB limit)
- ✅ CPU: ~10% per service (50% limit)
- ✅ Logging: ~1 MB/day (4GB limit)

**No changes needed** for market open. System will not overwhelm IBKR or machine.

**If issues arise**: Use environment variables to tune intervals without code changes.
