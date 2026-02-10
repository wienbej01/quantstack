# L2 VWAP Mean Reversion

Paper trading system implementing VWAP mean reversion with L2 depth filter and bracket orders.

**Uses same SIP symbols and L2 data as l2-scalping** - must run alongside l2-scalping service.

## Status: PRODUCTION READY ✓

- ✓ SIP symbol integration (same 3 symbols as l2-scalping)
- ✓ Real-time L2 data from l2-scalping output
- ✓ Bracket orders with stop-loss and take-profit
- ✓ Tick size rounding (0.01)
- ✓ EOD position flatten at 15:55 ET
- ✓ PostgreSQL trade database (shared event store)
- ✓ NTFY trade notifications
- ✓ Audit logging (JSONL + human-readable)
- ✓ Systemd timer for auto-start (Mon-Fri 22:26 Manila = 09:26 ET)

## Strategy Overview

Based on research from `quantresearch/projects/l2_vwap_spy_corr/research/analysis_summary.md`:

| Metric | Value |
|--------|-------|
| Variant | `spread_off` |
| Expectancy | 15.32 |
| Win Rate | 67.5% |
| Avg Duration | 25.1 min |

## Entry Conditions

- **Long**: `close <= VWAP * 0.995` AND `l2_ratio >= 1.165`
- **Short**: `close >= VWAP * 1.005` AND `l2_ratio <= 0.858`
- Entry window: 09:35-15:30 ET
- One position at a time

## Exit Conditions (Bracket Orders)

- **Take Profit**: +0.5% (long), -0.5% (short)
- **Stop Loss**: -0.75% (long), +0.75% (short)
- **Mean Reversion**: Price crosses VWAP
- **Forced Exit**: 15:55 ET (EOD flatten)

## Dependencies

This system **requires l2-scalping to be running** to provide:
- **SIP symbols**: Same 3 NYSE symbols from daily SIP universe
- **L2 data**: Real-time depth data at `/home/jacobw/quantstack/data/l2_maximum/features/`

## Installation

```bash
# Run install script
./install.sh

# Or manually:
sudo cp l2-vwap-reversion.service /etc/systemd/system/
sudo cp l2-vwap-reversion.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable l2-vwap-reversion.timer
sudo systemctl start l2-vwap-reversion.timer
```

## Commands

```bash
# Check timer (auto-start schedule)
systemctl list-timers l2-vwap-reversion.timer

# Start manually
sudo systemctl start l2-vwap-reversion

# Stop
sudo systemctl stop l2-vwap-reversion

# View logs
journalctl -u l2-vwap-reversion -f

# Check status
systemctl status l2-vwap-reversion
```

## IBKR Client IDs

| Session | Client ID |
|---------|-----------|
| Data (bars) | 350 |
| Orders | 300 |

## Data Sources

- **L2 Features**: `/home/jacobw/quantstack/data/l2_maximum/features/` (from l2-scalping)
- **SIP Universe**: `/home/jacobw/intraday_stack/data/daily_sip/` (shared with l2-scalping)

## Logs & Reporting

- **System logs**: `logs/vwap_reversion_YYYYMMDD.log`
- **Trade journal**: `logs/trades_YYYY-MM-DD.jsonl` (local backup)
- **Trade database**: PostgreSQL `trading` database (shared with l2-scalping)
- **Audit logs**: `/home/jacobw/quantstack/logs/audit/audit_YYYY-MM-DD.jsonl`
- **NTFY notifications**: Sent on trade entry/exit
- **Journalctl**: `journalctl -u l2-vwap-reversion`

## Project Structure

```
l2_vwap_reversion/
├── src/
│   ├── main.py              # Entry point with EOD handling
│   ├── strategy.py          # Core strategy logic
│   ├── vwap.py              # VWAP calculator
│   ├── l2_filter.py         # L2 ratio filter
│   ├── data/
│   │   ├── bar_feed.py      # 1-min bar feed
│   │   └── l2_reader.py     # L2 parquet reader
│   └── execution/
│       └── order_manager.py # Bracket orders
├── config/
│   ├── strategy.yaml
│   └── ibkr.yaml
├── logs/
├── l2-vwap-reversion.service
├── l2-vwap-reversion.timer
├── install.sh
└── start.sh
```
