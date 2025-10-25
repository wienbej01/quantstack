"""Unit tests for core validation functionality."""

import os
import sys

import pandas as pd
import pytest

# Add qx-core to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-core", "src"))

from qx_core.schemas import Bar
from qx_core.validators import (
    ValidationError,
    validate_allocation_log_dataframe,
    validate_bars_dataframe,
    validate_dataframe_schema,
    validate_enum_values,
    validate_inputs_checksum,
    validate_no_duplicates,
    validate_orders_dataframe,
    validate_positive_values,
    validate_pydantic_models,
    validate_range,
    validate_risk_rejects_dataframe,
    validate_signals_dataframe,
    validate_trades_dataframe,
)


class TestBarsValidation:
    """Test bars DataFrame validation."""

    def test_valid_bars_dataframe(self):
        """Test validation of valid bars DataFrame."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000, 1640995260000000000, 1640995320000000000],
                "symbol": ["AAPL", "GOOGL", "MSFT"],
                "open": [149.5, 2795.0, 299.0],
                "high": [150.5, 2805.0, 301.0],
                "low": [148.5, 2785.0, 298.0],
                "close": [150.0, 2800.0, 300.0],
                "volume": [1000, 500, 750],
            }
        )

        # Should not raise any exception
        validate_bars_dataframe(df)

    def test_missing_required_columns(self):
        """Test validation fails with missing required columns."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "open": [149.5],
                # Missing high, low, close, volume
            }
        )

        with pytest.raises(ValidationError, match="Missing required columns"):
            validate_bars_dataframe(df)

    def test_invalid_timestamps(self):
        """Test validation fails with invalid timestamps."""
        df = pd.DataFrame(
            {
                "ts": [-1],  # Negative timestamp
                "symbol": ["AAPL"],
                "open": [149.5],
                "high": [150.5],
                "low": [148.5],
                "close": [150.0],
                "volume": [1000],
            }
        )

        with pytest.raises(ValidationError, match="Timestamps must be positive"):
            validate_bars_dataframe(df)

    def test_negative_prices(self):
        """Test validation fails with negative prices."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "open": [149.5],
                "high": [-150.5],  # Negative high price
                "low": [148.5],
                "close": [150.0],
                "volume": [1000],
            }
        )

        with pytest.raises(ValidationError, match="contains negative values"):
            validate_bars_dataframe(df)

    def test_negative_volume(self):
        """Test validation fails with negative volume."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "open": [149.5],
                "high": [150.5],
                "low": [148.5],
                "close": [150.0],
                "volume": [-1000],  # Negative volume
            }
        )

        with pytest.raises(ValidationError, match="contains negative values"):
            validate_bars_dataframe(df)

    def test_ohlc_relationship_violations(self):
        """Test validation fails with OHLC relationship violations."""
        # High < Low
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "open": [149.5],
                "high": [148.0],  # High lower than low
                "low": [149.0],
                "close": [150.0],
                "volume": [1000],
            }
        )

        with pytest.raises(
            ValidationError, match="High values cannot be lower than low values"
        ):
            validate_bars_dataframe(df)

    def test_duplicate_symbol_ts_pairs(self):
        """Test validation fails with duplicate (symbol, ts) pairs."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000, 1640995200000000000],  # Duplicate timestamp
                "symbol": ["AAPL", "AAPL"],  # Same symbol
                "open": [149.5, 149.6],
                "high": [150.5, 150.6],
                "low": [148.5, 148.6],
                "close": [150.0, 150.1],
                "volume": [1000, 1001],
            }
        )

        with pytest.raises(ValidationError, match="Duplicate .* found"):
            validate_bars_dataframe(df)


class TestSignalsValidation:
    """Test signals DataFrame validation."""

    def test_valid_signals_dataframe(self):
        """Test validation of valid signals DataFrame."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000, 1640995260000000000],
                "symbol": ["AAPL", "GOOGL"],
                "side": ["BUY", "SELL"],
                "strength": [0.8, -0.6],
                "src": ["vwap_revert", "ml_signal"],
            }
        )

        # Should not raise any exception
        validate_signals_dataframe(df)

    def test_invalid_side_values(self):
        """Test validation fails with invalid side values."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "side": ["INVALID"],  # Invalid side
                "strength": [0.8],
                "src": ["vwap_revert"],
            }
        )

        with pytest.raises(ValidationError, match="Invalid side values"):
            validate_signals_dataframe(df)

    def test_strength_out_of_bounds(self):
        """Test validation fails with strength out of bounds."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "side": ["BUY"],
                "strength": [1.5],  # Strength > 1
                "src": ["vwap_revert"],
            }
        )

        with pytest.raises(
            ValidationError, match="Signal strength must be between -1 and 1"
        ):
            validate_signals_dataframe(df)


class TestOrdersValidation:
    """Test orders DataFrame validation."""

    def test_valid_orders_dataframe(self):
        """Test validation of valid orders DataFrame."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "side": ["BUY"],
                "qty": [100],
                "type": ["MKT"],
                "entry": [150.0],
                "stop": [145.0],
            }
        )

        # Should not raise any exception
        validate_orders_dataframe(df)

    def test_negative_quantity(self):
        """Test validation fails with negative quantity."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "side": ["BUY"],
                "qty": [-100],  # Negative quantity
                "type": ["MKT"],
            }
        )

        with pytest.raises(ValidationError, match="Order quantities must be positive"):
            validate_orders_dataframe(df)

    def test_negative_price_fields(self):
        """Test validation fails with negative price fields."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "side": ["BUY"],
                "qty": [100],
                "type": ["LMT"],
                "entry": [-150.0],  # Negative price
            }
        )

        with pytest.raises(ValidationError, match="must contain positive values"):
            validate_orders_dataframe(df)


class TestTradesValidation:
    """Test trades DataFrame validation."""

    def test_valid_trades_dataframe(self):
        """Test validation of valid trades DataFrame."""
        df = pd.DataFrame(
            {
                "entry_ts": [1640995200000000000],
                "exit_ts": [1640995800000000000],
                "symbol": ["AAPL"],
                "side": ["BUY"],
                "qty": [100],
                "entry_px": [150.0],
                "exit_px": [152.0],
                "pnl": [200.0],
                "fees": [1.0],
                "slippage_est": [0.5],
            }
        )

        # Should not raise any exception
        validate_trades_dataframe(df)

    def test_exit_before_entry(self):
        """Test validation fails when exit is before entry."""
        df = pd.DataFrame(
            {
                "entry_ts": [1640995800000000000],  # Later timestamp
                "exit_ts": [1640995200000000000],  # Earlier timestamp
                "symbol": ["AAPL"],
                "side": ["BUY"],
                "qty": [100],
                "entry_px": [150.0],
                "exit_px": [152.0],
                "pnl": [200.0],
            }
        )

        with pytest.raises(
            ValidationError, match="Exit timestamps must be after entry timestamps"
        ):
            validate_trades_dataframe(df)


class TestRiskRejectsValidation:
    """Test risk rejects DataFrame validation."""

    def test_valid_risk_rejects_dataframe(self):
        """Test validation of valid risk rejects DataFrame."""
        df = pd.DataFrame(
            {
                "reason_code": ["MAX_POSITION_SIZE"],
                "limit_name": ["max_position_value"],
                "value": [150000.0],
                "threshold": [100000.0],
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
            }
        )

        # Should not raise any exception
        validate_risk_rejects_dataframe(df)


class TestAllocationLogValidation:
    """Test allocation log DataFrame validation."""

    def test_valid_allocation_log_dataframe(self):
        """Test validation of valid allocation log DataFrame."""
        df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "allocation": [0.25],
                "reason": ["rebalance"],
            }
        )

        # Should not raise any exception
        validate_allocation_log_dataframe(df)


class TestInputsChecksumValidation:
    """Test inputs checksum validation."""

    def test_valid_inputs_checksum(self):
        """Test validation of valid inputs checksum."""
        data = {
            "bars_norm_hash": "a" * 64,
            "features_hash": "b" * 64,
            "config_hash": "c" * 64,
            "seed": 42,
            "sip_hash": "d" * 64,
        }

        # Should not raise any exception
        validate_inputs_checksum(data)

    def test_missing_required_fields(self):
        """Test validation fails with missing required fields."""
        data = {
            "bars_norm_hash": "a" * 64,
            "features_hash": "b" * 64,
            # Missing config_hash and seed
        }

        with pytest.raises(ValidationError, match="Missing required fields"):
            validate_inputs_checksum(data)

    def test_short_hash(self):
        """Test validation fails with hash that's too short."""
        data = {
            "bars_norm_hash": "short",  # Too short
            "features_hash": "b" * 64,
            "config_hash": "c" * 64,
            "seed": 42,
        }

        with pytest.raises(ValidationError, match="appears too short"):
            validate_inputs_checksum(data)


class TestPydanticModelsValidation:
    """Test Pydantic model validation."""

    def test_valid_bar_model(self):
        """Test validation of valid Bar model."""
        bar_data = {
            "ts": 1640995200000000000,
            "symbol": "AAPL",
            "open": 149.5,
            "high": 150.5,
            "low": 148.5,
            "close": 150.0,
            "volume": 1000,
        }

        bars = validate_pydantic_models([bar_data], Bar)
        assert len(bars) == 1
        assert isinstance(bars[0], Bar)
        assert bars[0].symbol == "AAPL"

    def test_invalid_bar_model(self):
        """Test validation fails with invalid Bar model."""
        bar_data = {
            "ts": -1,  # Invalid timestamp
            "symbol": "AAPL",
            "open": 149.5,
            "high": 150.5,
            "low": 148.5,
            "close": 150.0,
            "volume": 1000,
        }

        with pytest.raises(ValidationError, match="Validation failed"):
            validate_pydantic_models([bar_data], Bar)


class TestUtilityValidators:
    """Test utility validation functions."""

    def test_validate_no_duplicates(self):
        """Test duplicate validation."""
        df = pd.DataFrame(
            {"symbol": ["AAPL", "GOOGL", "AAPL"], "ts": [1, 2, 3]}  # Duplicate symbol
        )

        with pytest.raises(ValidationError, match="Duplicate row found"):
            validate_no_duplicates(df, ["symbol"])

    def test_validate_positive_values(self):
        """Test positive values validation."""
        df = pd.DataFrame(
            {"symbol": ["AAPL", "GOOGL"], "price": [150.0, -100.0]}  # Negative price
        )

        with pytest.raises(ValidationError, match="contains non-positive values"):
            validate_positive_values(df, ["price"])

    def test_validate_range(self):
        """Test range validation."""
        df = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL"],
                "strength": [0.8, 1.5],  # Outside [-1, 1] range
            }
        )

        with pytest.raises(ValidationError, match="must be between -1.0 and 1.0"):
            validate_range(df, "strength", -1.0, 1.0)

    def test_validate_enum_values(self):
        """Test enum values validation."""
        df = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL"],
                "side": ["BUY", "INVALID"],  # Invalid enum value
            }
        )

        valid_sides = {"BUY", "SELL"}

        with pytest.raises(ValidationError, match="contains invalid values"):
            validate_enum_values(df, "side", valid_sides)


class TestDataFrameSchemaValidation:
    """Test generic DataFrame schema validation."""

    def test_valid_schema_types(self):
        """Test validation with all valid schema types."""
        bars_df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "open": [149.5],
                "high": [150.5],
                "low": [148.5],
                "close": [150.0],
                "volume": [1000],
            }
        )

        signals_df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "side": ["BUY"],
                "strength": [0.8],
                "src": ["test"],
            }
        )

        # Should not raise any exception
        validate_dataframe_schema(bars_df, "bars")
        validate_dataframe_schema(signals_df, "signals")

    def test_unknown_schema_type(self):
        """Test validation fails with unknown schema type."""
        df = pd.DataFrame({"test": [1]})

        with pytest.raises(ValidationError, match="Unknown schema type"):
            validate_dataframe_schema(df, "unknown_type")


class TestErrorMessages:
    """Test validation error messages."""

    def test_validation_error_inheritance(self):
        """Test that ValidationError is properly raised."""

        def failing_validator():
            raise ValidationError("Test error message")

        with pytest.raises(ValidationError) as exc_info:
            failing_validator()

        assert "Test error message" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
