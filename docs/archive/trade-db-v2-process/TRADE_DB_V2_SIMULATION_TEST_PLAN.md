# Trade Database V2 - Simulation Test Plan

## Overview

Test Trade Database V2 using **simulated fills from historical data** - no need to wait for market open.

## Test Environment

### Data Sources
- Historical Polygon data (already saved)
- Saved L2 data from previous sessions
- Simulated IBKR fills based on historical trades

### Test Duration
- **Total time: 2-3 hours** (vs 11 days for live testing)
- Can run anytime, no market hours required

## Quick Start

```bash
# Run simulation tests
cd /home/jacobw/quantstack
python3 scripts/simulate_trade_db_v2.py
```

## Test Phases

### Phase 1: Basic Simulation (15 minutes)

**Script:** `scripts/simulate_trade_db_v2.py`

**Tests:**
1. Single complete trade (entry + exit)
2. Trade with multiple partial fills
3. Multiple trades same symbol
4. Rapid trades (deduplication test)

**Verification:**
```bash
python3 scripts/simulate_trade_db_v2.py

# Check results
psql -U jacobw -d trading -c "
SELECT COUNT(*) as trades FROM trades_v2 WHERE metadata->>'test' = 'simulation';
SELECT COUNT(*) as fills FROM executions WHERE source = 'simulation';
"
```

**Success Criteria:**
- [ ] All simulated trades created
- [ ] All fills captured in executions table
- [ ] Zero unlinked fills
- [ ] P&L calculated correctly
- [ ] VWAP correct for partial fills

### Phase 2: WAL Durability Test (10 minutes)

**Test WAL without database:**

```bash
# 1. Stop PostgreSQL
sudo systemctl stop postgresql

# 2. Run simulation (fills go to WAL only)
python3 scripts/simulate_trade_db_v2.py

# 3. Check WAL files
ls -lh /home/jacobw/quantstack/logs/wal/
cat /home/jacobw/quantstack/logs/wal/fills_*.jsonl | wc -l

# 4. Restart PostgreSQL
sudo systemctl start postgresql

# 5. Process WAL (manual recovery simulation)
python3 scripts/process_wal_recovery.py

# 6. Verify fills recovered
psql -U jacobw -d trading -c "SELECT COUNT(*) FROM executions WHERE source = 'simulation';"
```

**Success Criteria:**
- [ ] Fills written to WAL during DB outage
- [ ] All fills recovered after DB restart
- [ ] No data loss
- [ ] No duplicate fills

### Phase 3: Deduplication Test (10 minutes)

**Test database-level deduplication:**

```python
# scripts/test_deduplication.py
import psycopg2
from uuid import uuid4

DB_CONFIG = {'host': 'localhost', 'port': 5432, 'database': 'trading', 'user': 'jacobw', 'password': ''}

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

# Insert same fill 3 times (simulating triple-layer capture)
exec_id = f"DUP{uuid4().hex[:8]}"
for i in range(3):
    cur.execute("""
        INSERT INTO executions (exec_id, symbol, side, qty, price, commission, exec_time, received_at, source)
        VALUES (%s, 'TEST', 'BUY', 100, 150.0, 0.5, NOW(), NOW(), %s)
        ON CONFLICT (exec_id) DO NOTHING
    """, (exec_id, f"layer_{i+1}"))
    
conn.commit()

# Verify only 1 row inserted
cur.execute("SELECT COUNT(*) FROM executions WHERE exec_id = %s", (exec_id,))
count = cur.fetchone()[0]

print(f"✅ Deduplication works: {count} row(s) inserted (expected 1)")
assert count == 1

cur.close()
conn.close()
```

**Success Criteria:**
- [ ] Only 1 fill inserted despite 3 attempts
- [ ] ON CONFLICT works correctly
- [ ] No database errors

### Phase 4: Historical Data Replay (30 minutes)

**Replay actual historical trades:**

```python
# scripts/replay_historical_trades.py
import pandas as pd
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from scripts.simulate_trade_db_v2 import FillSimulator

# Load historical trades from old system
import psycopg2
conn = psycopg2.connect(host='localhost', port=5432, database='trading', user='jacobw', password='')

# Get last 100 trades from old system
df = pd.read_sql("""
    SELECT symbol, direction, entry_qty, entry_price, exit_price
    FROM trades
    WHERE entry_time > NOW() - INTERVAL '7 days'
        AND status = 'closed'
    ORDER BY entry_time DESC
    LIMIT 100
""", conn)

conn.close()

# Replay trades
sim = FillSimulator()
for _, row in df.iterrows():
    sim.simulate_trade(
        symbol=row['symbol'],
        direction=row['direction'].upper(),
        qty=int(row['entry_qty']),
        price=float(row['entry_price'])
    )

print(f"\n✅ Replayed {len(df)} historical trades")
```

**Success Criteria:**
- [ ] All historical trades replayed
- [ ] P&L matches original trades (within $0.01)
- [ ] All fills captured
- [ ] Performance acceptable (<1 sec per trade)

### Phase 5: Stress Test (20 minutes)

**Simulate high-frequency trading:**

```python
# scripts/stress_test_trade_db.py
from scripts.simulate_trade_db_v2 import FillSimulator
import time

sim = FillSimulator()
symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "JPM"]

start = time.time()
trade_count = 0

# Simulate 100 trades as fast as possible
for i in range(100):
    symbol = symbols[i % len(symbols)]
    direction = "LONG" if i % 2 == 0 else "SHORT"
    sim.simulate_trade(symbol, direction, 100, 150.0 + i)
    trade_count += 1
    
    if (i + 1) % 10 == 0:
        print(f"Progress: {i+1}/100 trades")

elapsed = time.time() - start
print(f"\n✅ Completed {trade_count} trades in {elapsed:.2f}s")
print(f"   Rate: {trade_count/elapsed:.1f} trades/sec")
```

**Success Criteria:**
- [ ] 100 trades completed without errors
- [ ] All fills captured
- [ ] No database deadlocks
- [ ] Performance >10 trades/sec
- [ ] Zero unlinked fills

### Phase 6: Position Reconciliation (15 minutes)

**Test position tracking:**

```python
# scripts/test_position_tracking.py
from scripts.simulate_trade_db_v2 import FillSimulator
import psycopg2

sim = FillSimulator()

# Open multiple positions
sim.simulate_trade("AAPL", "LONG", 100, 150.0)
sim.simulate_trade("AAPL", "LONG", 50, 151.0)
sim.simulate_trade("MSFT", "SHORT", 200, 380.0)

# Check positions
conn = psycopg2.connect(host='localhost', port=5432, database='trading', user='jacobw', password='')
cur = conn.cursor()

cur.execute("""
    SELECT symbol, qty, avg_price, realized_pnl
    FROM positions
    WHERE symbol IN ('AAPL', 'MSFT')
    ORDER BY symbol
""")

print("\n📊 Positions:")
for row in cur.fetchall():
    print(f"  {row[0]}: {row[1]} @ ${row[2]:.2f}, P&L: ${row[3]:.2f}")

cur.close()
conn.close()
```

**Success Criteria:**
- [ ] Positions calculated correctly
- [ ] VWAP correct for multiple entries
- [ ] Realized P&L accurate
- [ ] No position discrepancies

### Phase 7: Integration Test (30 minutes)

**Test with actual system code (mock IBKR):**

```python
# scripts/test_integration_mock.py
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

# Mock IB connection
mock_ib = Mock()
mock_ib.reqExecutions = MagicMock(return_value=[])

# Test TradeIntegration
from cpapi.trade_integration import TradeIntegration

trade_int = TradeIntegration(
    ib=mock_ib,
    system_name="test-system"
)

# Start (without actual IB connection)
# trade_int.start()  # Skip for mock test

# Open trade
trade_id = trade_int.open_trade(
    symbol="AAPL",
    direction="LONG",
    signal_price=150.0,
    stop_loss=149.0,
    take_profit=151.0,
    metadata={"test": "integration"}
)

print(f"✅ Trade opened: {trade_id}")

# Verify in database
import psycopg2
conn = psycopg2.connect(host='localhost', port=5432, database='trading', user='jacobw', password='')
cur = conn.cursor()
cur.execute("SELECT * FROM trades_v2 WHERE trade_id = %s", (trade_id,))
trade = cur.fetchone()
print(f"✅ Trade in database: {trade is not None}")
cur.close()
conn.close()
```

**Success Criteria:**
- [ ] TradeIntegration initializes
- [ ] Trades created via integration layer
- [ ] Database operations work
- [ ] No IBKR connection required

## Verification Queries

### After Each Test Phase

```sql
-- Trade summary
SELECT 
    COUNT(*) as total_trades,
    COUNT(CASE WHEN status = 'closed' THEN 1 END) as closed,
    SUM(net_pnl) as total_pnl
FROM trades_v2
WHERE metadata->>'test' IN ('simulation', 'integration');

-- Fill capture
SELECT 
    source,
    COUNT(*) as fills
FROM executions
WHERE source IN ('simulation', 'layer_1', 'layer_2', 'layer_3')
GROUP BY source;

-- Unlinked fills (should be 0)
SELECT COUNT(*) 
FROM executions 
WHERE trade_id IS NULL 
    AND source IN ('simulation', 'layer_1', 'layer_2', 'layer_3');

-- Position accuracy
SELECT 
    symbol,
    qty,
    avg_price,
    realized_pnl,
    is_reconciled
FROM positions
ORDER BY symbol;
```

## Cleanup After Tests

```sql
-- Remove test data
DELETE FROM executions WHERE source IN ('simulation', 'layer_1', 'layer_2', 'layer_3');
DELETE FROM trades_v2 WHERE metadata->>'test' IN ('simulation', 'integration');
DELETE FROM positions WHERE symbol IN ('TEST', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META', 'JPM');

-- Or keep for reference
-- Test data is tagged with metadata->>'test' = 'simulation'
```

## Test Execution Timeline

```
Phase 1: Basic Simulation          - 15 min
Phase 2: WAL Durability            - 10 min
Phase 3: Deduplication             - 10 min
Phase 4: Historical Replay         - 30 min
Phase 5: Stress Test               - 20 min
Phase 6: Position Tracking         - 15 min
Phase 7: Integration Test          - 30 min
-----------------------------------------
Total:                               2h 10min
```

## Success Metrics

| Test | Metric | Target | Pass/Fail |
|------|--------|--------|-----------|
| Basic Simulation | Trades created | 7+ | [ ] |
| Basic Simulation | Fills captured | 100% | [ ] |
| Basic Simulation | Unlinked fills | 0 | [ ] |
| WAL Durability | Data loss | 0 fills | [ ] |
| WAL Durability | Recovery time | <2 min | [ ] |
| Deduplication | Duplicates | 0 | [ ] |
| Historical Replay | P&L accuracy | ±$0.01 | [ ] |
| Stress Test | Throughput | >10 trades/sec | [ ] |
| Stress Test | Errors | 0 | [ ] |
| Position Tracking | Accuracy | 100% | [ ] |
| Integration | API works | Yes | [ ] |

## Run All Tests

```bash
# Complete test suite
cd /home/jacobw/quantstack

# Phase 1
python3 scripts/simulate_trade_db_v2.py

# Phase 2 (requires sudo for PostgreSQL restart)
# See Phase 2 instructions above

# Phase 3
python3 scripts/test_deduplication.py

# Phase 4
python3 scripts/replay_historical_trades.py

# Phase 5
python3 scripts/stress_test_trade_db.py

# Phase 6
python3 scripts/test_position_tracking.py

# Phase 7
python3 scripts/test_integration_mock.py

# Final verification
python3 scripts/verify_trade_db_v2.py
```

## Advantages Over Live Testing

✅ **No market hours required** - run anytime  
✅ **Faster** - 2 hours vs 11 days  
✅ **Repeatable** - same data every time  
✅ **Controlled** - test specific scenarios  
✅ **Safe** - no real money at risk  
✅ **Comprehensive** - test all edge cases  

## Next Steps After Simulation Tests Pass

1. **Review results** - all metrics green
2. **Optional: 1-day live test** - verify with real IBKR fills
3. **Deploy to production** - confidence from simulation tests
4. **Monitor closely** - first week of production

## Notes

- Simulation tests validate **database logic** and **data integrity**
- Live testing validates **IBKR integration** and **network reliability**
- Both are valuable, but simulation tests catch 90% of issues
- Can run simulation tests in CI/CD pipeline
