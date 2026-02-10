#!/bin/bash
# Trade Database V2 - Quick Test Runner
# Run all tests and display results

cd "$(dirname "$0")/.."

echo "=========================================="
echo "Trade Database V2 - Test Suite"
echo "=========================================="
echo ""

# Run tests
python3 scripts/run_trade_db_v2_tests.py 2>&1 | grep -v "WARNING:\|DETAIL:\|HINT:"

exit_code=$?

echo ""
echo "=========================================="
if [ $exit_code -eq 0 ]; then
    echo "✅ All tests passed!"
    echo "Trade DB V2 is ready for deployment"
else
    echo "❌ Some tests failed"
    echo "Review errors above"
fi
echo "=========================================="

exit $exit_code
