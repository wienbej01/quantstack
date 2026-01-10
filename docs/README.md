# QUANTSTACK DOCUMENTATION

## Current Documentation (2026-01-10)

**📁 [CONSOLIDATED DOCUMENTATION](consolidated/README.md)**

All current, authoritative documentation has been consolidated into the `consolidated/` directory:

- **[System Overview](consolidated/CURRENT_SYSTEM_OVERVIEW.md)** - Complete system status and architecture
- **[User Guide](consolidated/USER_GUIDE.md)** - Daily operations and troubleshooting  
- **[Development History](consolidated/DEVELOPMENT_HISTORY.md)** - Technical evolution and lessons learned
- **[IBKR Gateway Protocol](consolidated/IBKR_GATEWAY_PROTOCOL.md)** - Connection management procedures
- **[Emergency Procedures](consolidated/EMERGENCY_PROCEDURES.md)** - Crisis management and recovery

## Quick Start

```bash
# Check system status
systemctl status l2-collector l2-scalping intraday-paper

# View today's trades  
python3 /home/jacobw/quantstack/scripts/trading_report.py --date $(date +%F)

# Emergency position close
python3 /home/jacobw/quantstack/close_open_positions.py
```

## Archive

Historical documentation has been moved to `archive/` directory.

---

**Start here**: [consolidated/README.md](consolidated/README.md)

