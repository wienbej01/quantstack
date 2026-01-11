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


def load_sip_filtered_data(
    start_date: str,
    end_date: str,
    lookback_days: int,
    sip_dir: Path,
    gold_dir: Path,
) -> tuple[pd.DataFrame, dict]:
    """Load SIP-filtered 1m data across date range.

    Args:
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD
        lookback_days: Days of lookback for feature warmup
        sip_dir: Path to daily_sip directory
        gold_dir: Path to gold/stocks/1m directory

    Returns:
        Tuple of (DataFrame with all bars, metadata dict)
    """
    trading_days = get_trading_days(start_date, end_date, sip_dir)
    print(f"Found {len(trading_days)} trading days")

    all_bars = []
    symbol_dates: dict[str, list[str]] = {}

    for day_idx, date in enumerate(trading_days, 1):
        symbols = load_sip_universe(date, sip_dir)
        print(f"[{day_idx}/{len(trading_days)}] {date}: {len(symbols)} symbols")

        loaded = 0
        for sym_idx, symbol in enumerate(symbols, 1):
            if sym_idx % 5 == 0 or sym_idx == len(symbols):
                print(f"  [{sym_idx}/{len(symbols)}] Loading {symbol}...", flush=True)

            df = load_symbol_bars(symbol, date, lookback_days, gold_dir)
            if df.empty:
                continue

            # Tag with target date
            df["target_date"] = date
            all_bars.append(df)
            loaded += 1

            if symbol not in symbol_dates:
                symbol_dates[symbol] = []
            symbol_dates[symbol].append(date)

        print(
            f"  Loaded {loaded}/{len(symbols)} symbols, {sum(len(df) for df in all_bars):,} total bars"
        )

    if not all_bars:
        return pd.DataFrame(), {}

    combined = pd.concat(all_bars, ignore_index=True)

    metadata = {
        "start_date": start_date,
        "end_date": end_date,
        "trading_days": len(trading_days),
        "total_bars": len(combined),
        "unique_symbols": len(symbol_dates),
        "symbol_dates": symbol_dates,
    }

    return combined, metadata
