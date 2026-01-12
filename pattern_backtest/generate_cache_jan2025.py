#!/usr/bin/env python3
"""Generate featured data cache for January 2025 pattern backtest."""

import pickle
import sys
from pathlib import Path

# Setup paths
root = Path("/home/jacobw/quantstack")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "sip_pattern_discovery"))
sys.path.insert(0, str(root / "sip_pattern_discovery" / "src"))

# Imports
try:
    import data_loader as sip_data_loader
    from features import compute_all_features

    print("✅ All imports successful")
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)

# Configuration
START_DATE = "2025-01-01"
END_DATE = "2025-01-31"
LOOKBACK_DAYS = 5
CACHE_FILE = (
    root / "pattern_backtest" / "cache" / f"featured_data_{START_DATE}_{END_DATE}.pkl"
)

sip_dir = Path("/home/jacobw/intraday_stack/data/daily_sip")
gold_dir = Path("/home/jacobw/gcs-mount/gold/stocks/1m")

print("=" * 80)
print("GENERATE FEATURED DATA CACHE - JANUARY 2025")
print("=" * 80)
print(f"Period: {START_DATE} to {END_DATE}")
print(f"Cache file: {CACHE_FILE}")
print("=" * 80)

# Create cache directory
CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

# Load SIP-filtered data
print("\n[1/3] Loading SIP-filtered data...")
df, spy_df, metadata = sip_data_loader.load_sip_filtered_data(
    START_DATE,
    END_DATE,
    LOOKBACK_DAYS,
    sip_dir,
    gold_dir,
)

if df.empty:
    print("❌ ERROR: No data loaded")
    sys.exit(1)

print(f"✅ Loaded {len(df):,} bars across {metadata['unique_symbols']} symbols")

# Compute features
print("\n[2/3] Computing features...")
df = compute_all_features(df, spy_df=spy_df, n_workers=2)

# Discretize features for pattern matching
print("\n[3/3] Discretizing features...")
import pandas as pd


def discretize_feature(series, n_bins=5):
    """Discretize a continuous feature into bins."""
    if series.nunique() <= 2:
        return series
    try:
        return pd.qcut(
            series, q=n_bins, labels=[0, 1, 2, 3, 4], duplicates="drop"
        ).fillna(2)
    except Exception:
        return pd.cut(series, bins=n_bins, labels=[0, 1, 2, 3, 4]).fillna(2)


# Discretize features used in patterns
feature_cols = [
    "atr_14",
    "session_range_pct",
    "rvol",
    "rel_strength_60m",
    "ret_60m",
    "price_vs_vwap_pct",
]

for col in feature_cols:
    if col in df.columns:
        df[f"{col}_bin"] = discretize_feature(df[col])

# Boolean features
bool_cols = [
    "is_first_hour",
    "is_power_hour",
    "rel_outperform_extreme",
    "rel_underperform_extreme",
    "price_up_vol_weak",
    "price_down_vol_weak",
    "price_up_vol_strong",
    "price_down_vol_strong",
]

for col in bool_cols:
    if col in df.columns:
        df[f"{col}_bin"] = df[col]

# Save cache
print(f"\nSaving cache to {CACHE_FILE}...")
with open(CACHE_FILE, "wb") as f:
    pickle.dump(df, f)

print(f"✅ Cached {len(df):,} bars with features")
print("=" * 80)
print("CACHE GENERATION COMPLETE")
print("=" * 80)
