"""SMB Capital-style premarket scanner for stocks in play - works with monthly parquet files."""

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

    symbols = [
        d.name for d in gold_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
    ]
    return sorted(symbols)


def load_month_data(symbol: str, year: int, month: int, gold_path: str) -> pd.DataFrame:
    """Load monthly parquet file for a symbol."""
    symbol_path = Path(gold_path) / symbol / str(year) / f"{year}-{month:02d}.parquet"

    if not symbol_path.exists():
        return None

    try:
        df = pd.read_parquet(symbol_path)
        df["ts"] = pd.to_datetime(df["ts"])
        return df
    except Exception:
        return None


def calculate_gap_and_pm_metrics(symbol: str, date: str, gold_path: str) -> dict:
    """Calculate gap and premarket metrics for a symbol."""

    target_date = pd.to_datetime(date)
    year = target_date.year
    month = target_date.month

    # Load current month
    current_month_data = load_month_data(symbol, year, month, gold_path)
    if current_month_data is None:
        return None

    # Filter to target date
    current_month_data["date"] = current_month_data["ts"].dt.date
    target_date_obj = target_date.date()

    current_day_bars = current_month_data[current_month_data["date"] == target_date_obj]
    if len(current_day_bars) == 0:
        return None

    # Find prior trading day (search back in current month, then prior month if needed)
    prior_close = None

    # Try current month first
    prior_days = current_month_data[current_month_data["date"] < target_date_obj]
    if len(prior_days) > 0:
        prior_date_obj = prior_days["date"].max()
        prior_day_bars = current_month_data[
            current_month_data["date"] == prior_date_obj
        ]
        prior_close = prior_day_bars.iloc[-1]["close"]
    else:
        # Try prior month
        prior_month = month - 1 if month > 1 else 12
        prior_year = year if month > 1 else year - 1
        prior_month_data = load_month_data(symbol, prior_year, prior_month, gold_path)

        if prior_month_data is not None:
            prior_month_data["date"] = pd.to_datetime(prior_month_data["ts"]).dt.date
            if len(prior_month_data) > 0:
                prior_close = prior_month_data.iloc[-1]["close"]

    if prior_close is None:
        return None

    # Calculate gap
    first_price = current_day_bars.iloc[0]["open"]
    gap_pct = (first_price - prior_close) / prior_close

    # Premarket volume (before 9:30 AM ET = 13:30 UTC)
    pm_bars = current_day_bars[
        current_day_bars["ts"].dt.time < pd.Timestamp("13:30:00").time()
    ]
    pm_volume = pm_bars["volume"].sum() if len(pm_bars) > 0 else 0

    # ADV (use current day as proxy)
    adv_20 = current_day_bars["volume"].sum()

    return {
        "gap_pct": gap_pct,
        "pm_volume": pm_volume,
        "adv_20": adv_20,
        "pm_rvol": pm_volume / adv_20 if adv_20 > 0 else 0,
        "prior_close": prior_close,
        "first_price": first_price,
    }


def calculate_atr(symbol: str, date: str, gold_path: str, period: int = 20) -> float:
    """Calculate ATR for a symbol."""

    target_date = pd.to_datetime(date)
    year = target_date.year
    month = target_date.month

    # Load current and prior month
    all_bars = []

    for m_offset in range(3):  # Load 3 months of data
        check_month = month - m_offset
        check_year = year

        while check_month < 1:
            check_month += 12
            check_year -= 1

        month_data = load_month_data(symbol, check_year, check_month, gold_path)
        if month_data is not None:
            all_bars.append(month_data)

    if not all_bars:
        return 0.0

    # Combine and calculate ATR
    df = pd.concat(all_bars).sort_values("ts")
    df["date"] = pd.to_datetime(df["ts"]).dt.date

    # Daily OHLC
    daily = (
        df.groupby("date")
        .agg({"high": "max", "low": "min", "close": "last"})
        .reset_index()
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

    # Filter to dates before target
    daily = daily[daily["date"] < target_date.date()]

    atr = daily["tr"].tail(period).mean()
    return atr if not pd.isna(atr) else 0.0


def smb_premarket_scan(
    date: str,
    gold_path: str = "/home/jacobw/gcs-mount/gold/stocks/1m",
    min_gap_pct: float = 0.03,
    min_pm_rvol: float = 0.10,
    min_atr: float = 0.70,
    min_adv: float = 1_000_000,
    top_k: int = 20,
) -> pd.DataFrame:
    """SMB-style premarket scan for stocks in play."""

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
        atr = calculate_atr(symbol, date, gold_path, period=20)

        # Filter 4: ATR
        if atr < min_atr:
            continue

        # Calculate SMB composite score
        score = abs(metrics["gap_pct"]) * 10 + metrics["pm_rvol"] * 5 + (atr / 0.70) * 2

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
