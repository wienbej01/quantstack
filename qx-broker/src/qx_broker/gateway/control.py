from __future__ import annotations

import subprocess
from dataclasses import dataclass, field

from qx_broker.gateway.config import GatewayConfig
from qx_broker.gateway.health import GatewayManager
from qx_broker.gateway.status import fetch_status


@dataclass(frozen=True)
class ControlResult:
    ok: bool
    steps: list[str] = field(default_factory=list)


class GatewayController:
    def __init__(self, config: GatewayConfig):
        self.config = config
        self.config.validate()
        self.manager = GatewayManager(config)

    def start_gateway(self) -> ControlResult:
        status = fetch_status(self.config)
        if status.maintenance:
            return ControlResult(ok=False, steps=[status.message])
        return self._run_service_action("start", self.config.gateway_service)

    def stop_gateway(self) -> ControlResult:
        return self._run_service_action("stop", self.config.gateway_service)

    def restart_gateway(self) -> ControlResult:
        status = fetch_status(self.config)
        if status.maintenance:
            return ControlResult(ok=False, steps=[status.message])
        return self._run_service_action("restart", self.config.gateway_service)

    def stop_service(self, service: str) -> ControlResult:
        return self._run_service_action("stop", service)

    def start_service(self, service: str) -> ControlResult:
        return self._run_service_action("start", service)

    def restart_service(self, service: str) -> ControlResult:
        return self._run_service_action("restart", service)

    def kill_gateway_process(self) -> ControlResult:
        if not self.config.allow_force_kill:
            return ControlResult(
                ok=False,
                steps=["Force kill disabled. Set allow_force_kill=true to enable."],
            )

        steps: list[str] = []
        for pattern in self.config.process_patterns:
            result = subprocess.run(
                ["pkill", "-f", pattern],
                capture_output=True,
                text=True,
                check=False,
            )
            steps.append(
                f"pkill -f {pattern} (rc={result.returncode}) "
                f"{result.stderr.strip() or ''}".strip()
            )
        return ControlResult(ok=True, steps=steps)

    def _run_service_action(self, action: str, service: str) -> ControlResult:
        cmd = self._systemctl_cmd(action, service)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        steps = [
            f"{action} {service} (rc={result.returncode})",
        ]
        if result.stderr.strip():
            steps.append(f"stderr: {result.stderr.strip()}")
        return ControlResult(ok=result.returncode == 0, steps=steps)

    def _systemctl_cmd(self, action: str, service: str) -> list[str]:
        base = ["systemctl"]
        if self.config.use_user_systemctl:
            base.append("--user")
        if self.config.use_sudo:
            return ["sudo", "-n", *base, action, service]
        return [*base, action, service]
