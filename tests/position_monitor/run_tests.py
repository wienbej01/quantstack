"""
Run position monitor tests directly (workaround for pytest import issue).
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Now import and run tests
from position_monitor.models import PnLData, Position, PositionsOutput


def test_position_creation():
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
    print("✓ test_position_creation passed")


def test_pnl_display_positive():
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
    assert pos.pnl_value == "+500.00"
    assert pos.color == "#00FF00"
    print("✓ test_pnl_display_positive passed")


def test_pnl_display_negative():
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
    assert pos.pnl_value == "-500.00"
    assert pos.color == "#FF3333"
    print("✓ test_pnl_display_negative passed")


def test_pnl_data():
    """Test PnLData dataclass."""
    pnl = PnLData(daily_pnl=1234.56)
    assert pnl.daily_display == "+$1234.56"
    assert pnl.daily_value == "+$1234.56"
    assert pnl.color == "#00FF00"
    print("✓ test_pnl_data passed")


def test_positions_output():
    """Test PositionsOutput dataclass."""
    output = PositionsOutput(
        positions=[
            {"symbol": "AAPL", "pnl": "+500.00", "color": "#00FF00"},
        ],
        daily_pnl="+$300.00",
        daily_color="#00FF00",
        market_hours=True,
    )
    result = output.to_dict()
    assert result["daily_pnl"] == "+$300.00"
    assert result["market_hours"] is True
    print("✓ test_positions_output passed")


if __name__ == "__main__":
    print("Running position monitor tests...")
    test_position_creation()
    test_pnl_display_positive()
    test_pnl_display_negative()
    test_pnl_data()
    test_positions_output()
    print("\n✅ All tests passed!")
