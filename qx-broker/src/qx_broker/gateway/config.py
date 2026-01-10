from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class GatewayConfig:
    host: str = "127.0.0.1"
    port: int = 7497
    process_patterns: list[str] = field(default_factory=lambda: ["ibgateway", "tws"])
    zombie_threshold: int = 10
    expected_client_ids: dict[str, list[int]] = field(default_factory=dict)
    gateway_service: str = "ibkr-gateway.service"
    services: list[str] = field(
        default_factory=lambda: ["l2-scalping", "l2-collector", "intraday-paper"]
    )
    use_sudo: bool = False
    use_user_systemctl: bool = False
    gateway_startup_wait_seconds: int = 30
    gateway_stop_wait_seconds: int = 10
    service_start_delay_seconds: int = 5
    service_start_timeout_seconds: int = 45

    def validate(self) -> None:
        if not self.host:
            raise ValueError("Gateway host is required.")
        if self.port < 1 or self.port > 65535:
            raise ValueError(f"Gateway port out of range: {self.port}")
        if self.zombie_threshold < 0:
            raise ValueError("zombie_threshold must be >= 0.")
        if not self.process_patterns:
            raise ValueError("process_patterns must not be empty.")
        if not self.gateway_service:
            raise ValueError("gateway_service is required.")
        if self.gateway_startup_wait_seconds < 1:
            raise ValueError("gateway_startup_wait_seconds must be >= 1.")
        if self.gateway_stop_wait_seconds < 0:
            raise ValueError("gateway_stop_wait_seconds must be >= 0.")
        if self.service_start_delay_seconds < 0:
            raise ValueError("service_start_delay_seconds must be >= 0.")
        if self.service_start_timeout_seconds < 1:
            raise ValueError("service_start_timeout_seconds must be >= 1.")

        for service, ids in self.expected_client_ids.items():
            if not isinstance(ids, list):
                raise ValueError(f"expected_client_ids.{service} must be a list.")
            for client_id in ids:
                if not isinstance(client_id, int):
                    raise ValueError(
                        f"expected_client_ids.{service} must contain ints; got {client_id!r}"
                    )

    def total_expected_clients(self) -> int:
        return sum(len(ids) for ids in self.expected_client_ids.values())

    @classmethod
    def from_dict(cls, data: dict) -> "GatewayConfig":
        return cls(
            host=str(data.get("host", "127.0.0.1")),
            port=int(data.get("port", 7497)),
            process_patterns=list(data.get("process_patterns", ["ibgateway", "tws"])),
            zombie_threshold=int(data.get("zombie_threshold", 10)),
            expected_client_ids=dict(data.get("expected_client_ids", {})),
            gateway_service=str(data.get("gateway_service", "ibkr-gateway.service")),
            services=list(
                data.get(
                    "services", ["l2-scalping", "l2-collector", "intraday-paper"]
                )
            ),
            use_sudo=bool(data.get("use_sudo", False)),
            use_user_systemctl=bool(data.get("use_user_systemctl", False)),
            gateway_startup_wait_seconds=int(
                data.get("gateway_startup_wait_seconds", 30)
            ),
            gateway_stop_wait_seconds=int(data.get("gateway_stop_wait_seconds", 10)),
            service_start_delay_seconds=int(
                data.get("service_start_delay_seconds", 5)
            ),
            service_start_timeout_seconds=int(
                data.get("service_start_timeout_seconds", 45)
            ),
        )
