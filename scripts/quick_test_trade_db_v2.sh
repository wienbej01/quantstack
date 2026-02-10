#!/bin/bash
# Quick test script for Trade Database V2

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_RESULTS="$PROJECT_ROOT/test_results/trade_db_v2"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "============================================================"
echo "Trade Database V2 - Quick Test"
echo "============================================================"
echo ""

# Create test results directory
mkdir -p "$TEST_RESULTS"

# Test 1: Schema Check
echo -e "${YELLOW}Test 1: Schema Verification${NC}"
python3 "$PROJECT_ROOT/scripts/verify_trade_db_v2.py" > "$TEST_RESULTS/schema_check.txt" 2>&1
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Schema check passed${NC}"
else
    echo -e "${RED}❌ Schema check failed${NC}"
    cat "$TEST_RESULTS/schema_check.txt"
    exit 1
fi
echo ""

# Test 2: WAL Directory
echo -e "${YELLOW}Test 2: WAL Directory${NC}"
WAL_DIR="$PROJECT_ROOT/logs/wal"
if [ -d "$WAL_DIR" ]; then
    echo -e "${GREEN}✅ WAL directory exists: $WAL_DIR${NC}"
    ls -lh "$WAL_DIR" | head -10
else
    echo -e "${YELLOW}⚠️  Creating WAL directory${NC}"
    mkdir -p "$WAL_DIR"
    chmod 755 "$WAL_DIR"
    echo -e "${GREEN}✅ WAL directory created${NC}"
fi
echo ""

# Test 3: Database Connection
echo -e "${YELLOW}Test 3: Database Connection${NC}"
psql -U jacobw -d trading -c "SELECT 1;" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Database connection successful${NC}"
else
    echo -e "${RED}❌ Database connection failed${NC}"
    echo "Check PostgreSQL credentials and ensure database is running"
    exit 1
fi
echo ""

# Test 4: Table Counts
echo -e "${YELLOW}Test 4: Table Counts${NC}"
psql -U jacobw -d trading -c "
SELECT 
    'executions' as table_name, COUNT(*) as count FROM executions
UNION ALL
SELECT 
    'trades_v2' as table_name, COUNT(*) as count FROM trades_v2
UNION ALL
SELECT 
    'positions' as table_name, COUNT(*) as count FROM positions;
" 2>&1 | tee "$TEST_RESULTS/table_counts.txt"
echo ""

# Test 5: Recent Activity
echo -e "${YELLOW}Test 5: Recent Activity (Last 24 Hours)${NC}"
psql -U jacobw -d trading -c "
SELECT 
    'Executions' as metric,
    COUNT(*) as count
FROM executions
WHERE received_at > NOW() - INTERVAL '24 hours'
UNION ALL
SELECT 
    'Trades' as metric,
    COUNT(*) as count
FROM trades_v2
WHERE signal_time > NOW() - INTERVAL '24 hours';
" 2>&1 | tee "$TEST_RESULTS/recent_activity.txt"
echo ""

# Test 6: Fill Capture Sources
echo -e "${YELLOW}Test 6: Fill Capture Sources${NC}"
psql -U jacobw -d trading -c "
SELECT 
    source,
    COUNT(*) as fills,
    ROUND(COUNT(*) * 100.0 / NULLIF(SUM(COUNT(*)) OVER (), 0), 2) as pct
FROM executions
WHERE received_at > NOW() - INTERVAL '24 hours'
GROUP BY source
ORDER BY fills DESC;
" 2>&1 | tee "$TEST_RESULTS/fill_sources.txt"
echo ""

# Test 7: Unlinked Fills
echo -e "${YELLOW}Test 7: Unlinked Fills Check${NC}"
UNLINKED=$(psql -U jacobw -d trading -t -c "SELECT COUNT(*) FROM executions WHERE trade_id IS NULL AND received_at > NOW() - INTERVAL '24 hours';")
UNLINKED=$(echo $UNLINKED | xargs)
if [ "$UNLINKED" -eq 0 ]; then
    echo -e "${GREEN}✅ No unlinked fills (last 24h)${NC}"
else
    echo -e "${YELLOW}⚠️  Unlinked fills: $UNLINKED${NC}"
fi
echo ""

# Test 8: Position Reconciliation
echo -e "${YELLOW}Test 8: Position Reconciliation${NC}"
DISCREPANCIES=$(psql -U jacobw -d trading -t -c "SELECT COUNT(*) FROM positions WHERE NOT is_reconciled;")
DISCREPANCIES=$(echo $DISCREPANCIES | xargs)
if [ "$DISCREPANCIES" -eq 0 ]; then
    echo -e "${GREEN}✅ No position discrepancies${NC}"
else
    echo -e "${RED}❌ Position discrepancies: $DISCREPANCIES${NC}"
fi
echo ""

# Test 9: Integration Check
echo -e "${YELLOW}Test 9: Integration Check${NC}"
if grep -q "from cpapi.trade_integration import TradeIntegration" "$PROJECT_ROOT/l2_scalping/src/main.py"; then
    echo -e "${GREEN}✅ l2-scalping integrated${NC}"
else
    echo -e "${RED}❌ l2-scalping not integrated${NC}"
fi

if grep -q "from cpapi.trade_integration import TradeIntegration" "$PROJECT_ROOT/l2_vwap_reversion/src/main.py"; then
    echo -e "${GREEN}✅ l2-vwap integrated${NC}"
else
    echo -e "${YELLOW}⚠️  l2-vwap not integrated${NC}"
fi
echo ""

# Summary
echo "============================================================"
echo "Test Summary"
echo "============================================================"
echo "Results saved to: $TEST_RESULTS"
echo ""
echo "Next steps:"
echo "1. Review test results in $TEST_RESULTS"
echo "2. Start l2-scalping: cd l2_scalping && ./start_scalping.sh"
echo "3. Monitor fills: watch -n 10 'psql -U jacobw -d trading -c \"SELECT COUNT(*) FROM executions;\"'"
echo "4. Run full verification: python3 scripts/verify_trade_db_v2.py"
echo ""
echo "See docs/TRADE_DB_V2_TEST_PLAN.md for complete test plan"
echo "============================================================"
