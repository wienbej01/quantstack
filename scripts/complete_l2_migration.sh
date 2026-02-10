#!/bin/bash
set -euo pipefail

SOURCE="/home/jacobw/quantstack/data/l2_maximum"
DEST="/home/jacobw/quantstack/data/l2/l2_maximum"

echo "=== L2 Data Migration to GCS ==="
echo "Source: $SOURCE"
echo "Dest: $DEST"
echo ""

# Check if GCS mount is accessible
if [ ! -d "$DEST" ]; then
    echo "ERROR: GCS mount not accessible at $DEST"
    exit 1
fi

# Sync raw data
echo "Step 1/3: Syncing raw data..."
rsync -avh --progress --stats \
    "$SOURCE/raw/" \
    "$DEST/raw/" \
    2>&1 | tee -a /tmp/l2_migration_raw.log

# Sync features
echo ""
echo "Step 2/3: Syncing features..."
rsync -avh --progress --stats \
    "$SOURCE/features/" \
    "$DEST/features/" \
    2>&1 | tee -a /tmp/l2_migration_features.log

# Sync features_v2
echo ""
echo "Step 3/3: Syncing features_v2..."
rsync -avh --progress --stats \
    "$SOURCE/features_v2/" \
    "$DEST/features_v2/" \
    2>&1 | tee -a /tmp/l2_migration_features_v2.log

echo ""
echo "=== Migration Complete ==="
echo "Logs saved to /tmp/l2_migration_*.log"
echo ""
echo "Verification:"
du -sh "$SOURCE"/{raw,features,features_v2}
echo ""
du -sh "$DEST"/{raw,features,features_v2}
