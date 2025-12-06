"""SMB Capital-style premarket scanner for stocks in play."""

from pathlib import Path

import numpy as np
import pandas as pd


def load_gold_universe(
    gold_path: str = "/home/jacobw/gcs-mount/gold/stocks/1m",
) -> list[str]:
    """Load all available symbols from gold data."""
    gold_dir = Path(gold_path)
    if not gold_dir.exists():
        raise FileNotFoundError(f"Gold path not found: {gold_path}")

    symbols = [d.name for d in gold_dir.iterdir() if d.is_dir()]
    return sorted(symbols)


def calculate_gap_and_pm_metrics(
    symbol: str, date: str, gold_path: str = "/home/jacobw/gcs-mount/gold/stocks/1m"
) -> dict:
    """Calculate gap and premarket metrics for a symbol."""

    symbol_path = Path(gold_path) / symbol
    if not symbol_path.exists():
        return None

    # Load data for current day
    current_date = pd.to_datetime(date)
    current_file = symbol_path / f"{current_date.strftime('%Y-%m-%d')}.parquet"

    if not current_file.exists():
        return None

    # Find prior trading day (search back up to 5 days)
    prior_file = None
    for i in range(1, 6):
        check_date = current_date - pd.Timedelta(days=i)
        check_file = symbol_path / f"{check_date.strftime('%Y-%m-%d')}.parquet"
        if check_file.exists():
            prior_file = check_file
            break

    if prior_file is None:
        return None

    # Load prior day close
    try:
        prior_bars = pd.read_parquet(prior_file)
        prior_close = prior_bars.iloc[-1]["close"]
    except Exception:
        return None

    if not current_file.exists():
        return None

    # Load current day data
    try:
        current_bars = pd.read_parquet(current_file)
        current_bars["ts"] = pd.to_datetime(current_bars["ts"])
    except Exception:
        return None

    # Premarket = before 9:30 AM ET (13:30 UTC)
    premarket_cutoff = current_bars["ts"].dt.time < pd.Timestamp("13:30:00").time()
    pm_bars = current_bars[premarket_cutoff]

    if len(pm_bars) == 0:
        # Use first bar as proxy
        first_price = current_bars.iloc[0]["open"]
        gap_pct = (first_price - prior_close) / prior_close
        pm_volume = 0
    else:
        first_price = pm_bars.iloc[0]["open"]
        gap_pct = (first_price - prior_close) / prior_close
        pm_volume = pm_bars["volume"].sum()

    # Calculate 20-day ADV (approximate from recent data)
    adv_20 = current_bars["volume"].sum()  # Simplified: use current day as proxy

    return {
        "gap_pct": gap_pct,
        "pm_volume": pm_volume,
        "adv_20": adv_20,
        "pm_rvol": pm_volume / adv_20 if adv_20 > 0 else 0,
        "prior_close": prior_close,
        "first_price": first_price,
    }


def calculate_atr(
    symbol: str,
    date: str,
    period: int = 20,
    gold_path: str = "/home/jacobw/gcs-mount/gold/stocks/1m",
) -> float:
    """Calculate ATR for a symbol."""

    symbol_path = Path(gold_path) / symbol
    if not symbol_path.exists():
        return 0.0

    # Load recent days
    current_date = pd.to_datetime(date)
    all_bars = []

    for i in range(period + 5):  # Load extra days for safety
        check_date = current_date - pd.Timedelta(days=i)
        file_path = symbol_path / f"{check_date.strftime('%Y-%m-%d')}.parquet"

        if file_path.exists():
            try:
                bars = pd.read_parquet(file_path)
                all_bars.append(bars)
            except Exception:
                continue

    if not all_bars:
        return 0.0

    # Combine and calculate ATR
    df = pd.concat(all_bars).sort_values("ts")

    # Daily high-low range
    daily = df.groupby(pd.to_datetime(df["ts"]).dt.date).agg(
        {"high": "max", "low": "min", "close": "last"}
    )

    if len(daily) < 2:
        return 0.0

    # True range
    daily["tr"] = np.maximum(
        daily["high"] - daily["low"],
        np.maximum(
            abs(daily["high"] - daily["close"].shift(1)),
            abs(daily["low"] - daily["close"].shift(1)),
        ),
    )

    atr = daily["tr"].tail(period).mean()
    return atr


def smb_premarket_scan(
    date: str,
    gold_path: str = "/home/jacobw/gcs-mount/gold/stocks/1m",
    min_gap_pct: float = 0.03,
    min_pm_rvol: float = 0.10,
    min_atr: float = 0.70,
    min_adv: float = 1_000_000,
    top_k: int = 20,
) -> pd.DataFrame:
    """
    SMB-style premarket scan for stocks in play.

    Args:
        date: Trading date (YYYY-MM-DD)
        gold_path: Path to gold data
        min_gap_pct: Minimum gap % (default 3%)
        min_pm_rvol: Minimum premarket RVOL (default 10% of ADV)
        min_atr: Minimum ATR in dollars (default $0.70)
        min_adv: Minimum average daily volume (default 1M)
        top_k: Number of stocks to return (default 20)

    Returns:
        DataFrame with top stocks in play and their scores
    """

    symbols = load_gold_universe(gold_path)
    print(f"Scanning {len(symbols)} symbols for {date}...")

    candidates = []

    for i, symbol in enumerate(symbols):
        if (i + 1) % 100 == 0:
            print(f"  Processed {i+1}/{len(symbols)} symbols...")

        # Calculate gap and premarket metrics
        metrics = calculate_gap_and_pm_metrics(symbol, date, gold_path)
        if metrics is None:
            continue

        # Filter 1: Gap
        if abs(metrics["gap_pct"]) < min_gap_pct:
            continue

        # Filter 2: ADV
        if metrics["adv_20"] < min_adv:
            continue

        # Filter 3: Premarket RVOL
        if metrics["pm_rvol"] < min_pm_rvol:
            continue

        # Calculate ATR
        atr = calculate_atr(symbol, date, period=20, gold_path=gold_path)

        # Filter 4: ATR
        if atr < min_atr:
            continue

        # Calculate SMB composite score
        score = (
            abs(metrics["gap_pct"]) * 10  # Gap contribution
            + metrics["pm_rvol"] * 5  # RVOL contribution
            + (atr / 0.70) * 2  # ATR contribution
        )

        candidates.append(
            {
                "symbol": symbol,
                "gap_pct": metrics["gap_pct"],
                "pm_rvol": metrics["pm_rvol"],
                "atr": atr,
                "adv_20": metrics["adv_20"],
                "score": score,
                "prior_close": metrics["prior_close"],
                "first_price": metrics["first_price"],
            }
        )

    # Convert to DataFrame and sort by score
    df = pd.DataFrame(candidates)

    if len(df) == 0:
        print(f"No stocks in play found for {date}")
        return df

    df = df.sort_values("score", ascending=False).head(top_k)

    print(f"\nFound {len(df)} stocks in play:")
    for idx, row in df.head(10).iterrows():
        print(
            f"  {row['symbol']:6s}: gap={row['gap_pct']:+.2%}  pm_rvol={row['pm_rvol']:.2f}  atr=${row['atr']:.2f}  score={row['score']:.1f}"
        )

    return df


def save_daily_sip(
    df: pd.DataFrame,
    date: str,
    output_path: str = "/home/jacobw/quantstack/run/sip_membership_smb",
):
    """Save SMB-filtered SIP for a date."""

    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Add metadata
    df["trade_date"] = date
    df["is_sip"] = True
    df["sip_reason"] = "smb_gap_rvol_atr"
    df["sip_score"] = df["score"]

    # Save partitioned by date
    partition_dir = output_dir / f"trade_date={date}"
    partition_dir.mkdir(parents=True, exist_ok=True)

    output_file = partition_dir / "data.parquet"
    df.to_parquet(output_file, index=False)

    print(f"Saved {len(df)} stocks in play to {output_file}")
