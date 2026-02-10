"""Unit tests for IBKR config parsing."""

from __future__ import annotations

from qx_broker.ibkr import IBKRConfig


def test_config_from_ibkr_section():
    data = {
        "ibkr": {
            "host": "10.0.0.1",
            "port": 7496,
            "client_id": 42,
        },
        "session": {
            "system_name": "TEST",
        },
    }
    config = IBKRConfig.from_dict(data)
    assert config.session.system_name == "TEST"
    assert config.session.connection.host == "10.0.0.1"
    assert config.session.connection.port == 7496
    assert config.session.connection.client_id == 42
