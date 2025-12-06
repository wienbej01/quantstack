#!/usr/bin/env python3
"""Generate training data with SIMPLE fixed-percentage labels."""

import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def load_bars(symbols, start_date, end_date, gold_path):
    """Load 1m bars for symbols."""
    all_bars = []
    for symbol in symbols:
        symbol_path = Path(gold_path) / symbol.upper()
        if not symbol_path.exists():
            continue
        
        # Load monthly files
        for year_dir in symbol_path.iterdir():
            if not year_dir.is_dir():
                continue
            for month_file in year_dir.glob("*.parquet"):
                try:
                    df = pd.read_parquet(month_file)
                    df['symbol'] = symbol
                    all_bars.append(df)
                except Exception:
                    continue
    
    if not all_bars:
        return pd.DataFrame()
    
    combined = pd.concat(all_bars, ignore_index=True)
    combined['ts'] = pd.to_datetime(combined['ts'])
    
    # Filter date range
    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date) + pd.Timedelta(days=1)
    combined = combined[(combined['ts'] >= start_dt) & (combined['ts'] < end_dt)]
    
    return combined.sort_values(['symbol', 'ts']).reset_index(drop=True)


def label_bars(df, threshold_pct=0.02, horizon_minutes=30):
    """Label bars with simple fixed-percentage threshold."""
    df = df.copy()
    df['forward_30min_return'] = df.groupby('symbol')['close'].pct_change(horizon_minutes).shift(-horizon_minutes)
    
    # Simple labeling
    df['label'] = 0  # Default: neutral
    df.loc[df['forward_30min_return'] >= threshold_pct, 'label'] = 1  # LONG
    df.loc[df['forward_30min_return'] <= -threshold_pct, 'label'] = -1  # SHORT
    
    # Remove last 30 bars per symbol (no forward data)
    df = df.groupby('symbol').apply(lambda x: x.iloc[:-horizon_minutes]).reset_index(drop=True)
    
    return df[['symbol', 'ts', 'open', 'high', 'low', 'close', 'volume', 'label']]


def main():
    # Load SIP membership
    sip_file = Path("run/sip_membership_smb_1month/sip_membership.parquet")
    sip = pd.read_parquet(sip_file)
    symbols = sorted(sip["symbol"].unique())

    LOGGER.info("=" * 80)
    LOGGER.info("Generating Training Data - SIMPLE FIXED % LABELS")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Symbols: {len(symbols)} - {symbols}")
    LOGGER.info("Threshold: ±2% in 30 minutes")
    LOGGER.info("No ATR, no balancing, no scaling - just simple percentage moves")

    # Load bars
    LOGGER.info("Loading bars...")
    df = load_bars(symbols, "2024-05-01", "2024-05-31", "/home/jacobw/gcs-mount/gold/stocks/1m")
    LOGGER.info(f"Loaded {len(df):,} bars")

    # Label
    LOGGER.info("Labeling...")
    labeled = label_bars(df, threshold_pct=0.02, horizon_minutes=30)
    
    # Stats
    label_counts = labeled['label'].value_counts().sort_index()
    LOGGER.info("=" * 80)
    LOGGER.info("Label Distribution:")
    for label, count in label_counts.items():
        label_name = {-1: "SHORT", 0: "NEUTRAL", 1: "LONG"}[label]
        LOGGER.info(f"  {label_name:8s} ({label:2d}): {count:,} ({count/len(labeled)*100:.1f}%)")
    
    # Save
    output_path = Path("artefacts/extensions/intraday_ml/v4_sip_smb_simple/training_data.parquet")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    labeled.to_parquet(output_path, index=False)
    
    LOGGER.info("=" * 80)
    LOGGER.info(f"Saved to: {output_path}")
    LOGGER.info("SUCCESS!")


if __name__ == "__main__":
    main()
