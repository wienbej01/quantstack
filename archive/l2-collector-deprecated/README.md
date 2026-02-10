# L2-Collector (DEPRECATED)

**Archived**: 2026-01-31

## Reason
L2 data collection is now handled by `l2-scalping` service.
This avoids running two separate services and simplifies the architecture.

## Contents
- `*.yaml` - qx-l2 collector configs
- `l2-collector.service` - systemd service file
- `l2-collector.timer` - systemd timer file

## Current Architecture
- `l2-scalping` handles BOTH trading AND L2 data collection
- Data written to: `/home/jacobw/quantstack/data/l2/l2_maximum/features/`
- `l2-vwap` reads from the same location

## Do Not Restore
These files are kept for reference only. Do not restore them.
