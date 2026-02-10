"""Test fixtures for IBKR integration tests."""

from __future__ import annotations

import os

import pytest

from qx_broker.ibkr import IBKRConfig


def _build_config() -> IBKRConfig:
    host = os.environ.get("IBKR_HOST", "127.0.0.1")
    port = int(os.environ.get("IBKR_PORT", "7497"))
    client_id = int(os.environ.get("IBKR_CLIENT_ID", "999"))
    system_name = os.environ.get("IBKR_SYSTEM_NAME", "IBKR_TEST")

    data = {
        "session": {
            "system_name": system_name,
            "connection": {
                "host": host,
                "port": port,
                "client_id": client_id,
                "connect_timeout": float(os.environ.get("IBKR_CONNECT_TIMEOUT", "10")),
                "request_timeout": float(os.environ.get("IBKR_REQUEST_TIMEOUT", "30")),
            },
        },
        "market_data": {
            "market_data_type": int(os.environ.get("IBKR_MARKET_DATA_TYPE", "1")),
        },
        "depth": {
            "num_rows": int(os.environ.get("IBKR_DEPTH_ROWS", "5")),
            "smart_depth": os.environ.get("IBKR_SMART_DEPTH", "false").lower()
            in {"1", "true", "yes"},
            "max_symbols": int(os.environ.get("IBKR_DEPTH_MAX", "3")),
        },
        "orders": {
            "order_ref_prefix": os.environ.get("IBKR_ORDER_REF", "TEST"),
            "account": os.environ.get("IBKR_ACCOUNT"),
        },
    }
    return IBKRConfig.from_dict(data)


@pytest.fixture(scope="session")
def ibkr_config() -> IBKRConfig:
    return _build_config()
