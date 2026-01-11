from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from qx_broker.gateway.config import GatewayConfig

CLIENT_CONNECT_RE = re.compile(r"Client\s+(\d+)\s+connected", re.IGNORECASE)
CLIENT_DISCONNECT_RE = re.compile(
    r"Socket connection for client\{(\d+)\} has closed", re.IGNORECASE
)


@dataclass(frozen=True)
class ClientSnapshot:
    active_ids: list[int]
    seen_ids: list[int]
    message: str


def parse_clients(config: GatewayConfig) -> ClientSnapshot:
    if not config.gateway_log_path:
        return ClientSnapshot([], [], "Gateway log path not configured.")

    log_path = Path(config.gateway_log_path)
    if not log_path.exists():
        return ClientSnapshot([], [], f"Gateway log not found at {log_path}.")

    active: set[int] = set()
    seen: set[int] = set()

    with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            connect_match = CLIENT_CONNECT_RE.search(line)
            if connect_match:
                client_id = int(connect_match.group(1))
                active.add(client_id)
                seen.add(client_id)
                continue

            disconnect_match = CLIENT_DISCONNECT_RE.search(line)
            if disconnect_match:
                client_id = int(disconnect_match.group(1))
                active.discard(client_id)
                seen.add(client_id)

    return ClientSnapshot(
        active_ids=sorted(active),
        seen_ids=sorted(seen),
        message="Parsed gateway log.",
    )
