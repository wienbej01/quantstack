"""Configuration models for IBKR access."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IBKRConnectionConfig:
    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 1
    readonly: bool = False
    connect_timeout: float = 10.0
    request_timeout: float = 30.0
    raise_request_errors: bool = True
    timezone_tws: str | None = None
    reconnect_attempts: int = 5
    reconnect_backoff_sec: float = 2.0
    allow_client_id_fallback: bool = True
    client_id_fallbacks: int = 5

    def validate(self) -> None:
        if not self.host:
            raise ValueError("IBKR host is required.")
        if self.port < 1 or self.port > 65535:
            raise ValueError(f"IBKR port out of range: {self.port}")
        if self.client_id < 0:
            raise ValueError("client_id must be >= 0.")
        if self.connect_timeout <= 0:
            raise ValueError("connect_timeout must be > 0.")
        if self.request_timeout < 0:
            raise ValueError("request_timeout must be >= 0.")
        if self.reconnect_attempts < 0:
            raise ValueError("reconnect_attempts must be >= 0.")
        if self.reconnect_backoff_sec < 0:
            raise ValueError("reconnect_backoff_sec must be >= 0.")
        if self.client_id_fallbacks < 0:
            raise ValueError("client_id_fallbacks must be >= 0.")


@dataclass(frozen=True)
class IBKRMarketDataConfig:
    market_data_type: int = 1
    snapshot: bool = False
    generic_ticks: str = ""

    def validate(self) -> None:
        if self.market_data_type not in {1, 2, 3, 4}:
            raise ValueError(
                "market_data_type must be one of {1,2,3,4} "
                "(live, frozen, delayed, delayed frozen)."
            )


@dataclass(frozen=True)
class IBKRDepthConfig:
    num_rows: int = 5
    smart_depth: bool = False
    max_symbols: int = 3

    def validate(self) -> None:
        if self.num_rows < 1 or self.num_rows > 10:
            raise ValueError("num_rows must be between 1 and 10.")
        if self.max_symbols < 1:
            raise ValueError("max_symbols must be >= 1.")


@dataclass(frozen=True)
class IBKROrderConfig:
    order_ref_prefix: str = "SYSTEM"
    account: str | None = None
    min_cancel_interval_sec: float = 2.0

    def validate(self) -> None:
        if not self.order_ref_prefix:
            raise ValueError("order_ref_prefix is required.")
        if self.min_cancel_interval_sec < 0:
            raise ValueError("min_cancel_interval_sec must be >= 0.")


@dataclass(frozen=True)
class IBKRSessionConfig:
    system_name: str = "IBKR"
    connection: IBKRConnectionConfig = field(default_factory=IBKRConnectionConfig)

    def validate(self) -> None:
        if not self.system_name:
            raise ValueError("system_name is required.")
        self.connection.validate()


@dataclass(frozen=True)
class IBKRConfig:
    session: IBKRSessionConfig = field(default_factory=IBKRSessionConfig)
    market_data: IBKRMarketDataConfig = field(default_factory=IBKRMarketDataConfig)
    depth: IBKRDepthConfig = field(default_factory=IBKRDepthConfig)
    orders: IBKROrderConfig = field(default_factory=IBKROrderConfig)

    def validate(self) -> None:
        self.session.validate()
        self.market_data.validate()
        self.depth.validate()
        self.orders.validate()

    @classmethod
    def from_dict(cls, data: dict) -> "IBKRConfig":
        session_cfg = data.get("session", {})
        ibkr_cfg = data.get("ibkr", {})
        conn_cfg = {**ibkr_cfg, **session_cfg.get("connection", data.get("connection", {}))}
        market_cfg = data.get("market_data", data.get("marketData", {}))
        depth_cfg = data.get("depth", data.get("market_depth", {}))
        orders_cfg = data.get("orders", data.get("order", {}))

        session = IBKRSessionConfig(
            system_name=str(session_cfg.get("system_name", session_cfg.get("name", "IBKR"))),
            connection=IBKRConnectionConfig(
                host=str(conn_cfg.get("host", "127.0.0.1")),
                port=int(conn_cfg.get("port", 7497)),
                client_id=int(conn_cfg.get("client_id", conn_cfg.get("clientId", 1))),
                readonly=bool(conn_cfg.get("readonly", False)),
                connect_timeout=float(conn_cfg.get("connect_timeout", 10.0)),
                request_timeout=float(conn_cfg.get("request_timeout", 30.0)),
                raise_request_errors=bool(conn_cfg.get("raise_request_errors", True)),
                timezone_tws=conn_cfg.get("timezone_tws"),
                reconnect_attempts=int(conn_cfg.get("reconnect_attempts", 5)),
                reconnect_backoff_sec=float(conn_cfg.get("reconnect_backoff_sec", 2.0)),
                allow_client_id_fallback=bool(conn_cfg.get("allow_client_id_fallback", True)),
                client_id_fallbacks=int(conn_cfg.get("client_id_fallbacks", 5)),
            ),
        )

        market_data = IBKRMarketDataConfig(
            market_data_type=int(market_cfg.get("market_data_type", 1)),
            snapshot=bool(market_cfg.get("snapshot", False)),
            generic_ticks=str(market_cfg.get("generic_ticks", "")),
        )

        depth = IBKRDepthConfig(
            num_rows=int(depth_cfg.get("num_rows", depth_cfg.get("depth_levels", 5))),
            smart_depth=bool(depth_cfg.get("smart_depth", False)),
            max_symbols=int(depth_cfg.get("max_symbols", 3)),
        )

        orders = IBKROrderConfig(
            order_ref_prefix=str(orders_cfg.get("order_ref_prefix", "SYSTEM")),
            account=orders_cfg.get("account"),
            min_cancel_interval_sec=float(orders_cfg.get("min_cancel_interval_sec", 2.0)),
        )

        config = cls(session=session, market_data=market_data, depth=depth, orders=orders)
        config.validate()
        return config
