# L2 Data Migration Status

**Date**: 2026-01-28  
**Status**: INCOMPLETE - Machine crashed mid-process

## Current State

### Local (`~/quantstack/data/l2_maximum`)
- **raw**: 11 GB (739,859 files)
- **features**: 8.3 GB (363,006 files)
- **features_v2**: 11 MB
- **Total**: ~20 GB

### GCS Mount (`~/quantstack/data/l2/l2_maximum`)
- **raw**: 0 GB (0 files) ❌
- **features**: 111 MB (2,845 files) ⚠️ PARTIAL
- **features_v2**: 0 GB ❌
- **Total**: ~111 MB

## Analysis

The migration was interrupted early:
- Only ~1% of features were transferred (2,845 / 363,006 files)
- No raw data was transferred
- No features_v2 data was transferred

## Completion Plan

Run the migration script:
```bash
~/quantstack/scripts/complete_l2_migration.sh
```

This will:
1. Sync all raw L2 data (11 GB)
2. Complete features sync (remaining 8.2 GB)
3. Sync features_v2 (11 MB)

**Estimated time**: 30-60 minutes depending on network speed

## Post-Migration

After successful migration, update code references from:
- `~/quantstack/data/l2_maximum` → `~/quantstack/data/l2/l2_maximum`

Services that may need updates:
- `l2_scalping/platform.py`
- `qx-l2` package
- Any scripts reading L2 data

## Logs

Migration logs will be saved to:
- `/tmp/l2_migration_raw.log`
- `/tmp/l2_migration_features.log`
- `/tmp/l2_migration_features_v2.log`
