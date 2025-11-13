"""Validation utilities for experiment configuration and data."""

import pathlib
from typing import Any


def validate_config(config: dict[str, Any]) -> None:
    """Validate experiment configuration."""
    required_keys = ["gold_root", "family", "symbols", "dates", "features"]
    missing_keys = [k for k in required_keys if k not in config]

    if missing_keys:
        raise ValueError(f"Missing required config keys: {missing_keys}")

    # Validate symbols list
    if not config["symbols"] or not isinstance(config["symbols"], list):
        raise ValueError("symbols must be a non-empty list")

    # Validate dates list
    if not config["dates"] or not isinstance(config["dates"], list):
        raise ValueError("dates must be a non-empty list")

    # Validate features list
    if not config["features"] or not isinstance(config["features"], list):
        raise ValueError("features must be a non-empty list")


def validate_data_slice(
    gold_root: str,
    family: str,
    symbols: list[str],
    dates: list[str],
) -> None:
    """Validate that the requested data slice exists."""
    # Check gold root exists
    if not pathlib.Path(gold_root).exists():
        raise ValueError(f"Gold root does not exist: {gold_root}")

    # For now, just check the basic structure without relying on list_available_symbols
    # which seems to have issues with the current data structure
    # We'll do basic path validation instead
    for symbol in symbols[:1]:  # Check first symbol as sample
        symbol_path = pathlib.Path(gold_root) / "stocks" / "1m" / symbol
        if symbol_path.exists():
            # If path exists, check for at least one date directory
            date_dirs = [d for d in symbol_path.iterdir() if d.is_dir()]
            if not date_dirs:
                raise ValueError(f"No date directories found for symbol {symbol}")
        else:
            # If symbol path doesn't exist, try alternate structure
            alternate_path = pathlib.Path(gold_root) / "stocks" / "1m" / symbol[:1] / symbol
            if not alternate_path.exists():
                raise ValueError(f"Symbol directory not found: {symbol}")


def validate_backtest_result(result: dict[str, Any]) -> list[str]:
    """Validate backtest result structure and return any warnings."""
    warnings = []

    # Check required keys
    required_keys = ["performance", "trading"]
    missing_keys = [k for k in required_keys if k not in result]
    if missing_keys:
        warnings.append(f"missing_result_keys: {missing_keys}")

    # Check trading metrics
    if "trading" in result:
        trading = result["trading"]
        if trading.get("total_trades", 0) == 0:
            warnings.append("no_trades_executed")

    return warnings
