from __future__ import annotations

import time
from dataclasses import dataclass, field

from qx_broker.gateway.config import GatewayConfig
from qx_broker.gateway.health import GatewayManager
from qx_broker.gateway.status import fetch_status


@dataclass(frozen=True)
class RestartReport:
    success: bool
    steps: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class GatewayRestarter:
    def __init__(self, config: GatewayConfig):
        self.config = config
        self.config.validate()
        self.manager = GatewayManager(config)

    def restart(self, dry_run: bool = False) -> RestartReport:
        steps: list[str] = []
        warnings: list[str] = []

        status = fetch_status(self.config)
        if status.maintenance:
            warnings.append(status.message)
            return RestartReport(success=False, steps=steps, warnings=warnings)

        baseline = self.manager.check_health()
        steps.append(
            "Baseline: "
            f"reachable={baseline.reachable}, "
            f"estab_clients={baseline.estab_clients}, "
            f"close_wait={baseline.close_wait_sockets}"
        )

        stop_steps = self._stop_services(dry_run=dry_run)
        steps.extend(stop_steps)

        target_clients = self._expected_drain_target(baseline.estab_clients)
        if target_clients is not None:
            drained = self._wait_for_clients_below(
                target_clients,
                timeout=self.config.gateway_stop_wait_seconds,
                dry_run=dry_run,
            )
            if drained:
                steps.append(f"Drain: estab_clients <= {target_clients}")
            else:
                warnings.append(
                    f"Drain timeout: estab_clients did not drop to {target_clients} within "
                    f"{self.config.gateway_stop_wait_seconds}s."
                )

        steps.extend(self._restart_gateway(dry_run=dry_run, warnings=warnings))

        if not dry_run:
            time.sleep(self.config.gateway_startup_wait_seconds)

        post_gateway = self.manager.check_health()
        steps.append(
            "Post-gateway: "
            f"reachable={post_gateway.reachable}, "
            f"estab_clients={post_gateway.estab_clients}, "
            f"close_wait={post_gateway.close_wait_sockets}"
        )

        if not post_gateway.reachable:
            warnings.append("Gateway not reachable after restart.")

        steps.extend(self._start_services(dry_run=dry_run, warnings=warnings))

        success = post_gateway.reachable and not warnings
        return RestartReport(success=success, steps=steps, warnings=warnings)

    def _expected_drain_target(self, baseline_clients: int) -> int | None:
        expected = self.config.total_expected_clients()
        if expected <= 0:
            return None
        target = max(0, baseline_clients - expected)
        return target

    def _stop_services(self, dry_run: bool) -> list[str]:
        steps: list[str] = []
        for service in self.config.services:
            cmd = self._systemctl_cmd("stop", service)
            if dry_run:
                steps.append(f"DRY-RUN: {' '.join(cmd)}")
            else:
                result = self._run_cmd(cmd)
                steps.append(f"Stopped {service} (rc={result.returncode})")
                if result.returncode != 0:
                    steps.append(f"{service}: stderr={result.stderr.strip() or 'n/a'}")
        return steps

    def _start_services(self, dry_run: bool, warnings: list[str]) -> list[str]:
        steps: list[str] = []
        current_clients = self.manager.check_health().estab_clients
        for service in self.config.services:
            cmd = self._systemctl_cmd("start", service)
            if dry_run:
                steps.append(f"DRY-RUN: {' '.join(cmd)}")
                continue

            result = self._run_cmd(cmd)
            steps.append(f"Started {service} (rc={result.returncode})")
            if result.returncode != 0:
                warnings.append(
                    f"{service} start failed: {result.stderr.strip() or 'n/a'}"
                )
            time.sleep(self.config.service_start_delay_seconds)

            expected_delta = len(self.config.expected_client_ids.get(service, []))
            if expected_delta:
                target = current_clients + expected_delta
                started = self._wait_for_clients_at_least(
                    target, timeout=self.config.service_start_timeout_seconds
                )
                if started:
                    steps.append(f"{service}: estab_clients >= {target}")
                    current_clients = target
                else:
                    steps.append(
                        f"{service}: timeout waiting for estab_clients >= {target}"
                    )
        return steps

    def _restart_gateway(self, dry_run: bool, warnings: list[str]) -> list[str]:
        steps: list[str] = []
        stop_cmd = self._systemctl_cmd("stop", self.config.gateway_service)
        start_cmd = self._systemctl_cmd("start", self.config.gateway_service)
        if dry_run:
            steps.append(f"DRY-RUN: {' '.join(stop_cmd)}")
            steps.append(f"DRY-RUN: {' '.join(start_cmd)}")
            return steps

        stop_result = self._run_cmd(stop_cmd)
        steps.append(
            f"Stopped {self.config.gateway_service} (rc={stop_result.returncode})"
        )
        if stop_result.returncode != 0:
            warnings.append(
                f"Gateway stop failed: {stop_result.stderr.strip() or 'n/a'}"
            )
        time.sleep(self.config.gateway_stop_wait_seconds)
        start_result = self._run_cmd(start_cmd)
        steps.append(
            f"Started {self.config.gateway_service} (rc={start_result.returncode})"
        )
        if start_result.returncode != 0:
            warnings.append(
                f"Gateway start failed: {start_result.stderr.strip() or 'n/a'}"
            )
        return steps

    def _wait_for_clients_below(self, target: int, timeout: int, dry_run: bool) -> bool:
        if dry_run:
            return True
        if timeout <= 0:
            return True
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.manager.check_health().estab_clients <= target:
                return True
            time.sleep(2)
        return False

    def _wait_for_clients_at_least(self, target: int, timeout: int) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.manager.check_health().estab_clients >= target:
                return True
            time.sleep(2)
        return False

    def _systemctl_cmd(self, action: str, service: str) -> list[str]:
        base = ["systemctl"]
        if self.config.use_user_systemctl:
            base.append("--user")
        if self.config.use_sudo:
            return ["sudo", "-n", *base, action, service]
        return [*base, action, service]

    def _run_cmd(self, cmd: list[str]):
        import subprocess

        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
