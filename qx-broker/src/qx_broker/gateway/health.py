from __future__ import annotations

import json
import re
import socket
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from qx_broker.gateway.config import GatewayConfig


@dataclass(frozen=True)
class GatewayHealth:
    reachable: bool
    process_count: int
    process_pids: list[str]
    estab_sockets: int
    close_wait_sockets: int
    timestamp: str
    warnings: list[str] = field(default_factory=list)

    @property
    def estab_clients(self) -> int:
        return self.estab_sockets // 2

    def to_dict(self) -> dict:
        data = asdict(self)
        data["estab_clients"] = self.estab_clients
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


class GatewayManager:
    def __init__(self, config: GatewayConfig):
        self.config = config
        self.config.validate()

    def check_health(self) -> GatewayHealth:
        reachable = self._check_port()
        process_count, pids = self._count_processes()
        estab_sockets, close_wait_sockets = self._count_sockets()

        warnings: list[str] = []
        if process_count == 0:
            warnings.append("No gateway process detected.")
        if not reachable:
            warnings.append("Gateway port not reachable.")
        if close_wait_sockets > self.config.zombie_threshold:
            warnings.append(
                f"Zombie sockets exceed threshold: {close_wait_sockets} "
                f"(threshold={self.config.zombie_threshold})."
            )

        expected_clients = self.config.total_expected_clients()
        if expected_clients and self.estab_clients_below_expected(
            estab_sockets, expected_clients
        ):
            warnings.append(
                f"Established client sockets below expected: {estab_sockets // 2} "
                f"(expected={expected_clients})."
            )

        return GatewayHealth(
            reachable=reachable,
            process_count=process_count,
            process_pids=pids,
            estab_sockets=estab_sockets,
            close_wait_sockets=close_wait_sockets,
            timestamp=datetime.now(timezone.utc).isoformat(),
            warnings=warnings,
        )

    def estab_clients_below_expected(self, estab_sockets: int, expected: int) -> bool:
        return (estab_sockets // 2) < expected

    def _check_port(self) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        try:
            result = sock.connect_ex((self.config.host, self.config.port))
            return result == 0
        finally:
            sock.close()

    def _count_processes(self) -> tuple[int, list[str]]:
        pattern = "|".join(self.config.process_patterns)
        try:
            result = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception:
            return 0, []

        pids = [p.strip() for p in result.stdout.splitlines() if p.strip()]
        return len(pids), pids

    def _count_sockets(self) -> tuple[int, int]:
        try:
            result = subprocess.run(
                ["ss", "-an"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception:
            return 0, 0

        port_pattern = re.compile(fr":{self.config.port}\b")
        estab = 0
        close_wait = 0
        for line in result.stdout.splitlines():
            if not port_pattern.search(line):
                continue
            if "ESTAB" in line:
                estab += 1
            elif "CLOSE-WAIT" in line:
                close_wait += 1
        return estab, close_wait
