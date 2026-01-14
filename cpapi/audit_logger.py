"""
Centralized audit logging for trading system operations.

Provides structured JSONL logging with parallel human-readable output.
Handles timezone conversions (UTC/Manila/ET) and event categorization.
"""

import json
import logging
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import pytz

# Timezones
UTC = pytz.UTC
MANILA = pytz.timezone("Asia/Manila")
ET = pytz.timezone("America/New_York")


class EventType(str, Enum):
    """Audit event types."""

    TIMER_ACTIVATE = "TIMER_ACTIVATE"
    SERVICE_START = "SERVICE_START"
    SERVICE_READY = "SERVICE_READY"
    SERVICE_ERROR = "SERVICE_ERROR"
    SERVICE_STOP = "SERVICE_STOP"
    GATEWAY_AUTH = "GATEWAY_AUTH"
    PLATFORM_HEALTH = "PLATFORM_HEALTH"
    SIP_COMPLETE = "SIP_COMPLETE"
    TRADE_SIGNAL = "TRADE_SIGNAL"
    RESOURCE_ALERT = "RESOURCE_ALERT"
    DEPENDENCY_FAIL = "DEPENDENCY_FAIL"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Severity(str, Enum):
    """Event severity levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AuditLogger:
    """Centralized audit logger with structured and human-readable output."""

    def __init__(self, service_name: str, log_dir: Path | None = None):
        """
        Initialize audit logger.

        Args:
            service_name: Name of the service (e.g., 'intraday-sip')
            log_dir: Directory for audit logs (default: ~/quantstack/logs/audit)
        """
        self.service_name = service_name

        if log_dir is None:
            log_dir = Path.home() / "quantstack" / "logs" / "audit"

        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Get today's date in Manila timezone
        now_mnl = datetime.now(MANILA)
        date_str = now_mnl.strftime("%Y-%m-%d")

        # Log files
        self.jsonl_path = self.log_dir / f"audit_{date_str}.jsonl"
        self.human_path = self.log_dir / f"audit_{date_str}.log"

        # Setup Python logger for fallback
        self.logger = logging.getLogger(f"audit.{service_name}")

    def _get_timestamps(self) -> dict[str, str]:
        """Get current time in all three timezones."""
        now_utc = datetime.now(UTC)
        now_mnl = now_utc.astimezone(MANILA)
        now_et = now_utc.astimezone(ET)

        return {
            "timestamp_utc": now_utc.isoformat(),
            "timestamp_mnl": now_mnl.isoformat(),
            "timestamp_et": now_et.isoformat(),
        }

    def log_event(
        self,
        event_type: EventType,
        message: str,
        severity: Severity = Severity.INFO,
        context: dict[str, Any] | None = None,
        metrics: dict[str, Any] | None = None,
    ):
        """
        Log an audit event.

        Args:
            event_type: Type of event
            message: Human-readable message
            severity: Event severity
            context: Additional context data
            metrics: Performance/resource metrics
        """
        try:
            # Build event record
            event = {
                **self._get_timestamps(),
                "event_type": event_type.value,
                "service": self.service_name,
                "severity": severity.value,
                "message": message,
            }

            if context:
                event["context"] = context

            if metrics:
                event["metrics"] = metrics

            # Write JSONL
            with open(self.jsonl_path, "a") as f:
                f.write(json.dumps(event) + "\n")

            # Write human-readable
            now_mnl = datetime.fromisoformat(event["timestamp_mnl"])
            now_et = datetime.fromisoformat(event["timestamp_et"])

            human_line = (
                f"[{now_mnl.strftime('%Y-%m-%d %H:%M:%S')} MNL / "
                f"{now_et.strftime('%H:%M:%S')} ET] "
                f"[{severity.value}] [{self.service_name}] "
                f"{event_type.value}: {message}"
            )

            if context:
                human_line += f" | Context: {json.dumps(context)}"

            if metrics:
                human_line += f" | Metrics: {json.dumps(metrics)}"

            with open(self.human_path, "a") as f:
                f.write(human_line + "\n")

        except Exception as e:
            # Fallback to syslog
            self.logger.error(f"Audit logging failed: {e}", exc_info=True)
            self.logger.info(f"[AUDIT] {event_type.value}: {message}")

    def service_start(self, context: dict[str, Any] | None = None):
        """Log service start event."""
        self.log_event(
            EventType.SERVICE_START,
            f"{self.service_name} starting",
            Severity.INFO,
            context=context,
        )

    def service_ready(self, duration_ms: float | None = None):
        """Log service ready event."""
        metrics = {"startup_duration_ms": duration_ms} if duration_ms else None
        self.log_event(
            EventType.SERVICE_READY,
            f"{self.service_name} ready",
            Severity.INFO,
            metrics=metrics,
        )

    def service_error(self, error: str, context: dict[str, Any] | None = None):
        """Log service error event."""
        self.log_event(
            EventType.SERVICE_ERROR,
            f"{self.service_name} error: {error}",
            Severity.ERROR,
            context=context,
        )

    def service_stop(
        self, exit_code: int = 0, context: dict[str, Any] | None = None
    ):
        """Log service stop event."""
        severity = Severity.INFO if exit_code == 0 else Severity.ERROR
        self.log_event(
            EventType.SERVICE_STOP,
            f"{self.service_name} stopped (exit={exit_code})",
            severity,
            context=context,
        )

    def timer_activate(self, timer_name: str, expected_time: str, delay_ms: float = 0):
        """Log timer activation event."""
        self.log_event(
            EventType.TIMER_ACTIVATE,
            f"Timer {timer_name} activated",
            Severity.INFO,
            context={
                "timer": timer_name,
                "expected_time": expected_time,
                "delay_ms": delay_ms,
            },
        )

    def sip_complete(
        self, symbol_count: int, duration_ms: float, scores: dict | None = None
    ):
        """Log SIP generation completion."""
        self.log_event(
            EventType.SIP_COMPLETE,
            f"SIP generation complete: {symbol_count} symbols",
            Severity.INFO,
            context={"scores": scores} if scores else None,
            metrics={
                "symbol_count": symbol_count,
                "duration_ms": duration_ms,
            },
        )

    def resource_alert(self, resource: str, value: float, threshold: float):
        """Log resource usage alert."""
        self.log_event(
            EventType.RESOURCE_ALERT,
            f"High {resource} usage: {value:.1f} (threshold: {threshold})",
            Severity.WARNING,
            metrics={
                "resource": resource,
                "value": value,
                "threshold": threshold,
            },
        )


def get_audit_logger(service_name: str) -> AuditLogger:
    """Get or create audit logger for a service."""
    return AuditLogger(service_name)


if __name__ == "__main__":
    # Test the audit logger
    logger = get_audit_logger("test-service")

    logger.service_start(context={"trigger": "manual", "user": "jacobw"})
    logger.log_event(
        EventType.INFO,
        "Test event with metrics",
        metrics={"memory_mb": 128, "cpu_percent": 15.5},
    )
    logger.service_ready(duration_ms=1234.5)
    logger.service_stop(exit_code=0)

    print("✓ Audit logs written to:")
    print(f"  JSONL: {logger.jsonl_path}")
    print(f"  Human: {logger.human_path}")
