"""Gold loader for read-only access to normalized bars."""

import glob
import logging
import os
import time
from datetime import datetime

import pandas as pd
import pyarrow.parquet as pq

from qx_core.hashers import hash_dataframe
from qx_core.validators import ValidationError, validate_bars_dataframe

logger = logging.getLogger(__name__)

REQUIRED = ["ts", "symbol", "open", "high", "low", "close", "volume"]
OPTIONAL = ["trades", "vwap", "session", "date_et"]


def _symbol_variants(symbol: str) -> list[str]:
    """Return common case variants for a symbol for case-insensitive lookups."""

    variants = [symbol]
    upper = symbol.upper()
    lower = symbol.lower()
    if upper not in variants:
        variants.append(upper)
    if lower not in variants:
        variants.append(lower)
    return variants


def load_bars(
    root: str,
    family: str,
    symbols: list[str],
    dates: list[str],
    validate: bool = True,
    sort: bool = True,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Load and normalize bars from Gold parquet files.

    Args:
        root: Path to Gold root directory
        family: Data family (e.g., 'bars_1m')
        symbols: List of symbols to load
        dates: List of date strings in YYYY-MM-DD format
        validate: Whether to validate the resulting DataFrame
        sort: Whether to sort by [symbol, ts]
        columns: Optional list of columns to select (all columns used if None)

    Returns:
        Normalized DataFrame with canonical schema

    Raises:
        RuntimeError: If no parquet files could be read
        ValidationError: If validation fails and validate=True
    """
    if not symbols:
        raise ValueError("Symbols list cannot be empty")
    if not dates:
        raise ValueError("Dates list cannot be empty")

    internal_family = "bars_1m" if family in {"stocks", "bars_1m"} else family

    total_symbols = len(symbols)
    total_dates = len(dates)
    log_progress = total_symbols >= 200
    load_started = time.monotonic()
    logger.info(
        "Loading bars: %d symbols, %d dates, family=%s",
        total_symbols,
        total_dates,
        internal_family,
    )

    dfs: list[pd.DataFrame] = []
    files_attempted = 0

    month_filters = {
        d[:7]
        for d in dates
        if len(d) >= 7 and d[4] == "-" and d[:4].isdigit() and d[5:7].isdigit()
    }
    day_filters = {
        d
        for d in dates
        if len(d) >= 10 and d[4] == "-" and d[7] == "-" and d[:4].isdigit()
    }

    for idx, symbol in enumerate(symbols, 1):
        seen_paths: set[str] = set()

        for date_str in dates:
            paths = _get_parquet_paths(root, internal_family, symbol, date_str)
            if not paths:
                files_attempted += 1
            for path in paths:
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                files_attempted += 1
                try:
                    df = _read_parquet_with_validation(path, symbol, columns)
                except Exception as e:
                    print(f"Warning: failed to read {path}: {e}")
                    continue

                if df.empty:
                    continue

                if internal_family == "bars_1m" and (month_filters or day_filters):
                    ts_index = pd.to_datetime(df["ts"], unit="ns")
                    df["_date_month"] = ts_index.dt.strftime("%Y-%m")
                    df["_date_day"] = ts_index.dt.strftime("%Y-%m-%d")
                    mask_month = (
                        df["_date_month"].isin(month_filters)
                        if month_filters
                        else False
                    )
                    mask_day = (
                        df["_date_day"].isin(day_filters) if day_filters else False
                    )
                    combined_mask = mask_month | mask_day
                    if combined_mask.any():
                        df = df[combined_mask]
                    df = df.drop(columns=["_date_month", "_date_day"])
                    if df.empty:
                        continue

                dfs.append(df)

        if log_progress and (idx == 1 or idx % 200 == 0 or idx == total_symbols):
            logger.info(
                "Loaded symbols %d/%d (files attempted %d, elapsed %.1fs)",
                idx,
                total_symbols,
                files_attempted,
                time.monotonic() - load_started,
            )

    if not dfs:
        raise RuntimeError(
            "No parquet files could be read for symbols "
            f"{symbols} on dates {dates} under root '{root}' (family='{family}')."
        )

    combined = pd.concat(dfs, ignore_index=True)
    normalized = _normalize_in_memory(combined)
    # Deduplicate symbol/timestamp pairs for stable downstream processing
    normalized = normalized.drop_duplicates(subset=["symbol", "ts"]).reset_index(
        drop=True
    )

    # Validate schema if requested
    if validate:
        try:
            validate_bars_dataframe(normalized)
        except ValidationError as e:
            raise ValidationError(f"Loaded bars validation failed: {e}")

    # Sort for determinism if requested
    if sort:
        normalized = normalized.sort_values(["symbol", "ts"]).reset_index(drop=True)

    return normalized


def list_available_symbols(root: str, family: str) -> set[str]:
    """List all available symbols in the Gold data for a given family.

    Args:
        root: Path to Gold root directory
        family: Data family (e.g., 'bars_1m')

    Returns:
        Set of available symbol names
    """
    search_roots = []
    if family in {"bars_1m", "stocks"}:
        for base in [root, os.path.join(root, "gold")]:
            path = os.path.join(base, "stocks", "1m")
            if os.path.exists(path):
                search_roots.append(path)
        symbols = set()
        for base_path in search_roots:
            try:
                entries = list(os.scandir(base_path))
            except FileNotFoundError:
                continue
            for entry in entries:
                if not entry.is_dir():
                    continue
                name = entry.name
                # Two layouts are supported:
                # 1) <base>/<LETTER>/<SYMBOL>/...
                # 2) <base>/<SYMBOL>/...
                if len(name) == 1 and name.isalpha():
                    try:
                        for symbol_entry in os.scandir(entry.path):
                            if symbol_entry.is_dir():
                                symbols.add(symbol_entry.name)
                    except FileNotFoundError:
                        continue
                else:
                    symbols.add(name)
            if symbols:
                break
        return symbols
    else:
        symbols = set()
        candidate_bases = [
            os.path.join(root, family),
            os.path.join(root, "gold", family),
        ]
        for family_path in candidate_bases:
            if not os.path.exists(family_path):
                continue
            for item in os.listdir(family_path):
                if item.startswith("symbol="):
                    symbol = item.split("=", 1)[1]
                    symbols.add(symbol)
        return symbols


def list_available_dates(root: str, family: str, symbol: str) -> set[str]:
    """List all available dates for a symbol in the Gold data.

    Args:
        root: Path to Gold root directory
        family: Data family (e.g., 'bars_1m')
        symbol: Symbol name

    Returns:
        Set of available date strings in YYYY-MM format for 1m bars, YYYY-MM-DD for others
    """
    if family in {"bars_1m", "stocks"}:
        dates = set()
        candidate_bases = [
            os.path.join(root, "stocks", "1m", symbol),
            os.path.join(root, "gold", "stocks", "1m", symbol),
        ]
        for base_path in candidate_bases:
            if not os.path.exists(base_path):
                continue
            try:
                year_dirs = os.listdir(base_path)
            except FileNotFoundError:
                continue
            for year_dir in year_dirs:
                year_path = os.path.join(base_path, year_dir)
                try:
                    parquet_files = os.listdir(year_path)
                except FileNotFoundError:
                    continue
                for parquet_file in parquet_files:
                    if parquet_file.endswith(".parquet"):
                        date = parquet_file[:-8]
                        dates.add(date)
            if dates:
                break
        return dates
    else:
        # Look for date= partitions
        dates = set()
        candidate_paths = [
            os.path.join(root, family, f"symbol={symbol}"),
            os.path.join(root, "gold", family, f"symbol={symbol}"),
        ]
        for symbol_path in candidate_paths:
            if not os.path.exists(symbol_path):
                continue
            for item in os.listdir(symbol_path):
                if item.startswith("date="):
                    date = item.split("=", 1)[1]
                    dates.add(date)
        return dates


def get_bars_hash(root: str, family: str, symbols: list[str], dates: list[str]) -> str:
    """Get hash of bars data without loading full DataFrame.

    Args:
        root: Path to Gold root directory
        family: Data family (e.g., 'bars_1m')
        symbols: List of symbols to load
        dates: List of date strings

    Returns:
        Hash string of the bars data
    """
    # Load minimal data for hashing
    df = load_bars(root, family, symbols, dates, validate=False)
    return hash_dataframe(df)


def _get_parquet_paths(root: str, family: str, symbol: str, date_str: str) -> list[str]:
    """Resolve parquet file paths for a given data family/date."""
    candidates: list[str] = []
    if family == "bars_1m":
        try:
            parsed = datetime.strptime(date_str[:7], "%Y-%m")
        except ValueError as exc:
            raise ValueError(f"Invalid date format for bars_1m: {date_str}") from exc

        base_patterns = [
            os.path.join(root, "stocks", "1m"),
            os.path.join(root, "gold", "stocks", "1m"),
        ]
        for base in base_patterns:
            for symbol_variant in _symbol_variants(symbol):
                pattern = os.path.join(
                    base,
                    symbol_variant,
                    f"{parsed.year:04d}",
                    f"{parsed.year:04d}-{parsed.month:02d}.parquet",
                )
                matches = glob.glob(pattern)
                candidates.extend(matches)
                if matches:
                    break
            if candidates:
                break
    else:
        base_patterns = [
            os.path.join(root, family),
            os.path.join(root, "gold", family),
        ]
        for base in base_patterns:
            for symbol_variant in _symbol_variants(symbol):
                pattern = os.path.join(
                    base,
                    f"symbol={symbol_variant}",
                    f"date={date_str}",
                    "*.parquet",
                )
                matches = glob.glob(pattern)
                candidates.extend(matches)
                if matches:
                    break
            if candidates:
                break

    return sorted(set(candidates))


def _read_parquet_with_validation(
    path: str, symbol: str, columns: list[str] | None = None
) -> pd.DataFrame:
    """Read parquet file with basic validation and symbol injection.

    Args:
        path: Path to parquet file
        symbol: Symbol to inject if not present in data
        columns: Optional list of columns to select

    Returns:
        DataFrame with basic validation applied

    Raises:
        Exception: If file cannot be read or is corrupted
    """
    try:
        # Use pyarrow for more robust reading
        table = pq.read_table(path, columns=columns)
        df = table.to_pandas()
    except Exception as e:
        raise Exception(f"Failed to read parquet file {path}: {e}")

    if df.empty:
        raise Exception(f"Parquet file {path} is empty")

    # Inject symbol if not present
    if "symbol" not in df.columns:
        df["symbol"] = symbol

    return df


def _normalize_in_memory(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize DataFrame in memory for canonical schema.

    Args:
        df: Input DataFrame to normalize

    Returns:
        Normalized DataFrame with canonical schema

    Raises:
        ValueError: If required columns are missing or cannot be converted
    """
    out = df.copy()

    # Column name standardization (case insensitive, handling symbol vs timestamp)
    normalized_names = {}
    for column in out.columns:
        if column == "T":
            normalized_names[column] = "symbol"
            continue

        key = column.lower()
        if key == "symbol":
            normalized_names[column] = "symbol"
        elif key in {"t", "timestamp"}:
            normalized_names[column] = "ts"
        elif key in {"o", "open"}:
            normalized_names[column] = "open"
        elif key in {"h", "high"}:
            normalized_names[column] = "high"
        elif key in {"l", "low"}:
            normalized_names[column] = "low"
        elif key in {"c", "close"}:
            normalized_names[column] = "close"
        elif key in {"v", "volume"}:
            normalized_names[column] = "volume"
        else:
            normalized_names[column] = column

    out = out.rename(columns=normalized_names)

    # Ensure required columns exist
    missing = set(REQUIRED) - set(out.columns)
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Timestamp normalization
    if pd.api.types.is_datetime64_any_dtype(out["ts"]):
        if out["ts"].dt.tz is None:
            out["ts"] = out["ts"].dt.tz_localize("UTC")
        else:
            out["ts"] = out["ts"].dt.tz_convert("UTC")
        # Convert to nanoseconds since epoch
        out["ts"] = out["ts"].astype("int64")
    else:
        # Convert to numeric and then to int64 nanoseconds
        out["ts"] = pd.to_numeric(out["ts"], errors="coerce")
        if out["ts"].isna().any():
            raise ValueError("Timestamp conversion failed - NaN values present")
        out["ts"] = out["ts"].astype("int64")

        # Detect millisecond timestamps and convert to nanoseconds
        if out["ts"].max() < 1_000_000_000_000_000:
            out["ts"] *= 1_000_000

    # Symbol normalization
    out["symbol"] = out["symbol"].astype(str).str.lower()

    # Price columns normalization
    price_cols = ["open", "high", "low", "close"]
    for col in price_cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")
        if out[col].isna().any():
            print(f"Warning: {col} contains NaN values after conversion")

    # Volume normalization
    out["volume"] = (
        pd.to_numeric(out["volume"], errors="coerce").fillna(0).astype("int64")
    )

    # Optional columns - ensure they exist with proper types if present
    for col in OPTIONAL:
        if col in out.columns:
            if col in ["trades"]:
                out[col] = (
                    pd.to_numeric(out[col], errors="coerce").fillna(0).astype("int64")
                )
            elif col in ["vwap"]:
                out[col] = pd.to_numeric(out[col], errors="coerce")
            else:  # string columns
                out[col] = out[col].astype(str)

    # Sanity checks
    bad_hilo = (out["high"] < out["low"]).sum()
    if bad_hilo > 0:
        print(f"Warning: {bad_hilo} rows have high < low")

    bad_ohlc = (
        (out["high"] < out["open"])
        | (out["high"] < out["close"])
        | (out["low"] > out["open"])
        | (out["low"] > out["close"])
    ).sum()
    if bad_ohlc > 0:
        print(f"Warning: {bad_ohlc} rows have OHLC relationships violated")

    # Remove rows with invalid timestamps
    invalid_ts = (out["ts"] <= 0).sum()
    if invalid_ts > 0:
        print(f"Warning: Removing {invalid_ts} rows with invalid timestamps")
        out = out[out["ts"] > 0]

    # Remove rows with negative prices
    negative_prices = ((out[price_cols] < 0).any(axis=1)).sum()
    if negative_prices > 0:
        print(f"Warning: Removing {negative_prices} rows with negative prices")
        out = out[(out[price_cols] >= 0).all(axis=1)]

    return out
