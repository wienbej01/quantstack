from __future__ import annotations

import time
from dataclasses import dataclass, field

from qx_broker.gateway.clients import parse_clients
from qx_broker.gateway.config import GatewayConfig
from qx_broker.gateway.health import GatewayManager
from qx_broker.gateway.restart import GatewayRestarter
from qx_broker.gateway.status import fetch_status


@dataclass(frozen=True)
class MonitorEvent:
    ok: bool
    message: str
    action: str | None = None
    warnings: list[str] = field(default_factory=list)


class GatewayMonitor:
    def __init__(self, config: GatewayConfig):
        self.config = config
        self.config.validate()
        self.manager = GatewayManager(config)
        self.restarter = GatewayRestarter(config)

    def run_once(self) -> MonitorEvent:
        status = fetch_status(self.config)
        if status.ok and status.maintenance:
            return MonitorEvent(
                ok=False,
                message=status.message,
                action="maintenance_backoff",
            )

        health = self.manager.check_health()
        if not health.reachable:
            report = self.restarter.restart(dry_run=False)
            return MonitorEvent(
                ok=report.success,
                message="Gateway unreachable; restart attempted.",
                action="restart_gateway",
                warnings=report.warnings,
            )

        if health.close_wait_sockets > self.config.zombie_threshold:
            report = self.restarter.restart(dry_run=False)
            return MonitorEvent(
                ok=report.success,
                message="Zombie threshold exceeded; restart attempted.",
                action="restart_gateway",
                warnings=report.warnings,
            )

        if self.config.drop_unknown_clients and self.config.gateway_log_path:
            snapshot = parse_clients(self.config)
            expected_ids = {
                client_id
                for ids in self.config.expected_client_ids.values()
                for client_id in ids
            }
            unknown_ids = [
                cid for cid in snapshot.active_ids if cid not in expected_ids
            ]
            if unknown_ids:
                report = self.restarter.restart(dry_run=False)
                return MonitorEvent(
                    ok=report.success,
                    message=f"Unknown clients detected: {unknown_ids}. Restart attempted.",
                    action="restart_gateway",
                    warnings=report.warnings,
                )

        return MonitorEvent(ok=True, message="Gateway healthy.")

    def loop(self) -> None:
        while True:
            event = self.run_once()
            if event.action == "maintenance_backoff":
                time.sleep(self.config.maintenance_backoff_seconds)
            else:
                time.sleep(self.config.monitor_interval_seconds)
