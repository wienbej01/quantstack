"""Gold loader for read-only access to normalized bars."""

import os

import pandas as pd
import pyarrow.parquet as pq
from qx_core.hashers import hash_dataframe
from qx_core.validators import ValidationError, validate_bars_dataframe

REQUIRED = ["ts", "symbol", "open", "high", "low", "close", "volume"]
OPTIONAL = ["trades", "vwap", "session", "date_et"]


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

    dfs = []
    files_read = 0
    files_attempted = 0

    # Collect unique year-month combinations from the dates
    unique_year_months = set()
    for date_str in dates:
        parts = date_str.split("-")
        if len(parts) >= 2:
            unique_year_months.add(f"{parts[0]}-{parts[1]}")

    for symbol in symbols:
        for year_month in unique_year_months:
            # Construct path for monthly parquet file
            year, month = year_month.split("-")
            path = os.path.join(
                root, "stocks", "1m", symbol, year, f"{year}-{month}.parquet"
            )
            files_attempted += 1

            try:
                df = _read_parquet_with_validation(path, symbol, columns)
                # Filter the monthly data to include only the requested dates
                df["date_str"] = pd.to_datetime(df["ts"], unit="ns").dt.strftime("%Y-%m-%d")
                df = df[df["date_str"].isin(dates)]
                df = df.drop(columns=["date_str"])

                if not df.empty:
                    dfs.append(df)
                    files_read += 1
            except Exception as e:
                # Log warning but continue
                print(f"Warning: failed to read {path}: {e}")

    if files_read == 0:
        raise RuntimeError(
            f"No parquet files could be read from {files_attempted} attempted files"
        )

    # Combine all dataframes
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
    if family == "bars_1m":
        # For 1m bars, structure is: root/stocks/1m/LETTER/...
        base_path = os.path.join(root, "stocks", "1m")
        if not os.path.exists(base_path):
            return set()

        symbols = set()
        for letter_dir in os.listdir(base_path):
            letter_path = os.path.join(base_path, letter_dir)
            if os.path.isdir(letter_path):
                for symbol in os.listdir(letter_path):
                    symbol_path = os.path.join(letter_path, symbol)
                    if os.path.isdir(symbol_path):
                        symbols.add(symbol)
        return symbols
    else:
        # For other families, look for symbol= partitions
        family_path = os.path.join(root, family)
        if not os.path.exists(family_path):
            return set()

        symbols = set()
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
    if family == "bars_1m":
        # Structure: root/stocks/1m/SYMBOL/2020/2020-10.parquet
        base_path = os.path.join(root, "stocks", "1m", symbol[:1], symbol)
        if not os.path.exists(base_path):
            return set()

        dates = set()
        for year_dir in os.listdir(base_path):
            year_path = os.path.join(base_path, year_dir)
            if os.path.isdir(year_path):
                for parquet_file in os.listdir(year_path):
                    if parquet_file.endswith(".parquet"):
                        # Extract YYYY-MM from filename like 2020-10.parquet
                        date = parquet_file[:-8]  # Remove .parquet
                        dates.add(date)
        return dates
    else:
        # Look for date= partitions
        symbol_path = os.path.join(root, family, f"symbol={symbol}")
        if not os.path.exists(symbol_path):
            return set()

        dates = set()
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

    # Column name standardization
    rename_map = {
        "T": "symbol",
        "t": "ts",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
    }
    cols_lower = {c: c.lower() for c in out.columns}
    out = out.rename(columns=cols_lower).rename(columns=rename_map)

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
    out["symbol"] = out["symbol"].astype(str)

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
