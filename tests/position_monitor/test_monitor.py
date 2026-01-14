"""
Unit tests for position_monitor.monitor.
"""

import json
from datetime import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest

from position_monitor.models import PnLData, Position
from position_monitor.monitor import PositionMonitor


@pytest.fixture
def mock_platform_client():
    """Mock IBKRPlatformClient."""
    client = MagicMock()
    client.is_healthy.return_value = True
    client.register.return_value = True
    client.heartbeat.return_value = True
    client.get_positions.return_value = []
    client.get_pnl.return_value = {}
    return client


@pytest.fixture
def temp_output_file(tmp_path):
    """Create a temporary output file."""
    return tmp_path / "positions.json"


@pytest.fixture
def monitor(mock_platform_client, temp_output_file):
    """Create a PositionMonitor with mocked client."""
    with patch(
        "position_monitor.monitor.IBKRPlatformClient", return_value=mock_platform_client
    ):
        mon = PositionMonitor(
            platform_url="http://127.0.0.1:8000",
            output_file=str(temp_output_file),
        )
        mon.client = mock_platform_client
        return mon


class TestPositionMonitorInit:
    """Test PositionMonitor initialization."""

    def test_init_defaults(self, mock_platform_client):
        """Test initialization with default values."""
        with patch(
            "position_monitor.monitor.IBKRPlatformClient",
            return_value=mock_platform_client,
        ):
            mon = PositionMonitor()
            assert mon.platform_url == "http://127.0.0.1:8000"
            assert str(mon.output_file) == "/tmp/positions.json"
            assert mon.account_id is None

    def test_init_custom(self, mock_platform_client, temp_output_file):
        """Test initialization with custom values."""
        with patch(
            "position_monitor.monitor.IBKRPlatformClient",
            return_value=mock_platform_client,
        ):
            mon = PositionMonitor(
                platform_url="http://localhost:9000",
                output_file=str(temp_output_file),
                account_id="U1234567",
            )
            assert mon.platform_url == "http://localhost:9000"
            assert mon.output_file == temp_output_file
            assert mon.account_id == "U1234567"


class TestPositionMonitorConnect:
    """Test PositionMonitor connection."""

    def test_connect_success(self, monitor, mock_platform_client):
        """Test successful connection."""
        result = monitor.connect()
        assert result is True
        assert monitor._registered is True
        mock_platform_client.register.assert_called_once_with(
            endpoints=["positions", "pnl"]
        )

    def test_connect_unhealthy(self, monitor, mock_platform_client):
        """Test connection when platform is unhealthy."""
        mock_platform_client.is_healthy.return_value = False
        result = monitor.connect()
        assert result is False
        assert monitor._registered is False
        mock_platform_client.register.assert_not_called()

    def test_connect_register_fails(self, monitor, mock_platform_client):
        """Test connection when registration fails."""
        mock_platform_client.register.return_value = False
        result = monitor.connect()
        assert result is False
        assert monitor._registered is False


class TestMarketHours:
    """Test market hours detection."""

    @patch("position_monitor.monitor.datetime")
    def test_is_market_hours_true(self, mock_datetime, monitor):
        """Test market hours detection during market hours."""
        # 10:00 AM ET is within market hours (9:30 AM - 4:30 PM ET)
        mock_datetime.now.return_value.time.return_value = time(
            10, 0, tzinfo=ZoneInfo("America/New_York")
        )
        assert monitor.is_market_hours() is True

    @patch("position_monitor.monitor.datetime")
    def test_is_market_hours_false_before(self, mock_datetime, monitor):
        """Test market hours detection before market opens."""
        # 8:00 AM ET is before market hours
        mock_datetime.now.return_value.time.return_value = time(
            8, 0, tzinfo=ZoneInfo("America/New_York")
        )
        assert monitor.is_market_hours() is False

    @patch("position_monitor.monitor.datetime")
    def test_is_market_hours_false_after(self, mock_datetime, monitor):
        """Test market hours detection after market close."""
        # 5:00 PM ET is after market hours
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

    def test_get_open_positions_success(self, monitor, mock_platform_client):
        """Test successfully getting positions."""
        monitor.account_id = "U1234567"
        mock_platform_client.get_positions.return_value = [
            {
                "contractdesc": "AAPL",
                "pos": "100",
                "avgpx": "150.0",
                "mark_price": "155.0",
                "mktval": "15500.0",
                "unrealized_pnl": "500.0",
            },
            {
                "contractdesc": "TSLA",
                "pos": "-50",
                "avgpx": "200.0",
                "mark_price": "195.0",
                "mktval": "-9750.0",
                "unrealized_pnl": "250.0",
            },
        ]

        positions = monitor.get_open_positions()
        assert len(positions) == 2
        assert positions[0].symbol == "AAPL"
        assert positions[0].quantity == 100
        assert positions[0].unrealized_pnl == 500.0
        assert positions[1].symbol == "TSLA"
        assert positions[1].quantity == -50

    def test_get_open_positions_skip_zero_quantity(self, monitor, mock_platform_client):
        """Test that positions with zero quantity are skipped."""
        monitor.account_id = "U1234567"
        mock_platform_client.get_positions.return_value = [
            {
                "contractdesc": "AAPL",
                "pos": "100",
                "avgpx": "150.0",
                "mark_price": "155.0",
                "mktval": "15500.0",
            },
            {
                "contractdesc": "TSLA",
                "pos": "0",  # Zero quantity
                "avgpx": "200.0",
                "mark_price": "195.0",
                "mktval": "0",
            },
        ]

        positions = monitor.get_open_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "AAPL"


class TestGetDailyPnL:
    """Test getting daily P&L."""

    def test_get_daily_pnl_upnl(self, monitor, mock_platform_client):
        """Test getting daily P&L from upnl field."""
        mock_platform_client.get_pnl.return_value = {"upnl": "1234.56"}
        pnl = monitor.get_daily_pnl()
        assert pnl.daily_pnl == 1234.56

    def test_get_daily_pnl_unrealized_pnl(self, monitor, mock_platform_client):
        """Test getting daily P&L from unrealized_pnl field."""
        mock_platform_client.get_pnl.return_value = {"unrealized_pnl": "-567.89"}
        pnl = monitor.get_daily_pnl()
        assert pnl.daily_pnl == -567.89

    def test_get_daily_pnl_dailypnl(self, monitor, mock_platform_client):
        """Test getting daily P&L from dailypnl field."""
        mock_platform_client.get_pnl.return_value = {"dailypnl": "100.0"}
        pnl = monitor.get_daily_pnl()
        assert pnl.daily_pnl == 100.0

    def test_get_daily_pnl_no_field(self, monitor, mock_platform_client):
        """Test getting daily P&L when no recognized field exists."""
        mock_platform_client.get_pnl.return_value = {"other_field": "100.0"}
        pnl = monitor.get_daily_pnl()
        assert pnl.daily_pnl == 0.0


class TestWritePositionsJson:
    """Test writing positions to JSON."""

    def test_write_positions_json_market_hours(
        self, monitor, mock_platform_client, temp_output_file
    ):
        """Test writing JSON during market hours."""
        monitor.account_id = "U1234567"

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

        # Verify file contents
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

        # Verify file contents
        with open(temp_output_file) as f:
            data = json.load(f)
        assert data["market_hours"] is False
        assert data["positions"] == []
        assert data["daily_pnl"] == "+$0.00"


class TestUpdate:
    """Test update cycle."""

    def test_update_success(self, monitor, mock_platform_client):
        """Test successful update cycle."""
        monitor._registered = True
        with patch.object(monitor, "write_positions_json", return_value=True):
            result = monitor.update()
            assert result is True
            mock_platform_client.heartbeat.assert_called_once()

    def test_update_not_registered(self, monitor, mock_platform_client):
        """Test update when not registered."""
        monitor._registered = False
        with patch.object(monitor, "write_positions_json", return_value=True):
            result = monitor.update()
            assert result is True
            mock_platform_client.heartbeat.assert_not_called()


class TestDisconnect:
    """Test disconnection."""

    def test_disconnect_registered(self, monitor, mock_platform_client):
        """Test disconnecting when registered."""
        monitor._registered = True
        monitor.disconnect()
        assert monitor._registered is False
        mock_platform_client.unregister.assert_called_once()

    def test_disconnect_not_registered(self, monitor, mock_platform_client):
        """Test disconnecting when not registered."""
        monitor._registered = False
        monitor.disconnect()
        assert monitor._registered is False
        mock_platform_client.unregister.assert_not_called()
