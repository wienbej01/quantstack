"""Load SIP-filtered gold 1m data with lookback for feature warmup."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


def load_sip_universe(date: str, sip_dir: Path) -> list[str]:
    """Load SIP universe for a given date.

    Args:
        date: Date string YYYY-MM-DD
        sip_dir: Path to daily_sip directory

    Returns:
        List of symbols in SIP universe
    """
    sip_file = sip_dir / f"date={date}" / "sip_universe.json"
    if not sip_file.exists():
        return []

    with open(sip_file) as f:
        data = json.load(f)
    return data.get("symbols", [])


def get_trading_days(start_date: str, end_date: str, sip_dir: Path) -> list[str]:
    """Get list of trading days with SIP data.

    Args:
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        sip_dir: Path to daily_sip directory

    Returns:
        List of date strings
    """
    dates = []
    current = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        sip_file = sip_dir / f"date={date_str}" / "sip_universe.json"
        if sip_file.exists():
            dates.append(date_str)
        current += timedelta(days=1)

    return dates


def load_symbol_bars(
    symbol: str, date: str, lookback_days: int, gold_dir: Path
) -> pd.DataFrame:
    """Load 1m bars for a symbol with lookback days for warmup.

    Args:
        symbol: Stock symbol
        date: Target date YYYY-MM-DD
        lookback_days: Number of prior days to load
        gold_dir: Path to gold/stocks/1m directory

    Returns:
        DataFrame with ts, symbol, open, high, low, close, volume
    """
    # Handle both /gold/stocks/1m/SYMBOL and /gold/stocks/1m/1m/SYMBOL paths
    symbol_dir = gold_dir / symbol
    if not symbol_dir.exists():
        # Try with extra 1m subdirectory
        symbol_dir = gold_dir / "1m" / symbol
    if not symbol_dir.exists():
        return pd.DataFrame()

    # Get all parquet files (recursively for year/month structure)
    # Filter to relevant year/month to avoid loading everything
    target_dt = pd.Timestamp(date)
    start_dt = target_dt - pd.Timedelta(days=lookback_days + 5)

    relevant_files = []
    for year_dir in symbol_dir.glob("*"):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        year = int(year_dir.name)
        if year < start_dt.year or year > target_dt.year:
            continue
        for pq_file in year_dir.glob("*.parquet"):
            relevant_files.append(pq_file)

    if not relevant_files:
        return pd.DataFrame()

    # Load all data and filter by date range
    dfs = []
    print(f"    Loading {len(relevant_files)} parquet files...", flush=True)
    for pq_file in relevant_files:
        try:
            df = pd.read_parquet(pq_file)
            dfs.append(df)
        except Exception:
            continue

    if not dfs:
        return pd.DataFrame()

    df = pd.concat(dfs, ignore_index=True)

    # Ensure required columns
    required = ["ts", "open", "high", "low", "close", "volume"]
    if not all(col in df.columns for col in required):
        return pd.DataFrame()

    # Add symbol column if missing
    if "symbol" not in df.columns:
        df["symbol"] = symbol

    # Convert ts to datetime for filtering
    df["dt"] = pd.to_datetime(df["ts"], unit="ns", utc=True)
    target_date = pd.Timestamp(date, tz="UTC")
    start_date = target_date - pd.Timedelta(days=lookback_days + 5)  # Extra buffer

    # Filter date range
    df = df[(df["dt"] >= start_date) & (df["dt"] <= target_date + pd.Timedelta(days=1))]
    df = df.sort_values("ts").reset_index(drop=True)

    return df[required + ["symbol"]]


def load_symbol_bars_range(
    symbol: str, start_date: str, end_date: str, gold_dir: Path
) -> pd.DataFrame:
    """Load 1m bars for a symbol within a date range.

    Args:
        symbol: Stock symbol
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        gold_dir: Path to gold/stocks/1m directory

    Returns:
        DataFrame with ts, symbol, open, high, low, close, volume
    """
    symbol_dir = gold_dir / symbol
    if not symbol_dir.exists():
        symbol_dir = gold_dir / "1m" / symbol
    if not symbol_dir.exists():
        return pd.DataFrame()

    start_dt = pd.Timestamp(start_date, tz="UTC")
    end_dt = pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1)

    relevant_files = []
    for year_dir in symbol_dir.glob("*"):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        year = int(year_dir.name)
        if year < start_dt.year or year > end_dt.year:
            continue
        for pq_file in year_dir.glob("*.parquet"):
            relevant_files.append(pq_file)

    if not relevant_files:
        return pd.DataFrame()

    dfs = []
    for pq_file in relevant_files:
        try:
            df = pd.read_parquet(pq_file)
            dfs.append(df)
        except Exception:
            continue

    if not dfs:
        return pd.DataFrame()

    df = pd.concat(dfs, ignore_index=True)

    required = ["ts", "open", "high", "low", "close", "volume"]
    if not all(col in df.columns for col in required):
        return pd.DataFrame()

    if "symbol" not in df.columns:
        df["symbol"] = symbol

    df["dt"] = pd.to_datetime(df["ts"], unit="ns", utc=True)
    df = df[(df["dt"] >= start_dt) & (df["dt"] < end_dt)]
    df = df.sort_values("ts").reset_index(drop=True)

    return df[required + ["symbol"]]


def build_daily_sip_cache(
    start_date: str,
    end_date: str,
    sip_dir: Path,
    gold_dir: Path,
    output_dir: Path,
) -> tuple[Path, dict]:
    """Build daily SIP-filtered cache files without concatenating full dataset."""
    trading_days = get_trading_days(start_date, end_date, sip_dir)
    daily_cache_dir = output_dir / "daily_cache"
    daily_cache_dir.mkdir(parents=True, exist_ok=True)

    symbol_dates: dict[str, list[str]] = {}
    total_bars = 0

    for day_idx, date_str in enumerate(trading_days, 1):
        daily_file = daily_cache_dir / f"day_{date_str.replace('-', '')}.parquet"
        if daily_file.exists():
            continue

        symbols = load_sip_universe(date_str, sip_dir)
        print(f"[{day_idx}/{len(trading_days)}] {date_str}: {len(symbols)} symbols")

        daily_bars = []
        loaded = 0
        for sym_idx, symbol in enumerate(symbols, 1):
            if sym_idx % 10 == 0 or sym_idx == len(symbols):
                print(f"  [{sym_idx}/{len(symbols)}] Loading {symbol}...", flush=True)

            df = load_symbol_bars_range(symbol, date_str, date_str, gold_dir)
            if df.empty:
                continue

            daily_bars.append(df)
            loaded += 1

            if symbol not in symbol_dates:
                symbol_dates[symbol] = []
            symbol_dates[symbol].append(date_str)

        if daily_bars:
            daily_df = pd.concat(daily_bars, ignore_index=True)
            total_bars += len(daily_df)
            daily_df.to_parquet(daily_file, index=False)

            print(
                f"  Loaded {loaded}/{len(symbols)} symbols, {total_bars:,} total bars "
                f"(cached day to {daily_file.name})"
            )

        del daily_bars
        if "daily_df" in locals():
            del daily_df

    metadata = {
        "start_date": start_date,
        "end_date": end_date,
        "trading_days": len(trading_days),
        "total_bars": total_bars,
        "unique_symbols": len(symbol_dates),
        "symbol_dates": symbol_dates,
    }

    return daily_cache_dir, metadata


def load_daily_cache_range(
    daily_cache_dir: Path,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """Load cached daily files for a date range and concatenate."""
    start_dt = pd.Timestamp(start_date).date()
    end_dt = pd.Timestamp(end_date).date()
    dates = pd.date_range(start_dt, end_dt, freq="D")

    dfs = []
    for date_obj in dates:
        day_str = date_obj.strftime("%Y%m%d")
        daily_file = daily_cache_dir / f"day_{day_str}.parquet"
        if not daily_file.exists():
            continue
        dfs.append(pd.read_parquet(daily_file))

    if not dfs:
        return pd.DataFrame()

    return pd.concat(dfs, ignore_index=True)


def compute_volume_baseline(
    daily_cache_dir: Path,
    start_date: str,
    end_date: str,
    output_dir: Path,
) -> Path:
    """Compute per-symbol minute-of-day average volume over the date range."""
    baseline_file = output_dir / "daily_cache" / "volume_baseline.parquet"
    if baseline_file.exists():
        return baseline_file

    parts_dir = output_dir / "daily_cache" / "volume_baseline_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    start_dt = pd.Timestamp(start_date).date()
    end_dt = pd.Timestamp(end_date).date()
    dates = pd.date_range(start_dt, end_dt, freq="D")

    for date_obj in dates:
        day_str = date_obj.strftime("%Y%m%d")
        daily_file = daily_cache_dir / f"day_{day_str}.parquet"
        part_file = parts_dir / f"volume_baseline_{day_str}.parquet"
        if part_file.exists():
            continue
        if not daily_file.exists():
            continue

        daily_df = pd.read_parquet(daily_file, columns=["symbol", "ts", "volume"])
        if daily_df.empty:
            continue

        daily_df["dt_et"] = pd.to_datetime(daily_df["ts"], unit="ns", utc=True).dt.tz_convert(
            "America/New_York"
        )
        daily_df["minute_of_day"] = (
            daily_df["dt_et"].dt.hour * 60 + daily_df["dt_et"].dt.minute
        )

        agg = (
            daily_df.groupby(["symbol", "minute_of_day"])["volume"]
            .agg(["sum", "count"])
            .reset_index()
        )
        agg.to_parquet(part_file, index=False)

        del daily_df, agg

    running_df: pd.DataFrame | None = None
    for part_file in sorted(parts_dir.glob("volume_baseline_*.parquet")):
        part_df = pd.read_parquet(part_file)
        if part_df.empty:
            continue
        part_df = part_df.set_index(["symbol", "minute_of_day"])
        part_df.index.names = ["symbol", "minute_of_day"]
        if running_df is None:
            running_df = part_df.copy()
            continue
        running_df = running_df.add(part_df, fill_value=0.0)

    if running_df is None or running_df.empty:
        avg_df = pd.DataFrame(columns=["symbol", "minute_of_day", "avg_volume"])
        avg_df.to_parquet(baseline_file, index=False)
        return baseline_file

    avg_volume = running_df["sum"] / running_df["count"].replace(0, pd.NA)
    avg_volume = avg_volume.dropna()
    avg_df = avg_volume.reset_index()
    avg_df.columns = ["symbol", "minute_of_day", "avg_volume"]
    avg_df.to_parquet(baseline_file, index=False)
    return baseline_file


def load_sip_filtered_data(
    start_date: str,
    end_date: str,
    lookback_days: int,
    sip_dir: Path,
    gold_dir: Path,
    output_dir: Path = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Load SIP-filtered 1m data across date range.

    Args:
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        lookback_days: Days of lookback for feature warmup
        sip_dir: Path to daily_sip directory
        gold_dir: Path to gold/stocks/1m directory
        output_dir: Optional path for temp files (defaults to gold_dir)

    Returns:
        Tuple of (DataFrame with all bars, SPY DataFrame, metadata dict)
    """
    trading_days = get_trading_days(start_date, end_date, sip_dir)
    print(f"Found {len(trading_days)} trading days")

    # Load SPY data for regime features
    print("Loading SPY data for regime features...")
    spy_df = load_symbol_bars("SPY", end_date, lookback_days + 60, gold_dir)
    if not spy_df.empty:
        print(f"  Loaded {len(spy_df):,} SPY bars")
    else:
        print("  WARNING: No SPY data found")

    # Streaming write: process one day at a time to avoid memory explosion
    daily_files = []
    symbol_dates: dict[str, list[str]] = {}
    total_bars = 0

    for day_idx, date in enumerate(trading_days, 1):
        symbols = load_sip_universe(date, sip_dir)
        print(f"[{day_idx}/{len(trading_days)}] {date}: {len(symbols)} symbols")

        daily_bars = []
        loaded = 0
        for sym_idx, symbol in enumerate(symbols, 1):
            if sym_idx % 5 == 0 or sym_idx == len(symbols):
                print(f"  [{sym_idx}/{len(symbols)}] Loading {symbol}...", flush=True)

            df = load_symbol_bars(symbol, date, lookback_days, gold_dir)
            if df.empty:
                continue

            # Tag with target date
            df["target_date"] = date
            daily_bars.append(df)
            loaded += 1

            if symbol not in symbol_dates:
                symbol_dates[symbol] = []
            symbol_dates[symbol].append(date)

        if daily_bars:
            # Write this day's data to temp parquet file
            daily_df = pd.concat(daily_bars, ignore_index=True)
            day_bars = len(daily_df)
            total_bars += day_bars

            # Use output_dir for temp files (avoids /tmp filesystem corruption issues)
            if output_dir is None:
                import tempfile
                temp_dir = Path(tempfile.gettempdir()) / "sip_pattern_discovery_temp"
            else:
                temp_dir = output_dir / ".temp_daily_files"
            temp_dir.mkdir(parents=True, exist_ok=True)

            daily_file = temp_dir / f"day_{date.replace('-', '')}.parquet"
            daily_df.to_parquet(daily_file, index=False)
            daily_files.append(daily_file)

            print(f"  Loaded {loaded}/{len(symbols)} symbols, {total_bars:,} total bars (cached day to {daily_file.name})")

        # Clear memory for this day
        del daily_bars
        if 'daily_df' in locals():
            del daily_df

    if not daily_files:
        return pd.DataFrame(), spy_df, {}

    # Concat all daily files into final dataset
    print(f"\nConcatenating {len(daily_files)} daily files...")
    daily_dfs = [pd.read_parquet(f) for f in daily_files]
    combined = pd.concat(daily_dfs, ignore_index=True)
    if "target_date" in combined.columns:
        combined = combined.drop(columns=["target_date"])

    # Clean up temp files directory (only .temp dirs, not output_dir itself)
    import shutil
    temp_dir = daily_files[0].parent
    if temp_dir.name.startswith('.temp') or 'sip_pattern_discovery_temp' in str(temp_dir):
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"Cleaned up {len(daily_files)} temporary daily files")

    metadata = {
        "start_date": start_date,
        "end_date": end_date,
        "trading_days": len(trading_days),
        "total_bars": len(combined),
        "unique_symbols": len(symbol_dates),
        "symbol_dates": symbol_dates,
    }

    return combined, spy_df, metadata
