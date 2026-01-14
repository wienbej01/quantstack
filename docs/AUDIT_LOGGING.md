# Audit Logging System - Usage Guide

## Overview

Comprehensive audit logging system for overnight trading operations with timeline reconstruction and failure analysis.

## Components

### 1. Core Library (`cpapi/audit_logger.py`)
- Structured JSONL logging + human-readable parallel output
- Automatic timezone conversion (UTC/Manila/ET)
- Event categorization and severity levels
- Context and metrics capture

### 2. Service Wrapper (`scripts/audit_wrapper.sh`)
- Wraps systemd service commands
- Tracks lifecycle events (START/READY/STOP)
- Captures resource metrics (memory, CPU)
- Records exit codes and duration

### 3. Query Tool (`scripts/query_audit.py`)
- Search audit logs by date, service, severity, event type
- Time-range queries
- Human-readable and JSON output formats

### 4. Failure Analyzer (`scripts/analyze_failures.py`)
- Aggregate failure statistics
- Group by service and event type
- Exit code distribution analysis
- Failure rate calculation

## Log Files

All logs stored in: `/home/jacobw/quantstack/logs/audit/`

- `audit_YYYY-MM-DD.jsonl` - Structured JSON Lines format
- `audit_YYYY-MM-DD.log` - Human-readable timeline

## Usage Examples

### Query Today's Logs
```bash
python3 scripts/query_audit.py
```

### Query Specific Date
```bash
python3 scripts/query_audit.py --date 2026-01-13
```

### Filter by Service
```bash
python3 scripts/query_audit.py --service intraday-sip
```

### Show Only Errors
```bash
python3 scripts/query_audit.py --severity ERROR
```

### Last 24 Hours
```bash
python3 scripts/query_audit.py --last 24h
```

### Specific Event Type
```bash
python3 scripts/query_audit.py --event-type SERVICE_ERROR
```

### JSON Output
```bash
python3 scripts/query_audit.py --format json > audit_export.json
```

### Analyze Failures
```bash
python3 scripts/analyze_failures.py --date 2026-01-14
```

### Weekly Failure Report
```bash
python3 scripts/analyze_failures.py --last 7d
```

## Python Integration

### Basic Usage
```python
from cpapi.audit_logger import get_audit_logger, EventType, Severity

# Get logger for your service
audit = get_audit_logger("my-service")

# Log service lifecycle
audit.service_start(context={"trigger": "timer", "config": "production"})
audit.service_ready(duration_ms=1234.5)

# Log custom events
audit.log_event(
    EventType.INFO,
    "Processing 100 symbols",
    metrics={"symbol_count": 100, "duration_ms": 5432}
)

# Log errors
audit.service_error("Connection failed", context={"host": "localhost", "port": 8000})

# Log service stop
audit.service_stop(exit_code=0)
```

### Specialized Events
```python
# Timer activation
audit.timer_activate("intraday-sip.timer", "09:10:00 ET", delay_ms=234)

# SIP completion
audit.sip_complete(
    symbol_count=40,
    duration_ms=125000,
    scores={"AAPL": 0.85, "MSFT": 0.82}
)

# Resource alerts
audit.resource_alert("memory", value=85.5, threshold=80.0)
```

## Systemd Integration

### Wrap Service Command
Modify systemd service file:

**Before:**
```ini
ExecStart=/home/jacobw/quantstack/scripts/my_service.sh
```

**After:**
```ini
ExecStart=/home/jacobw/quantstack/scripts/audit_wrapper.sh my-service /home/jacobw/quantstack/scripts/my_service.sh
```

### Example Service File
```ini
[Unit]
Description=My Trading Service
After=network.target

[Service]
Type=simple
User=jacobw
WorkingDirectory=/home/jacobw/quantstack
ExecStart=/home/jacobw/quantstack/scripts/audit_wrapper.sh my-service /home/jacobw/quantstack/scripts/my_service.sh
Restart=on-failure
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

## Event Types

- `TIMER_ACTIVATE` - Timer triggered
- `SERVICE_START` - Service starting
- `SERVICE_READY` - Service operational
- `SERVICE_ERROR` - Service error/exception
- `SERVICE_STOP` - Service stopped
- `GATEWAY_AUTH` - IBKR Gateway authentication
- `PLATFORM_HEALTH` - Platform health check
- `SIP_COMPLETE` - SIP generation complete
- `TRADE_SIGNAL` - Trade order placed
- `RESOURCE_ALERT` - High resource usage
- `DEPENDENCY_FAIL` - Dependency failure
- `INFO` - General information
- `WARNING` - Warning condition
- `ERROR` - Error condition

## Severity Levels

- `DEBUG` - Detailed debugging information
- `INFO` - Normal operational events
- `WARNING` - Warning conditions
- `ERROR` - Error conditions
- `CRITICAL` - Critical failures

## Troubleshooting Overnight Failures

### 1. Check What Happened Last Night
```bash
# Query overnight period (22:00 MNL - 05:00 MNL)
python3 scripts/query_audit.py --date 2026-01-13 --last 12h
```

### 2. Find Service Failures
```bash
# Show all errors
python3 scripts/query_audit.py --severity ERROR --date 2026-01-13

# Specific service errors
python3 scripts/query_audit.py --service intraday-paper --severity ERROR
```

### 3. Analyze Failure Patterns
```bash
# Get failure summary
python3 scripts/analyze_failures.py --date 2026-01-13

# Weekly trends
python3 scripts/analyze_failures.py --last 7d
```

### 4. Check Service Timeline
```bash
# See full service lifecycle
python3 scripts/query_audit.py --service intraday-sip --date 2026-01-13

# Check timing issues
python3 scripts/query_audit.py --event-type TIMER_ACTIVATE --date 2026-01-13
```

### 5. Verify SIP Generation
```bash
# Check SIP completion
python3 scripts/query_audit.py --event-type SIP_COMPLETE --date 2026-01-13
```

## Log Rotation

Logs are automatically rotated daily. Each day gets its own file:
- `audit_2026-01-13.jsonl`
- `audit_2026-01-14.jsonl`
- etc.

Recommended: Keep 30 days of logs, compress older than 7 days.

## Performance

- Minimal overhead: ~1-2ms per log event
- Async writes to avoid blocking
- Automatic fallback to syslog on failure
- Typical daily log size: 5-10 MB (uncompressed)

## Next Steps

1. **Integrate with remaining services**: Add audit logging to paper trading, l2-scalping, l2-collector
2. **Update systemd files**: Wrap all service commands with audit_wrapper.sh
3. **Add NTFY alerts**: Send critical audit events to phone
4. **Create dashboard**: Build real-time monitoring dashboard
5. **Automate reports**: Daily failure summary via email/NTFY

## Support

For issues or questions, check:
- Audit logs: `/home/jacobw/quantstack/logs/audit/`
- System logs: `journalctl -u <service-name>`
- Test audit logger: `python3 cpapi/audit_logger.py`
