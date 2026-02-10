# Trade Database V2 - Full Test Plan

## Test Objectives

1. Verify 100% fill capture across all 3 layers
2. Confirm WAL durability during database outages
3. Validate position reconciliation accuracy
4. Test deduplication under high load
5. Verify P&L calculations match actual fills
6. Ensure zero data loss over 5-day parallel run

## Pre-Test Setup

### 1. Database Configuration
```bash
# Verify PostgreSQL is running
sudo systemctl status postgresql

# Set password if needed
psql -U jacobw -d trading
\password

# Verify schema
psql -U jacobw -d trading -c "\dt"
# Should show: executions, trades_v2, positions

# Create WAL directory
mkdir -p /home/jacobw/quantstack/logs/wal
chmod 755 /home/jacobw/quantstack/logs/wal
```

### 2. Environment Setup
```bash
# Add to ~/.bashrc or systemd service files
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=trading
export POSTGRES_USER=jacobw
export POSTGRES_PASSWORD=your_password  # Set actual password

# Reload
source ~/.bashrc
```

### 3. Baseline Verification
```bash
# Run health check
python3 scripts/verify_trade_db_v2.py

# Should show:
# ✅ All tables exist
# ✅ No fills yet (first run)
# ✅ No discrepancies
```

## Test Phase 1: Unit Testing (Day 1)

### Test 1.1: Basic Fill Capture
**Duration:** 1 hour  
**System:** l2-scalping (paper trading)

```bash
# Start l2-scalping
cd /home/jacobw/quantstack/l2_scalping
./start_scalping.sh

# Monitor logs
tail -f logs/scalping_system.log | grep -E "Trade DB|TRADE|FILL"
```

**Success Criteria:**
- [ ] System starts without errors
- [ ] Trade DB V2 initializes successfully
- [ ] At least 1 trade executed
- [ ] Trade appears in trades_v2 table
- [ ] All fills captured in executions table
- [ ] No unlinked fills

**Verification:**
```sql
-- Check trades
SELECT trade_id, symbol, direction, status, entry_price, net_pnl 
FROM trades_v2 
ORDER BY signal_time DESC 
LIMIT 5;

-- Check fills
SELECT exec_id, symbol, side, qty, price, source, received_at
FROM executions
ORDER BY received_at DESC
LIMIT 10;

-- Verify no unlinked fills
SELECT COUNT(*) FROM executions WHERE trade_id IS NULL;
-- Should be 0

-- Check fill sources
SELECT source, COUNT(*) as fills
FROM executions
GROUP BY source;
-- Should see: callback, polling, or reconciliation
```

### Test 1.2: Triple-Layer Verification
**Duration:** 2 hours  
**System:** l2-scalping

**Objective:** Verify all 3 fill capture layers work

```sql
-- Monitor fill sources in real-time
SELECT 
    source,
    COUNT(*) as fills,
    MAX(received_at) as last_fill
FROM executions
WHERE received_at > NOW() - INTERVAL '2 hours'
GROUP BY source;
```

**Success Criteria:**
- [ ] Fills captured from callback layer (Layer 1)
- [ ] Fills captured from polling layer (Layer 2)
- [ ] Reconciliation runs every 5 minutes (Layer 3)
- [ ] No duplicate fills in database (deduplication works)
- [ ] All fills have valid trade_id links

### Test 1.3: WAL Durability Test
**Duration:** 30 minutes  
**System:** l2-scalping

**Steps:**
```bash
# 1. Start system and verify trading
cd /home/jacobw/quantstack/l2_scalping
./start_scalping.sh

# 2. Wait for at least 1 trade to execute

# 3. Stop PostgreSQL (simulate outage)
sudo systemctl stop postgresql

# 4. Continue trading for 5 minutes
# Fills should write to WAL

# 5. Check WAL files
ls -lh /home/jacobw/quantstack/logs/wal/
tail -20 /home/jacobw/quantstack/logs/wal/fills_*.jsonl

# 6. Restart PostgreSQL
sudo systemctl start postgresql

# 7. Wait 2 minutes for WAL recovery

# 8. Verify fills recovered
psql -U jacobw -d trading -c "SELECT COUNT(*) FROM executions WHERE received_at > NOW() - INTERVAL '10 minutes';"
```

**Success Criteria:**
- [ ] System continues trading during DB outage
- [ ] Fills written to WAL files
- [ ] All fills recovered after DB restart
- [ ] No data loss
- [ ] No duplicate fills after recovery

## Test Phase 2: Integration Testing (Day 2-3)

### Test 2.1: Multi-System Test
**Duration:** 1 trading day  
**Systems:** l2-scalping + l2-vwap

```bash
# Terminal 1: Start l2-scalping
cd /home/jacobw/quantstack/l2_scalping
./start_scalping.sh

# Terminal 2: Start l2-vwap (after completing integration)
cd /home/jacobw/quantstack/l2_vwap_reversion
./start_l2_vwap.sh

# Terminal 3: Monitor database
watch -n 30 'psql -U jacobw -d trading -c "SELECT COUNT(*) FROM executions; SELECT COUNT(*) FROM trades_v2;"'
```

**Success Criteria:**
- [ ] Both systems run simultaneously
- [ ] No client ID conflicts
- [ ] Fills from both systems captured
- [ ] Trades properly attributed to correct system
- [ ] Position reconciliation works for both

**Verification:**
```sql
-- Check trades by system
SELECT 
    metadata->>'system' as system,
    COUNT(*) as trades,
    SUM(net_pnl) as total_pnl
FROM trades_v2
WHERE signal_time > NOW() - INTERVAL '1 day'
GROUP BY metadata->>'system';

-- Should show:
-- l2-scalping | X trades | $Y.YY
-- l2-vwap     | X trades | $Y.YY
```

### Test 2.2: Position Reconciliation
**Duration:** 4 hours  
**System:** All active systems

```bash
# Run reconciliation check every 30 minutes
watch -n 1800 'python3 scripts/verify_trade_db_v2.py | grep -A 10 "POSITION RECONCILIATION"'
```

**Success Criteria:**
- [ ] Reconciliation runs every 5 minutes
- [ ] Zero position discrepancies
- [ ] Database positions match IBKR positions
- [ ] Discrepancies logged if they occur

**Verification:**
```sql
-- Check reconciliation status
SELECT 
    symbol,
    qty,
    avg_price,
    is_reconciled,
    last_reconciled
FROM positions
ORDER BY last_reconciled DESC;

-- All should have is_reconciled = true
```

### Test 2.3: Partial Fill Handling
**Duration:** 2 hours  
**System:** l2-scalping

**Objective:** Verify VWAP calculation for partial fills

**Steps:**
1. Place large order that will fill in multiple parts
2. Monitor fills in real-time
3. Verify VWAP calculation

**Verification:**
```sql
-- Check partial fills
SELECT 
    trade_id,
    symbol,
    entry_fills,
    entry_price,
    entry_qty
FROM trades_v2
WHERE jsonb_array_length(entry_fills) > 1
ORDER BY signal_time DESC
LIMIT 5;

-- Manually verify VWAP calculation:
-- entry_price should equal weighted average of fills
```

**Success Criteria:**
- [ ] Multiple fills captured for single trade
- [ ] VWAP calculated correctly
- [ ] All partial fills linked to same trade_id
- [ ] Total quantity matches sum of fills

## Test Phase 3: Stress Testing (Day 3-4)

### Test 3.1: High-Frequency Trading
**Duration:** 4 hours  
**System:** l2-scalping (aggressive settings)

**Configuration:**
```yaml
# Temporarily increase trade frequency
risk:
  per_trade:
    max_loss_bps: 5  # Tighter stops = more trades
    profit_target_bps: 10
  daily:
    max_trades: 100  # Increase limit
```

**Success Criteria:**
- [ ] System handles 50+ trades in 4 hours
- [ ] All fills captured
- [ ] No database deadlocks
- [ ] No WAL file corruption
- [ ] Query performance acceptable (<100ms)

**Monitoring:**
```bash
# Monitor fill rate
watch -n 10 'psql -U jacobw -d trading -c "SELECT COUNT(*) FROM executions WHERE received_at > NOW() - INTERVAL '\''10 minutes'\'';"'

# Monitor database performance
psql -U jacobw -d trading -c "SELECT * FROM pg_stat_activity WHERE datname = 'trading';"
```

### Test 3.2: Deduplication Stress Test
**Duration:** 1 hour  
**System:** l2-scalping

**Objective:** Verify deduplication under high load

**Verification:**
```sql
-- Check for duplicate exec_ids (should be 0)
SELECT exec_id, COUNT(*) as count
FROM executions
GROUP BY exec_id
HAVING COUNT(*) > 1;

-- Check fill capture efficiency
SELECT 
    source,
    COUNT(*) as fills,
    COUNT(*) * 100.0 / SUM(COUNT(*)) OVER () as pct
FROM executions
WHERE received_at > NOW() - INTERVAL '1 hour'
GROUP BY source;
```

**Success Criteria:**
- [ ] Zero duplicate exec_ids
- [ ] All 3 layers attempting capture
- [ ] Database handling conflicts correctly
- [ ] No performance degradation

## Test Phase 4: Parallel Run (Day 4-8)

### Test 4.1: 5-Day Production Parallel
**Duration:** 5 trading days  
**Systems:** All production systems

**Setup:**
```bash
# Run Trade DB V2 alongside existing system
# Both systems capture same trades
# Compare results at end of each day
```

**Daily Verification Checklist:**
```bash
# Run at end of each trading day
python3 scripts/verify_trade_db_v2.py > /tmp/trade_db_report_$(date +%Y%m%d).txt

# Check for issues
grep -E "❌|⚠️" /tmp/trade_db_report_$(date +%Y%m%d).txt
```

**Daily Queries:**
```sql
-- Daily summary
SELECT 
    DATE(signal_time) as date,
    COUNT(*) as trades,
    SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) as closed,
    SUM(net_pnl) as total_pnl,
    AVG(net_pnl) as avg_pnl
FROM trades_v2
WHERE signal_time > NOW() - INTERVAL '1 day'
GROUP BY DATE(signal_time);

-- Fill capture rate
SELECT 
    DATE(received_at) as date,
    source,
    COUNT(*) as fills
FROM executions
WHERE received_at > NOW() - INTERVAL '1 day'
GROUP BY DATE(received_at), source
ORDER BY date DESC, source;

-- Unlinked fills (should be 0)
SELECT COUNT(*) 
FROM executions 
WHERE trade_id IS NULL 
    AND received_at > NOW() - INTERVAL '1 day';
```

**Success Criteria (Each Day):**
- [ ] 100% fill capture rate
- [ ] Zero unlinked fills
- [ ] Zero position discrepancies
- [ ] P&L matches old system (within $0.01)
- [ ] No database errors
- [ ] WAL files processed correctly

### Test 4.2: Comparison with Old System
**Duration:** End of 5-day run

**Comparison Queries:**
```sql
-- Trade DB V2 summary
SELECT 
    COUNT(*) as total_trades,
    SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) as closed_trades,
    SUM(net_pnl) as total_pnl,
    AVG(net_pnl) as avg_pnl,
    MIN(net_pnl) as worst_trade,
    MAX(net_pnl) as best_trade
FROM trades_v2
WHERE signal_time > NOW() - INTERVAL '5 days';

-- Old system summary (from trades table)
SELECT 
    COUNT(*) as total_trades,
    SUM(CASE WHEN status = 'closed' THEN 1 ELSE 0 END) as closed_trades,
    SUM(net_pnl) as total_pnl,
    AVG(net_pnl) as avg_pnl,
    MIN(net_pnl) as worst_trade,
    MAX(net_pnl) as best_trade
FROM trades
WHERE entry_time > NOW() - INTERVAL '5 days';

-- Compare results
-- Should match within rounding errors
```

**Success Criteria:**
- [ ] Trade counts match (±1 for timing differences)
- [ ] P&L totals match (within $1.00)
- [ ] All fills accounted for
- [ ] No missing trades in V2
- [ ] V2 has better fill capture rate

## Test Phase 5: Failure Scenarios (Day 9)

### Test 5.1: Database Connection Loss
```bash
# 1. Start trading
# 2. Block database port
sudo iptables -A OUTPUT -p tcp --dport 5432 -j DROP

# 3. Trade for 10 minutes
# 4. Restore connection
sudo iptables -D OUTPUT -p tcp --dport 5432 -j DROP

# 5. Verify recovery
```

**Success Criteria:**
- [ ] System continues trading
- [ ] Fills written to WAL
- [ ] Automatic reconnection
- [ ] All fills recovered

### Test 5.2: WAL Directory Full
```bash
# 1. Create small partition for WAL
# 2. Fill until disk full
# 3. Verify graceful handling
```

**Success Criteria:**
- [ ] Error logged clearly
- [ ] System doesn't crash
- [ ] Fallback to syslog
- [ ] Alert sent (if configured)

### Test 5.3: Corrupted WAL File
```bash
# 1. Stop system
# 2. Corrupt WAL file
echo "corrupted" >> /home/jacobw/quantstack/logs/wal/fills_*.jsonl

# 3. Restart system
# 4. Verify handling
```

**Success Criteria:**
- [ ] Corrupted entries skipped
- [ ] Valid entries processed
- [ ] Error logged
- [ ] System continues

## Test Phase 6: Performance Testing (Day 10)

### Test 6.1: Query Performance
```sql
-- Test common queries
EXPLAIN ANALYZE
SELECT * FROM trades_v2 
WHERE symbol = 'AAPL' 
    AND signal_time > NOW() - INTERVAL '7 days';

EXPLAIN ANALYZE
SELECT * FROM executions 
WHERE trade_id = 'some-uuid';

EXPLAIN ANALYZE
SELECT * FROM positions 
WHERE symbol IN ('AAPL', 'MSFT', 'GOOGL');
```

**Success Criteria:**
- [ ] All queries < 100ms
- [ ] Indexes used correctly
- [ ] No sequential scans on large tables

### Test 6.2: Write Performance
```bash
# Monitor insert rate during high-frequency trading
psql -U jacobw -d trading -c "
SELECT 
    schemaname,
    relname,
    n_tup_ins as inserts,
    n_tup_upd as updates
FROM pg_stat_user_tables
WHERE relname IN ('executions', 'trades_v2', 'positions');"
```

**Success Criteria:**
- [ ] Inserts keep up with fill rate
- [ ] No write bottlenecks
- [ ] WAL processing < 1 second lag

## Final Acceptance Test

### Checklist
- [ ] All Phase 1 tests passed
- [ ] All Phase 2 tests passed
- [ ] All Phase 3 tests passed
- [ ] 5-day parallel run successful
- [ ] All failure scenarios handled
- [ ] Performance acceptable
- [ ] Documentation complete
- [ ] Team trained on new system

### Go/No-Go Decision Criteria

**GO if:**
- 100% fill capture rate over 5 days
- Zero unlinked fills
- Zero position discrepancies
- P&L matches old system
- All failure scenarios handled gracefully
- Performance meets requirements

**NO-GO if:**
- Any fills lost
- Position discrepancies detected
- P&L doesn't match
- Database errors during normal operation
- Performance unacceptable

## Rollback Procedure

If NO-GO decision:
```bash
# 1. Stop all systems
systemctl stop l2-scalping l2-vwap

# 2. Comment out Trade DB V2 initialization
# In main.py files:
# self.trade_db = None  # Disabled

# 3. Restart systems
systemctl start l2-scalping l2-vwap

# 4. Verify old system working
# 5. Analyze failures
# 6. Fix issues
# 7. Restart test plan
```

## Test Execution Schedule

```
Day 1:  Phase 1 - Unit Testing (8 hours)
Day 2:  Phase 2 - Integration Testing (8 hours)
Day 3:  Phase 2 - Integration Testing + Phase 3 Start (8 hours)
Day 4:  Phase 3 - Stress Testing + Phase 4 Start (8 hours)
Day 5:  Phase 4 - Parallel Run Day 1
Day 6:  Phase 4 - Parallel Run Day 2
Day 7:  Phase 4 - Parallel Run Day 3
Day 8:  Phase 4 - Parallel Run Day 4
Day 9:  Phase 4 - Parallel Run Day 5 + Phase 5 - Failure Tests
Day 10: Phase 6 - Performance Testing + Final Review
Day 11: Go/No-Go Decision + Cutover (if GO)
```

## Test Artifacts

Save all test results:
```bash
mkdir -p /home/jacobw/quantstack/test_results/trade_db_v2

# Daily reports
python3 scripts/verify_trade_db_v2.py > test_results/trade_db_v2/report_day_$(date +%Y%m%d).txt

# Database dumps
pg_dump -U jacobw -d trading -t executions -t trades_v2 -t positions > test_results/trade_db_v2/db_snapshot_$(date +%Y%m%d).sql

# Logs
cp logs/scalping_system.log test_results/trade_db_v2/scalping_$(date +%Y%m%d).log
```

## Success Metrics Summary

| Metric | Target | Measurement |
|--------|--------|-------------|
| Fill Capture Rate | 100% | executions count vs IBKR |
| Unlinked Fills | 0 | COUNT WHERE trade_id IS NULL |
| Position Discrepancies | 0 | COUNT WHERE NOT is_reconciled |
| P&L Accuracy | ±$0.01 | Compare with old system |
| Query Performance | <100ms | EXPLAIN ANALYZE |
| WAL Recovery Time | <2 min | Manual test |
| System Uptime | 99.9% | During 5-day run |
| Data Loss | 0 fills | All scenarios |

## Contact & Escalation

**Test Lead:** [Your Name]  
**Database Admin:** [DBA Name]  
**On-Call:** [On-Call Contact]

**Escalation Path:**
1. Test failure → Review logs
2. Data loss → STOP ALL TRADING
3. Cannot resolve → Rollback to old system
4. Critical issue → Contact on-call immediately
