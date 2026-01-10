# L2 Data Collection - Systemd Setup

## Overview

The L2 data collector runs as a systemd service using a **daily daemon approach**:
- Starts once per day at 9:25 AM ET (5 minutes before market open)
- Runs continuously, collecting data during 7 configured windows
- Automatically handles collection scheduling and window management
- Provides 25x data improvement (2.16M records/day vs 86,400)

## Architecture

```
Daily Schedule:
9:25 AM ET: systemd timer starts L2 collector daemon
9:30 AM ET: First collection window begins (Opening Hour)
...       : Daemon waits between windows, collects during active periods
4:00 PM ET: Last collection window ends, daemon exits naturally
```

## Installation

```bash
# Install systemd service and timer
./scripts/install_l2_systemd.sh

# Verify installation
sudo systemctl status l2-collector.timer
sudo systemctl status l2-collector.service
```

## Configuration

**Service**: `/etc/systemd/system/l2-collector.service`
- Type: simple (long-running daemon)
- Restart: on-failure with 60s delay
- Uses: `qx-l2/configs/maximum_l2.yaml`

**Timer**: `/etc/systemd/system/l2-collector.timer`
- Schedule: Daily at 9:25 AM ET (14:25 UTC)
- Days: Monday-Friday only
- Persistent: true (catches up missed runs)

## Management Commands

```bash
# Status and monitoring
sudo systemctl status l2-collector.timer    # Timer status
sudo systemctl status l2-collector.service  # Service status
sudo journalctl -u l2-collector.service -f  # Live logs
python scripts/monitor_l2_systemd.py        # Data collection stats

# Control
sudo systemctl start l2-collector.service   # Manual start
sudo systemctl stop l2-collector.timer      # Stop scheduled runs
sudo systemctl restart l2-collector.timer   # Restart scheduling

# Debugging
sudo journalctl -u l2-collector.service --since "today"  # Today's logs
sudo systemctl list-timers l2-collector.timer           # Next run time
```

## Data Collection Details

**Collection Windows**: 7 windows covering 6.5 hours
- 09:30-10:30 (Opening Hour)
- 10:30-11:30
- 11:30-12:30
- 12:30-13:30
- 13:30-14:30
- 14:30-15:30
- 15:30-16:00 (Power Hour)

**Collection Rate**: 500ms intervals (2 snapshots/second)
**Symbols**: 50 symbols (10 core + 40 rotating)
**Depth**: 10 levels per symbol
**Client ID**: L2COLLECT_MAX_521 (separate from trading system)

## Performance Metrics

| Metric | Value |
|--------|-------|
| Daily Records | 2,160,000 |
| API Lines Used | 50/100 (50% utilization) |
| Storage per Day | ~500MB compressed |
| Timeline to 200k | 2-3 months (vs 18-20 months) |

## Integration with Trading System

The L2 collector operates independently from the trading system:
- **Trading System**: Uses 40 symbols for live trading
- **L2 Collector**: Uses 50 symbols for data collection
- **Total API Usage**: 90/100 lines (10-line safety buffer)
- **No Conflicts**: Separate client IDs and connection pools

## Troubleshooting

**Service won't start**:
```bash
sudo journalctl -u l2-collector.service --no-pager
# Check for IBKR connection issues or config errors
```

**No data collection**:
```bash
python scripts/monitor_l2_systemd.py
# Verify collection windows and file creation
```

**Timer not triggering**:
```bash
sudo systemctl list-timers --all | grep l2-collector
# Check timer status and next run time
```

## Files and Locations

- **Service**: `/etc/systemd/system/l2-collector.service`
- **Timer**: `/etc/systemd/system/l2-collector.timer`
- **Config**: `/home/jacobw/quantstack/qx-l2/configs/maximum_l2.yaml`
- **Data**: `/home/jacobw/quantstack/qx-l2/data/l2_dual/`
- **Logs**: `sudo journalctl -u l2-collector.service`
- **Monitor**: `/home/jacobw/quantstack/scripts/monitor_l2_systemd.py`
