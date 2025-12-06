#!/usr/bin/env python3
"""Generate training data for 3 months with train/val/OOS split."""

import logging
import time
from pathlib import Path
from threading import Thread

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def heartbeat_monitor(interval=60):
    """Log heartbeat every N seconds."""
    while True:
        time.sleep(interval)
        LOGGER.info(f"[HEARTBEAT] Process alive, time: {time.strftime('%H:%M:%S')}")


def load_bars(symbols, start_date, end_date, gold_path):
    """Load 1m bars for symbols."""
    all_bars = []
    for i, symbol in enumerate(symbols, 1):
        if i % 5 == 0:
            LOGGER.info(f"Loading bars: {i}/{len(symbols)} symbols")
        
        symbol_path = Path(gold_path) / symbol.upper()
        if not symbol_path.exists():
            continue
        
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
    
    df['label'] = 0
    df.loc[df['forward_30min_return'] >= threshold_pct, 'label'] = 1
    df.loc[df['forward_30min_return'] <= -threshold_pct, 'label'] = -1
    
    # Remove last 30 bars per symbol
    df = df.groupby('symbol', group_keys=False).apply(lambda x: x.iloc[:-horizon_minutes])
    
    return df[['symbol', 'ts', 'open', 'high', 'low', 'close', 'volume', 'label']]


def main():
    # Start heartbeat
    heartbeat = Thread(target=heartbeat_monitor, args=(60,), daemon=True)
    heartbeat.start()

    # Load SIP membership
    sip_file = Path("run/sip_membership_smb_3months/sip_membership.parquet")
    sip = pd.read_parquet(sip_file)
    symbols = sorted(sip["symbol"].unique())

    LOGGER.info("=" * 80)
    LOGGER.info("Generating Training Data - 3 MONTHS with Train/Val/OOS Split")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Symbols: {len(symbols)} - {symbols}")
    LOGGER.info("Period: Mar-May 2024")
    LOGGER.info("Split: 60% train (Mar-Apr 15), 20% val (Apr 16-30), 20% OOS (May)")

    # Load bars
    LOGGER.info("Loading bars...")
    df = load_bars(symbols, "2024-03-01", "2024-05-31", "/home/jacobw/gcs-mount/gold/stocks/1m")
    LOGGER.info(f"Loaded {len(df):,} bars")

    # Label
    LOGGER.info("Labeling...")
    labeled = label_bars(df, threshold_pct=0.02, horizon_minutes=30)
    
    # Split by date
    labeled['date'] = labeled['ts'].dt.date
    
    train_end = pd.to_datetime('2024-04-15').date()
    val_end = pd.to_datetime('2024-04-30').date()
    
    train_df = labeled[labeled['date'] <= train_end]
    val_df = labeled[(labeled['date'] > train_end) & (labeled['date'] <= val_end)]
    oos_df = labeled[labeled['date'] > val_end]
    
    # Stats
    LOGGER.info("=" * 80)
    LOGGER.info("Dataset Split:")
    LOGGER.info(f"  TRAIN: {len(train_df):,} rows ({len(train_df)/len(labeled)*100:.1f}%)")
    LOGGER.info(f"    Dates: {train_df['date'].min()} to {train_df['date'].max()}")
    LOGGER.info(f"    LONG: {(train_df['label']==1).sum():,}, SHORT: {(train_df['label']==-1).sum():,}, NEUTRAL: {(train_df['label']==0).sum():,}")
    
    LOGGER.info(f"  VAL: {len(val_df):,} rows ({len(val_df)/len(labeled)*100:.1f}%)")
    LOGGER.info(f"    Dates: {val_df['date'].min()} to {val_df['date'].max()}")
    LOGGER.info(f"    LONG: {(val_df['label']==1).sum():,}, SHORT: {(val_df['label']==-1).sum():,}, NEUTRAL: {(val_df['label']==0).sum():,}")
    
    LOGGER.info(f"  OOS: {len(oos_df):,} rows ({len(oos_df)/len(labeled)*100:.1f}%)")
    LOGGER.info(f"    Dates: {oos_df['date'].min()} to {oos_df['date'].max()}")
    LOGGER.info(f"    LONG: {(oos_df['label']==1).sum():,}, SHORT: {(oos_df['label']==-1).sum():,}, NEUTRAL: {(oos_df['label']==0).sum():,}")
    
    # Save
    output_dir = Path("artefacts/extensions/intraday_ml/v4_3months")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    train_df.drop('date', axis=1).to_parquet(output_dir / "train.parquet", index=False)
    val_df.drop('date', axis=1).to_parquet(output_dir / "val.parquet", index=False)
    oos_df.drop('date', axis=1).to_parquet(output_dir / "oos.parquet", index=False)
    
    LOGGER.info("=" * 80)
    LOGGER.info(f"Saved to: {output_dir}")
    LOGGER.info("  - train.parquet")
    LOGGER.info("  - val.parquet")
    LOGGER.info("  - oos.parquet")
    LOGGER.info("SUCCESS!")


if __name__ == "__main__":
    main()
