"""qx-data: Gold data loader for read-only access to canonical bars."""

from .gold_loader import (
    OPTIONAL,
    REQUIRED,
    get_bars_hash,
    list_available_dates,
    list_available_symbols,
    load_bars,
)

__version__ = "0.1.0"

__all__ = [
    "load_bars",
    "list_available_symbols",
    "list_available_dates",
    "get_bars_hash",
    "REQUIRED",
    "OPTIONAL",
]
