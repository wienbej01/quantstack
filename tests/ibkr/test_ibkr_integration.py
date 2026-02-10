"""IBKR integration tests (opt-in)."""

from __future__ import annotations

import os
import time

import pytest
from ib_insync import LimitOrder

from qx_broker.ibkr import (
    ContractFactory,
    IBKRMarketData,
    IBKRMarketDepth,
    IBKROrderManager,
    IBKRSession,
)


def _require_live_data() -> bool:
    return os.environ.get("IBKR_REQUIRE_LIVE_DATA", "0").lower() in {"1", "true", "yes"}


@pytest.mark.ibkr
def test_connect_disconnect(ibkr_config):
    session = IBKRSession(ibkr_config.session)
    if not session.connect():
        pytest.skip("IBKR gateway not reachable")
    assert session.is_connected()
    assert session.check_connection()
    session.disconnect()


@pytest.mark.ibkr
def test_l1_l2_flow(ibkr_config):
    session = IBKRSession(ibkr_config.session)
    if not session.connect():
        pytest.skip("IBKR gateway not reachable")

    try:
        symbol = os.environ.get("IBKR_TEST_SYMBOL", "AAPL")
        exchange = os.environ.get("IBKR_TEST_EXCHANGE", "SMART")
        primary_exchange = os.environ.get("IBKR_TEST_PRIMARY_EXCHANGE")

        factory = ContractFactory(session)
        contract = factory.stock(
            symbol=symbol,
            exchange=exchange,
            primary_exchange=primary_exchange,
        )
        contract = factory.qualify(contract)

        market_data = IBKRMarketData(session, ibkr_config.market_data)
        depth = IBKRMarketDepth(session, ibkr_config.depth)

        market_data.subscribe(contract, snapshot=False)
        depth.subscribe(contract)

        deadline = time.time() + 10
        l1_ok = False
        l2_ok = False

        while time.time() < deadline and (not l1_ok or not l2_ok):
            snap = market_data.snapshot(symbol)
            depth_snap = depth.snapshot(symbol)
            if snap and (snap.bid is not None or snap.ask is not None or snap.last is not None):
                l1_ok = True
            if depth_snap and (depth_snap.bids or depth_snap.asks):
                l2_ok = True
            time.sleep(0.2)

        if _require_live_data():
            assert l1_ok, "L1 data not received"
            assert l2_ok, "L2 data not received"
        else:
            if not l1_ok or not l2_ok:
                pytest.skip("No live L1/L2 data available (market closed or no subscription)")
    finally:
        session.disconnect()


@pytest.mark.ibkr
def test_order_what_if(ibkr_config):
    if os.environ.get("IBKR_TEST_ORDERS", "0").lower() not in {"1", "true", "yes"}:
        pytest.skip("Set IBKR_TEST_ORDERS=1 to enable order connectivity test")

    session = IBKRSession(ibkr_config.session)
    if not session.connect():
        pytest.skip("IBKR gateway not reachable")

    try:
        symbol = os.environ.get("IBKR_TEST_SYMBOL", "AAPL")
        exchange = os.environ.get("IBKR_TEST_EXCHANGE", "SMART")
        primary_exchange = os.environ.get("IBKR_TEST_PRIMARY_EXCHANGE")

        factory = ContractFactory(session)
        contract = factory.stock(
            symbol=symbol,
            exchange=exchange,
            primary_exchange=primary_exchange,
        )
        contract = factory.qualify(contract)

        orders = IBKROrderManager(session, ibkr_config.orders)
        order = LimitOrder("BUY", 1, 0.01)
        what_if = orders.what_if(contract, order)
        assert what_if is not None
    finally:
        session.disconnect()
