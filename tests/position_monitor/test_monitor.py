"""
Unit tests for position_monitor.monitor.
"""

import json
from datetime import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from position_monitor.models import PnLData, Position
from position_monitor.monitor import PositionMonitor


@pytest.fixture
def temp_output_file(tmp_path):
    """Create a temporary output file."""
    return tmp_path / "positions.json"


@pytest.fixture
def monitor(temp_output_file):
    """Create a PositionMonitor with mocked session/account."""
    mon = PositionMonitor(
        host="127.0.0.1",
        port=7497,
        client_id=900,
        output_file=str(temp_output_file),
    )
    mon.session = MagicMock()
    mon.account = MagicMock()
    return mon


class TestPositionMonitorInit:
    """Test PositionMonitor initialization."""

    def test_init_defaults(self):
        """Test initialization with default values."""
        mon = PositionMonitor()
        assert mon.host == "127.0.0.1"
        assert mon.port == 7497
        assert mon.client_id == 900
        assert str(mon.output_file) == "/tmp/positions.json"
        assert mon.account_id is None

    def test_init_custom(self, temp_output_file):
        """Test initialization with custom values."""
        mon = PositionMonitor(
            host="localhost",
            port=4002,
            client_id=901,
            output_file=str(temp_output_file),
            account_id="DU123456",
        )
        assert mon.host == "localhost"
        assert mon.port == 4002
        assert mon.client_id == 901
        assert mon.output_file == temp_output_file
        assert mon.account_id == "DU123456"


class TestPositionMonitorConnect:
    """Test PositionMonitor connection."""

    def test_connect_success(self, monitor):
        """Test successful connection."""
        monitor.session.connect.return_value = True
        monitor._resolve_account_id = MagicMock(return_value="DU123456")
        monitor.account.subscribe_pnl.return_value = MagicMock()

        result = monitor.connect()

        assert result is True
        monitor.session.connect.assert_called_once()
        monitor.account.subscribe_pnl.assert_called_once_with("DU123456")

    def test_connect_fail(self, monitor):
        """Test connection failure."""
        monitor.session.connect.return_value = False
        result = monitor.connect()
        assert result is False


class TestMarketHours:
    """Test market hours detection."""

    @patch("position_monitor.monitor.datetime")
    def test_is_market_hours_true(self, mock_datetime, monitor):
        """Test market hours detection during market hours."""
        mock_datetime.now.return_value.time.return_value = time(
            10, 0, tzinfo=ZoneInfo("America/New_York")
        )
        assert monitor.is_market_hours() is True

    @patch("position_monitor.monitor.datetime")
    def test_is_market_hours_false_before(self, mock_datetime, monitor):
        """Test market hours detection before market opens."""
        mock_datetime.now.return_value.time.return_value = time(
            8, 0, tzinfo=ZoneInfo("America/New_York")
        )
        assert monitor.is_market_hours() is False

    @patch("position_monitor.monitor.datetime")
    def test_is_market_hours_false_after(self, mock_datetime, monitor):
        """Test market hours detection after market close."""
        mock_datetime.now.return_value.time.return_value = time(
            17, 0, tzinfo=ZoneInfo("America/New_York")
        )
        assert monitor.is_market_hours() is False


class TestGetOpenPositions:
    """Test getting open positions."""

    def test_get_open_positions_no_account(self, monitor):
        """Test getting positions when no account is set."""
        monitor.account_id = None
        positions = monitor.get_open_positions()
        assert positions == []

    def test_get_open_positions_success(self, monitor):
        """Test successfully getting positions."""
        monitor.account_id = "DU123456"
        monitor.account.positions.return_value = [
            SimpleNamespace(
                contract=SimpleNamespace(symbol="AAPL"),
                position=100,
                avgCost=150.0,
                marketPrice=155.0,
                marketValue=15500.0,
                unrealizedPNL=500.0,
            ),
            SimpleNamespace(
                contract=SimpleNamespace(symbol="TSLA"),
                position=-50,
                avgCost=200.0,
                marketPrice=195.0,
                marketValue=-9750.0,
                unrealizedPNL=250.0,
            ),
        ]

        positions = monitor.get_open_positions()
        assert len(positions) == 2
        assert positions[0].symbol == "AAPL"
        assert positions[0].quantity == 100
        assert positions[0].unrealized_pnl == 500.0
        assert positions[1].symbol == "TSLA"
        assert positions[1].quantity == -50

    def test_get_open_positions_skip_zero_quantity(self, monitor):
        """Test that positions with zero quantity are skipped."""
        monitor.account_id = "DU123456"
        monitor.account.positions.return_value = [
            SimpleNamespace(
                contract=SimpleNamespace(symbol="AAPL"),
                position=100,
                avgCost=150.0,
                marketPrice=155.0,
                marketValue=15500.0,
                unrealizedPNL=500.0,
            ),
            SimpleNamespace(
                contract=SimpleNamespace(symbol="TSLA"),
                position=0,
                avgCost=200.0,
                marketPrice=195.0,
                marketValue=0.0,
                unrealizedPNL=0.0,
            ),
        ]

        positions = monitor.get_open_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"


class TestGetDailyPnL:
    """Test getting daily P&L."""

    def test_get_daily_pnl(self, monitor):
        """Test getting daily P&L from subscription fields."""
        monitor._pnl_subscription = SimpleNamespace(
            dailyPnL=1234.56, realizedPnL=100.0, unrealizedPnL=1134.56
        )
        pnl = monitor.get_daily_pnl()
        assert pnl.daily_pnl == 1234.56
        assert pnl.realized_pnl == 100.0
        assert pnl.unrealized_pnl == 1134.56

    def test_get_daily_pnl_no_subscription(self, monitor):
        """Test getting daily P&L without subscription."""
        monitor._pnl_subscription = None
        pnl = monitor.get_daily_pnl()
        assert pnl.daily_pnl == 0.0


class TestWritePositionsJson:
    """Test writing positions to JSON."""

    def test_write_positions_json_market_hours(self, monitor, temp_output_file):
        """Test writing JSON during market hours."""
        monitor.account_id = "DU123456"

        with patch.object(monitor, "is_market_hours", return_value=True):
            with patch.object(
                monitor,
                "get_open_positions",
                return_value=[
                    Position(
                        symbol="AAPL",
                        quantity=100,
                        avg_price=150.0,
                        current_price=155.0,
                        unrealized_pnl=500.0,
                        market_value=15500.0,
                    )
                ],
            ):
                with patch.object(
                    monitor, "get_daily_pnl", return_value=PnLData(daily_pnl=1234.56)
                ):
                    result = monitor.write_positions_json()
                    assert result is True

        with open(temp_output_file) as f:
            data = json.load(f)
        assert data["market_hours"] is True
        assert len(data["positions"]) == 1
        assert data["positions"][0]["symbol"] == "AAPL"
        assert data["positions"][0]["pnl"] == "+500.00"
        assert data["daily_pnl"] == "+$1234.56"

    def test_write_positions_json_outside_market_hours(self, monitor, temp_output_file):
        """Test writing JSON outside market hours."""
        with patch.object(monitor, "is_market_hours", return_value=False):
            result = monitor.write_positions_json()
            assert result is True

        with open(temp_output_file) as f:
            data = json.load(f)
        assert data["market_hours"] is False
        assert data["positions"] == []
        assert data["daily_pnl"] == "+$0.00"


class TestUpdate:
    """Test update cycle."""

    def test_update_success(self, monitor):
        """Test successful update cycle."""
        with patch.object(monitor, "write_positions_json", return_value=True):
            result = monitor.update()
            assert result is True


class TestDisconnect:
    """Test disconnection."""

    def test_disconnect(self, monitor):
        """Test disconnecting and canceling subscriptions."""
        monitor.account_id = "DU123456"
        monitor._pnl_subscription = SimpleNamespace()
        monitor.disconnect()
        monitor.account.cancel_pnl.assert_called_once_with("DU123456")
        monitor.session.disconnect.assert_called_once()
