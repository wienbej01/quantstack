#!/bin/bash

echo "=== L2 Migration Status ==="
echo ""

# Check if migration is running
if pgrep -f "complete_l2_migration.sh" > /dev/null; then
    echo "✓ Migration is RUNNING"
    echo ""
    echo "Process:"
    ps aux | grep complete_l2_migration.sh | grep -v grep
else
    echo "✗ Migration is NOT running"
fi

echo ""
echo "Current sizes:"
echo "Local:"
du -sh /home/jacobw/quantstack/data/l2_maximum/{raw,features,features_v2} 2>/dev/null

echo ""
echo "GCS:"
du -sh /home/jacobw/quantstack/data/l2/l2_maximum/{raw,features,features_v2} 2>/dev/null

echo ""
echo "Recent log activity:"
tail -5 /tmp/l2_migration_main.log 2>/dev/null || echo "No log yet"
