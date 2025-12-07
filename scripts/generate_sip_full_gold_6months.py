#!/usr/bin/env python3
"""Generate SIP membership for full gold universe (600 symbols) for 6-month period."""

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def load_gold_universe():
    """Load full gold universe from config."""
    with open("configs/extensions/intraday_ml/universe_gold_full.yaml") as f:
        config = yaml.safe_load(f)
    return config["symbols"]


def calculate_daily_features(
    symbol, date, data_root="/home/jacobw/gcs-mount/gold/stocks/1m"
):
    """Calculate features for a symbol on a given date."""
    symbol_path = Path(data_root) / symbol

    if not symbol_path.exists():
        return None

    # Load data for the date and previous 20 days for calculations
    date_str = date.strftime("%Y-%m-%d")

    try:
        # Load parquet files for the date range
        files = sorted(symbol_path.glob("*.parquet"))
        if not files:
            return None

        # Load recent data (simplified - in production would load specific date range)
        df = pd.read_parquet(files[-1])  # Load most recent file

        if len(df) == 0:
            return None

        # Filter to specific date
        df["date"] = pd.to_datetime(df["timestamp"]).dt.date
        date_data = df[df["date"] == date.date()]

        if len(date_data) == 0:
            return None

        # Calculate features
        prev_close = (
            df[df["date"] < date.date()]["close"].iloc[-1]
            if len(df[df["date"] < date.date()]) > 0
            else date_data["open"].iloc[0]
        )
        open_price = date_data["open"].iloc[0]

        # Gap %
        gap_pct = (open_price - prev_close) / prev_close if prev_close > 0 else 0

        # ATR (simplified - use recent 14-day range)
        recent_data = df[df["date"] < date.date()].tail(14)
        if len(recent_data) > 0:
            atr14 = (recent_data["high"] - recent_data["low"]).mean()
        else:
            atr14 = date_data["high"].max() - date_data["low"].min()

        # ADV (20-day average volume)
        recent_data = df[df["date"] < date.date()].tail(20)
        if len(recent_data) > 0:
            adv20 = recent_data.groupby("date")["volume"].sum().mean()
        else:
            adv20 = date_data["volume"].sum()

        return {
            "symbol": symbol,
            "date": date_str,
            "gap_pct": gap_pct,
            "atr14": atr14,
            "adv20": adv20,
            "open": open_price,
            "prev_close": prev_close,
        }
    except Exception as e:
        logging.debug(f"Error processing {symbol} on {date_str}: {e}")
        return None


def generate_sip_for_date(
    symbols, date, min_gap_pct=0.02, min_atr=2.0, min_adv=10_000_000, top_k=50
):
    """Generate SIP list for a specific date."""
    features = []

    for symbol in symbols:
        feat = calculate_daily_features(symbol, date)
        if feat:
            features.append(feat)

    if not features:
        return pd.DataFrame()

    df = pd.DataFrame(features)

    # Apply SMB filters
    filtered = df[
        (df["gap_pct"].abs() >= min_gap_pct)
        & (df["atr14"] >= min_atr)
        & (df["adv20"] >= min_adv)
    ].copy()

    # Score = |gap| * ATR * (ADV / 1M)
    filtered["score"] = (
        filtered["gap_pct"].abs() * filtered["atr14"] * (filtered["adv20"] / 1_000_000)
    )

    # Select top-k
    sip = filtered.nlargest(top_k, "score")

    return sip


def main():
    logging.info("=" * 80)
    logging.info("GENERATING SIP MEMBERSHIP FOR FULL GOLD UNIVERSE")
    logging.info("=" * 80)

    # Load gold universe
    symbols = load_gold_universe()
    logging.info(f"Gold universe: {len(symbols)} symbols")

    # Date range: Jan 2 - Jun 28, 2024 (same as v4_6months)
    start_date = datetime(2024, 1, 2)
    end_date = datetime(2024, 6, 28)

    # Generate trading days
    date_range = pd.bdate_range(start=start_date, end=end_date)
    logging.info(
        f"Date range: {start_date.date()} to {end_date.date()} ({len(date_range)} trading days)"
    )

    # SMB SIP parameters
    min_gap_pct = 0.02  # 2% gap
    min_atr = 2.0  # $2 ATR
    min_adv = 10_000_000  # 10M ADV
    top_k = 50  # Top 50 per day

    logging.info(
        f"SIP Filters: gap≥{min_gap_pct:.1%}, ATR≥${min_atr:.2f}, ADV≥{min_adv:,}"
    )
    logging.info(f"Top-k per day: {top_k}")
    logging.info("")

    # Generate SIP for each date
    all_sip = []

    for i, date in enumerate(date_range, 1):
        logging.info(f"Processing {date.date()} ({i}/{len(date_range)})...")

        sip_df = generate_sip_for_date(
            symbols, date, min_gap_pct, min_atr, min_adv, top_k
        )

        if len(sip_df) > 0:
            all_sip.append(sip_df)
            logging.info(f"  Selected {len(sip_df)} symbols")
        else:
            logging.info("  No symbols met criteria")

    # Combine all dates
    if not all_sip:
        logging.error("No SIP data generated!")
        return

    sip_full = pd.concat(all_sip, ignore_index=True)

    # Save
    output_dir = Path("run/sip_membership_full_gold_6months")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "sip_membership.parquet"
    sip_full.to_parquet(output_file, index=False)

    # Statistics
    logging.info("")
    logging.info("=" * 80)
    logging.info("SIP MEMBERSHIP GENERATED")
    logging.info("=" * 80)
    logging.info(f"Total selections: {len(sip_full):,}")
    logging.info(f"Unique symbols: {sip_full['symbol'].nunique()}")
    logging.info(f"Date range: {sip_full['date'].min()} to {sip_full['date'].max()}")
    logging.info(f"Avg symbols/day: {len(sip_full) / sip_full['date'].nunique():.1f}")
    logging.info(f"Saved to: {output_file}")

    # Daily distribution
    daily_counts = sip_full.groupby("date").size()
    logging.info("")
    logging.info("Daily Distribution:")
    logging.info(f"  Min: {daily_counts.min()}")
    logging.info(f"  Max: {daily_counts.max()}")
    logging.info(f"  Mean: {daily_counts.mean():.1f}")
    logging.info(f"  Std: {daily_counts.std():.1f}")

    # Top symbols
    top_symbols = sip_full["symbol"].value_counts().head(20)
    logging.info("")
    logging.info("Top 20 Most Frequent Symbols:")
    for symbol, count in top_symbols.items():
        pct = count / sip_full["date"].nunique() * 100
        logging.info(f"  {symbol}: {count} days ({pct:.1f}%)")

    # Save summary
    with open(output_dir / "summary.txt", "w") as f:
        f.write("SIP MEMBERSHIP SUMMARY - FULL GOLD UNIVERSE\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Universe: {len(symbols)} symbols\n")
        f.write(f"Period: {start_date.date()} to {end_date.date()}\n")
        f.write(f"Trading days: {len(date_range)}\n\n")
        f.write("Filters:\n")
        f.write(f"  Gap: ≥{min_gap_pct:.1%}\n")
        f.write(f"  ATR: ≥${min_atr:.2f}\n")
        f.write(f"  ADV: ≥{min_adv:,}\n")
        f.write(f"  Top-k: {top_k}\n\n")
        f.write("Results:\n")
        f.write(f"  Total selections: {len(sip_full):,}\n")
        f.write(f"  Unique symbols: {sip_full['symbol'].nunique()}\n")
        f.write(
            f"  Avg symbols/day: {len(sip_full) / sip_full['date'].nunique():.1f}\n"
        )
        f.write(
            f"  Min/Max/Std: {daily_counts.min()}/{daily_counts.max()}/{daily_counts.std():.1f}\n"
        )

    logging.info(f"\nSummary saved to: {output_dir}/summary.txt")


if __name__ == "__main__":
    main()
