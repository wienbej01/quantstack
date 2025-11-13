"""DataFrame validation utilities for critical tables."""

from typing import Any

import pandas as pd


class ValidationError(Exception):
    """Custom exception for validation failures."""

    pass


def validate_bars_dataframe(df: pd.DataFrame) -> None:
    """Validate bars DataFrame against required schema.

    Args:
        df: DataFrame to validate

    Raises:
        ValidationError: If validation fails
    """
    required_columns = {"ts", "symbol", "open", "high", "low", "close", "volume"}
    df_columns = set(df.columns)

    missing_columns = required_columns - df_columns
    if missing_columns:
        raise ValidationError(f"Missing required columns: {missing_columns}")

    # Validate data types
    if not pd.api.types.is_integer_dtype(df["ts"]):
        raise ValidationError("Column 'ts' must be integer type")

    if not pd.api.types.is_string_dtype(df["symbol"]):
        raise ValidationError("Column 'symbol' must be string type")

    price_columns = ["open", "high", "low", "close"]
    for col in price_columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            raise ValidationError(f"Column '{col}' must be numeric")
        if (df[col] < 0).any():
            raise ValidationError(f"Column '{col}' contains negative values")

    if not pd.api.types.is_integer_dtype(df["volume"]):
        raise ValidationError("Column 'volume' must be integer type")
    if (df["volume"] < 0).any():
        raise ValidationError("Column 'volume' contains negative values")

    # Validate OHLC relationships
    if (df["high"] < df["low"]).any():
        raise ValidationError("High values cannot be lower than low values")
    if (df["high"] < df["open"]).any():
        raise ValidationError("High values cannot be lower than open values")
    if (df["high"] < df["close"]).any():
        raise ValidationError("High values cannot be lower than close values")
    if (df["low"] > df["open"]).any():
        raise ValidationError("Low values cannot be higher than open values")
    if (df["low"] > df["close"]).any():
        raise ValidationError("Low values cannot be higher than close values")

    # Validate timestamps are positive
    if (df["ts"] <= 0).any():
        raise ValidationError("Timestamps must be positive")

    # Validate no duplicate (symbol, ts) pairs
    if df.duplicated(subset=["symbol", "ts"]).any():
        raise ValidationError("Duplicate (symbol, ts) pairs found")


def validate_signals_dataframe(df: pd.DataFrame) -> None:
    """Validate signals DataFrame against required schema.

    Args:
        df: DataFrame to validate

    Raises:
        ValidationError: If validation fails
    """
    required_columns = {"ts", "symbol", "side", "strength", "src"}
    df_columns = set(df.columns)

    missing_columns = required_columns - df_columns
    if missing_columns:
        raise ValidationError(f"Missing required columns: {missing_columns}")

    # Validate data types
    if not pd.api.types.is_integer_dtype(df["ts"]):
        raise ValidationError("Column 'ts' must be integer type")

    if not pd.api.types.is_string_dtype(df["symbol"]):
        raise ValidationError("Column 'symbol' must be string type")

    if not pd.api.types.is_string_dtype(df["side"]):
        raise ValidationError("Column 'side' must be string type")

    valid_sides = {"BUY", "SELL"}
    invalid_sides = set(df["side"].unique()) - valid_sides
    if invalid_sides:
        raise ValidationError(f"Invalid side values: {invalid_sides}. Must be one of {valid_sides}")

    if not pd.api.types.is_numeric_dtype(df["strength"]):
        raise ValidationError("Column 'strength' must be numeric")

    # Validate strength bounds [-1, 1]
    if (df["strength"] < -1).any() or (df["strength"] > 1).any():
        raise ValidationError("Signal strength must be between -1 and 1")

    if not pd.api.types.is_string_dtype(df["src"]):
        raise ValidationError("Column 'src' must be string type")

    # Validate timestamps are positive
    if (df["ts"] <= 0).any():
        raise ValidationError("Timestamps must be positive")


def validate_orders_dataframe(df: pd.DataFrame) -> None:
    """Validate orders DataFrame against required schema.

    Args:
        df: DataFrame to validate

    Raises:
        ValidationError: If validation fails
    """
    required_columns = {"ts", "symbol", "side", "qty"}
    df_columns = set(df.columns)

    missing_columns = required_columns - df_columns
    if missing_columns:
        raise ValidationError(f"Missing required columns: {missing_columns}")

    # Validate data types
    if not pd.api.types.is_integer_dtype(df["ts"]):
        raise ValidationError("Column 'ts' must be integer type")

    if not pd.api.types.is_string_dtype(df["symbol"]):
        raise ValidationError("Column 'symbol' must be string type")

    if not pd.api.types.is_string_dtype(df["side"]):
        raise ValidationError("Column 'side' must be string type")

    valid_sides = {"BUY", "SELL"}
    invalid_sides = set(df["side"].unique()) - valid_sides
    if invalid_sides:
        raise ValidationError(f"Invalid side values: {invalid_sides}. Must be one of {valid_sides}")

    if not pd.api.types.is_integer_dtype(df["qty"]):
        raise ValidationError("Column 'qty' must be integer type")
    if (df["qty"] <= 0).any():
        raise ValidationError("Order quantities must be positive")

    # Validate optional price columns
    price_columns = ["entry", "stop", "take_profit"]
    for col in price_columns:
        if col in df.columns:
            if not pd.api.types.is_numeric_dtype(df[col]):
                raise ValidationError(f"Column '{col}' must be numeric")
            if df[col].notna().any() and (df[col] <= 0).any():
                raise ValidationError(f"Column '{col}' must contain positive values")


def validate_trades_dataframe(df: pd.DataFrame) -> None:
    """Validate trades DataFrame against required schema.

    Args:
        df: DataFrame to validate

    Raises:
        ValidationError: If validation fails
    """
    required_columns = {
        "entry_ts",
        "exit_ts",
        "symbol",
        "side",
        "qty",
        "entry_px",
        "exit_px",
        "pnl",
    }
    df_columns = set(df.columns)

    missing_columns = required_columns - df_columns
    if missing_columns:
        raise ValidationError(f"Missing required columns: {missing_columns}")

    # Validate data types
    for ts_col in ["entry_ts", "exit_ts"]:
        if not pd.api.types.is_integer_dtype(df[ts_col]):
            raise ValidationError(f"Column '{ts_col}' must be integer type")

    if not pd.api.types.is_string_dtype(df["symbol"]):
        raise ValidationError("Column 'symbol' must be string type")

    if not pd.api.types.is_string_dtype(df["side"]):
        raise ValidationError("Column 'side' must be string type")

    valid_sides = {"BUY", "SELL"}
    invalid_sides = set(df["side"].unique()) - valid_sides
    if invalid_sides:
        raise ValidationError(f"Invalid side values: {invalid_sides}. Must be one of {valid_sides}")

    if not pd.api.types.is_integer_dtype(df["qty"]):
        raise ValidationError("Column 'qty' must be integer type")
    if (df["qty"] <= 0).any():
        raise ValidationError("Trade quantities must be positive")

    # Validate prices
    price_columns = ["entry_px", "exit_px"]
    for col in price_columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            raise ValidationError(f"Column '{col}' must be numeric")
        if (df[col] <= 0).any():
            raise ValidationError(f"Column '{col}' must contain positive values")

    if not pd.api.types.is_numeric_dtype(df["pnl"]):
        raise ValidationError("Column 'pnl' must be numeric")

    # Validate exit after entry
    if (df["exit_ts"] <= df["entry_ts"]).any():
        raise ValidationError("Exit timestamps must be after entry timestamps")

    # Validate timestamps are positive
    if (df["entry_ts"] <= 0).any() or (df["exit_ts"] <= 0).any():
        raise ValidationError("Timestamps must be positive")


def validate_risk_rejects_dataframe(df: pd.DataFrame) -> None:
    """Validate risk rejects DataFrame against required schema.

    Args:
        df: DataFrame to validate

    Raises:
        ValidationError: If validation fails
    """
    required_columns = {"reason_code", "limit_name", "value", "threshold"}
    df_columns = set(df.columns)

    missing_columns = required_columns - df_columns
    if missing_columns:
        raise ValidationError(f"Missing required columns: {missing_columns}")

    # Validate data types
    string_columns = ["reason_code", "limit_name"]
    for col in string_columns:
        if not pd.api.types.is_string_dtype(df[col]):
            raise ValidationError(f"Column '{col}' must be string type")

    numeric_columns = ["value", "threshold"]
    for col in numeric_columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            raise ValidationError(f"Column '{col}' must be numeric")


def validate_allocation_log_dataframe(df: pd.DataFrame) -> None:
    """Validate allocation log DataFrame against required schema.

    Args:
        df: DataFrame to validate

    Raises:
        ValidationError: If validation fails
    """
    required_columns = {"ts", "symbol", "allocation", "reason"}
    df_columns = set(df.columns)

    missing_columns = required_columns - df_columns
    if missing_columns:
        raise ValidationError(f"Missing required columns: {missing_columns}")

    # Validate data types
    if not pd.api.types.is_integer_dtype(df["ts"]):
        raise ValidationError("Column 'ts' must be integer type")

    if not pd.api.types.is_string_dtype(df["symbol"]):
        raise ValidationError("Column 'symbol' must be string type")

    if not pd.api.types.is_numeric_dtype(df["allocation"]):
        raise ValidationError("Column 'allocation' must be numeric")

    if not pd.api.types.is_string_dtype(df["reason"]):
        raise ValidationError("Column 'reason' must be string type")

    # Validate timestamps are positive
    if (df["ts"] <= 0).any():
        raise ValidationError("Timestamps must be positive")


def validate_inputs_checksum(data: dict[str, Any]) -> None:
    """Validate inputs checksum structure.

    Args:
        data: Dictionary to validate

    Raises:
        ValidationError: If validation fails
    """
    required_fields = {"bars_norm_hash", "features_hash", "config_hash", "seed"}
    missing_fields = required_fields - set(data.keys())

    if missing_fields:
        raise ValidationError(f"Missing required fields: {missing_fields}")

    # Validate hash fields
    hash_fields = ["bars_norm_hash", "features_hash", "sip_hash", "config_hash"]
    for field in hash_fields:
        if field in data:
            if not isinstance(data[field], str):
                raise ValidationError(f"Field '{field}' must be a string")
            if len(data[field]) < 8:
                raise ValidationError(f"Field '{field}' appears too short to be a valid hash")

    # Validate seed
    if not isinstance(data["seed"], int):
        raise ValidationError("Field 'seed' must be an integer")


def validate_dataframe_schema(df: pd.DataFrame, schema_type: str) -> None:
    """Validate DataFrame against schema type.

    Args:
        df: DataFrame to validate
        schema_type: Type of schema ('bars', 'signals', 'orders', 'trades', 'risk_rejects', 'allocation_log')

    Raises:
        ValidationError: If validation fails or unknown schema type
    """
    validators = {
        "bars": validate_bars_dataframe,
        "signals": validate_signals_dataframe,
        "orders": validate_orders_dataframe,
        "trades": validate_trades_dataframe,
        "risk_rejects": validate_risk_rejects_dataframe,
        "allocation_log": validate_allocation_log_dataframe,
    }

    if schema_type not in validators:
        raise ValidationError(f"Unknown schema type: {schema_type}")

    validators[schema_type](df)


def validate_pydantic_models(data_list: list[dict[str, Any]], model_class: type) -> list:
    """Validate list of dictionaries against Pydantic model.

    Args:
        data_list: List of dictionaries to validate
        model_class: Pydantic model class

    Returns:
        List of validated Pydantic models

    Raises:
        ValidationError: If validation fails
    """
    validated_models = []
    for i, data in enumerate(data_list):
        try:
            model = model_class(**data)
            validated_models.append(model)
        except Exception as e:
            raise ValidationError(f"Validation failed for item {i}: {str(e)}")

    return validated_models


# Convenience functions for common validation patterns
def validate_no_duplicates(df: pd.DataFrame, columns: list[str], entity_name: str = "row") -> None:
    """Validate that specified columns have no duplicate combinations."""
    if df.duplicated(subset=columns).any():
        raise ValidationError(f"Duplicate {entity_name} found for columns: {columns}")


def validate_positive_values(df: pd.DataFrame, columns: list[str]) -> None:
    """Validate that specified columns contain only positive values."""
    for col in columns:
        if col in df.columns and (df[col] <= 0).any():
            raise ValidationError(f"Column '{col}' contains non-positive values")


def validate_range(df: pd.DataFrame, column: str, min_val: float, max_val: float) -> None:
    """Validate that column values are within specified range."""
    if column not in df.columns:
        return

    if (df[column] < min_val).any() or (df[column] > max_val).any():
        raise ValidationError(f"Column '{column}' values must be between {min_val} and {max_val}")


def validate_enum_values(df: pd.DataFrame, column: str, valid_values: set[str]) -> None:
    """Validate that column values are within allowed enum values."""
    if column not in df.columns:
        return

    invalid_values = set(df[column].unique()) - valid_values
    if invalid_values:
        raise ValidationError(
            f"Column '{column}' contains invalid values: {invalid_values}. "
            f"Allowed values: {valid_values}"
        )
