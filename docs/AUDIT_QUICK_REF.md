# Audit Logging Quick Reference

## Query Commands

```bash
# Today's logs
python3 scripts/query_audit.py

# Specific date
python3 scripts/query_audit.py --date 2026-01-13

# Last 24 hours
python3 scripts/query_audit.py --last 24h

# Errors only
python3 scripts/query_audit.py --severity ERROR

# Specific service
python3 scripts/query_audit.py --service intraday-sip

# Specific event type
python3 scripts/query_audit.py --event-type SERVICE_ERROR

# Failure analysis
python3 scripts/analyze_failures.py --date 2026-01-14
python3 scripts/analyze_failures.py --last 7d
```

## Python Integration

```python
from cpapi.audit_logger import get_audit_logger, EventType, Severity

audit = get_audit_logger("my-service")

# Lifecycle
audit.service_start(context={"config": "production"})
audit.service_ready(duration_ms=1234)
audit.service_stop(exit_code=0)

# Events
audit.log_event(EventType.INFO, "Message", metrics={"count": 100})
audit.service_error("Error message", context={"detail": "info"})

# Specialized
audit.sip_complete(symbol_count=40, duration_ms=125000)
audit.resource_alert("memory", value=85.5, threshold=80.0)
```

## Systemd Integration

```ini
ExecStart=/home/jacobw/quantstack/scripts/audit_wrapper.sh service-name /path/to/command
```

## Log Locations

- JSONL: `/home/jacobw/quantstack/logs/audit/audit_YYYY-MM-DD.jsonl`
- Human: `/home/jacobw/quantstack/logs/audit/audit_YYYY-MM-DD.log`

## Event Types

- TIMER_ACTIVATE, SERVICE_START, SERVICE_READY, SERVICE_ERROR, SERVICE_STOP
- GATEWAY_AUTH, PLATFORM_HEALTH, SIP_COMPLETE, TRADE_SIGNAL
- RESOURCE_ALERT, DEPENDENCY_FAIL, INFO, WARNING, ERROR

## Troubleshooting Overnight Failures

1. Check errors: `python3 scripts/query_audit.py --severity ERROR --date YYYY-MM-DD`
2. Analyze: `python3 scripts/analyze_failures.py --date YYYY-MM-DD`
3. Service timeline: `python3 scripts/query_audit.py --service SERVICE_NAME`
4. Full timeline: `python3 scripts/query_audit.py --date YYYY-MM-DD`
