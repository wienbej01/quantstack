"""
Unit tests for position_monitor.models.
"""

import pytest

from position_monitor.models import PnLData, Position, PositionsOutput


class TestPosition:
    """Test Position dataclass."""

    def test_position_creation(self):
        """Test creating a Position."""
        pos = Position(
            symbol="AAPL",
            quantity=100,
            avg_price=150.0,
            current_price=155.0,
            unrealized_pnl=500.0,
            market_value=15500.0,
        )
        assert pos.symbol == "AAPL"
        assert pos.quantity == 100
        assert pos.unrealized_pnl == 500.0

    def test_pnl_display_positive(self):
        """Test P&L display formatting for positive values."""
        pos = Position(
            symbol="AAPL",
            quantity=100,
            avg_price=150.0,
            current_price=155.0,
            unrealized_pnl=500.0,
            market_value=15500.0,
        )
        assert pos.pnl_display == "+$500.00"

    def test_pnl_display_negative(self):
        """Test P&L display formatting for negative values."""
        pos = Position(
            symbol="AAPL",
            quantity=100,
            avg_price=150.0,
            current_price=145.0,
            unrealized_pnl=-500.0,
            market_value=14500.0,
        )
        assert pos.pnl_display == "-$500.00"

    def test_pnl_value_positive(self):
        """Test P&L value formatting for positive values."""
        pos = Position(
            symbol="AAPL",
            quantity=100,
            avg_price=150.0,
            current_price=155.0,
            unrealized_pnl=500.0,
            market_value=15500.0,
        )
        assert pos.pnl_value == "+500.00"

    def test_pnl_value_negative(self):
        """Test P&L value formatting for negative values."""
        pos = Position(
            symbol="AAPL",
            quantity=100,
            avg_price=150.0,
            current_price=145.0,
            unrealized_pnl=-500.0,
            market_value=14500.0,
        )
        assert pos.pnl_value == "-500.00"

    def test_color_green(self):
        """Test color code for positive P&L."""
        pos = Position(
            symbol="AAPL",
            quantity=100,
            avg_price=150.0,
            current_price=155.0,
            unrealized_pnl=500.0,
            market_value=15500.0,
        )
        assert pos.color == "#00FF00"

    def test_color_red(self):
        """Test color code for negative P&L."""
        pos = Position(
            symbol="AAPL",
            quantity=100,
            avg_price=150.0,
            current_price=145.0,
            unrealized_pnl=-500.0,
            market_value=14500.0,
        )
        assert pos.color == "#FF3333"

    def test_color_yellow(self):
        """Test color code for zero P&L."""
        pos = Position(
            symbol="AAPL",
            quantity=100,
            avg_price=150.0,
            current_price=150.0,
            unrealized_pnl=0.0,
            market_value=15000.0,
        )
        assert pos.color == "#FFFF00"


class TestPnLData:
    """Test PnLData dataclass."""

    def test_pnl_data_creation(self):
        """Test creating PnLData."""
        pnl = PnLData(daily_pnl=1234.56)
        assert pnl.daily_pnl == 1234.56

    def test_pnl_data_with_defaults(self):
        """Test creating PnLData with default values."""
        pnl = PnLData(daily_pnl=100.0)
        assert pnl.realized_pnl == 0.0
        assert pnl.unrealized_pnl == 0.0

    def test_daily_display_positive(self):
        """Test daily display formatting for positive values."""
        pnl = PnLData(daily_pnl=1234.56)
        assert pnl.daily_display == "+$1234.56"

    def test_daily_display_negative(self):
        """Test daily display formatting for negative values."""
        pnl = PnLData(daily_pnl=-567.89)
        assert pnl.daily_display == "-$567.89"

    def test_daily_value_positive(self):
        """Test daily value formatting for positive values."""
        pnl = PnLData(daily_pnl=1234.56)
        assert pnl.daily_value == "+$1234.56"

    def test_daily_value_negative(self):
        """Test daily value formatting for negative values."""
        pnl = PnLData(daily_pnl=-567.89)
        assert pnl.daily_value == "-$567.89"

    def test_color_green(self):
        """Test color code for positive P&L."""
        pnl = PnLData(daily_pnl=100.0)
        assert pnl.color == "#00FF00"

    def test_color_red(self):
        """Test color code for negative P&L."""
        pnl = PnLData(daily_pnl=-100.0)
        assert pnl.color == "#FF3333"

    def test_color_yellow(self):
        """Test color code for zero P&L."""
        pnl = PnLData(daily_pnl=0.0)
        assert pnl.color == "#FFFF00"


class TestPositionsOutput:
    """Test PositionsOutput dataclass."""

    def test_positions_output_to_dict(self):
        """Test converting PositionsOutput to dictionary."""
        output = PositionsOutput(
            positions=[
                {"symbol": "AAPL", "pnl": "+500.00", "color": "#00FF00"},
                {"symbol": "TSLA", "pnl": "-200.00", "color": "#FF3333"},
            ],
            daily_pnl="+$300.00",
            daily_color="#00FF00",
            market_hours=True,
        )
        result = output.to_dict()
        assert result == {
            "positions": [
                {"symbol": "AAPL", "pnl": "+500.00", "color": "#00FF00"},
                {"symbol": "TSLA", "pnl": "-200.00", "color": "#FF3333"},
            ],
            "daily_pnl": "+$300.00",
            "daily_color": "#00FF00",
            "market_hours": True,
        }

    def test_positions_output_empty(self):
        """Test PositionsOutput with empty positions."""
        output = PositionsOutput(
            positions=[],
            daily_pnl="+$0.00",
            daily_color="#FFFF00",
            market_hours=False,
        )
        result = output.to_dict()
        assert result["positions"] == []
        assert result["market_hours"] is False
