#!/usr/bin/env python3
"""Quick test of fixed system on small dataset."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# Import the feature engineering function
from scripts.build_intraday_features_rolling import (
    engineer_features,
    load_intraday_bars,
)


def test_single_symbol_day():
    """Test feature generation on single symbol/day."""
    print("=" * 80)
    print("TESTING FIXED SYSTEM")
    print("=" * 80)

    # Test on AAPL, 2024-05-01
    symbol = "AAPL"
    date = "2024-05-01"

    print(f"\nLoading {symbol} for {date}...")
    df = load_intraday_bars(symbol, date)

    if df is None or len(df) == 0:
        print(f"ERROR: No data for {symbol} on {date}")
        return

    print(f"Loaded {len(df)} bars")

    print("\nEngineering features...")
    features = engineer_features(df, date)

    if len(features) == 0:
        print("ERROR: No features generated")
        return

    print(f"Generated {len(features)} feature rows")

    # Convert to pandas for analysis
    df_pd = features.to_pandas()

    # Validation checks
    print("\n" + "=" * 80)
    print("VALIDATION CHECKS")
    print("=" * 80)

    # Check 1: Entry after signal
    entry_after = (df_pd["entry_timestamp"] > df_pd["timestamp"]).all()
    print(f"\n✓ Entry after signal: {entry_after}")
    if not entry_after:
        bad_rows = df_pd[df_pd["entry_timestamp"] <= df_pd["timestamp"]]
        print(f"  ERROR: {len(bad_rows)} rows have entry <= signal")
        print(bad_rows[["timestamp", "entry_timestamp"]].head())

    # Check 2: Same-day entry
    df_pd["signal_date"] = df_pd["timestamp"].dt.date
    df_pd["entry_date"] = df_pd["entry_timestamp"].dt.date
    same_day_entry = (df_pd["signal_date"] == df_pd["entry_date"]).all()
    print(f"✓ Same-day entry: {same_day_entry}")
    if not same_day_entry:
        bad_rows = df_pd[df_pd["signal_date"] != df_pd["entry_date"]]
        print(f"  ERROR: {len(bad_rows)} rows have cross-day entry")

    # Check 3: Same-day exit
    df_pd["exit_date"] = df_pd["exit_timestamp"].dt.date
    same_day_exit = (df_pd["entry_date"] == df_pd["exit_date"]).all()
    print(f"✓ Same-day exit: {same_day_exit}")
    if not same_day_exit:
        bad_rows = df_pd[df_pd["entry_date"] != df_pd["exit_date"]]
        print(f"  ERROR: {len(bad_rows)} rows have cross-day exit")

    # Check 4: ATR present
    has_atr = "atr" in df_pd.columns and not df_pd["atr"].isna().all()
    print(f"✓ ATR calculated: {has_atr}")
    if has_atr:
        print(f"  ATR range: [{df_pd['atr'].min():.4f}, {df_pd['atr'].max():.4f}]")

    # Check 5: Entry/exit prices present
    has_entry = "entry_close" in df_pd.columns and not df_pd["entry_close"].isna().all()
    has_exit = "exit_close" in df_pd.columns and not df_pd["exit_close"].isna().all()
    print(f"✓ Entry prices: {has_entry}")
    print(f"✓ Exit prices: {has_exit}")

    # Check 6: Labels
    long_pct = df_pd["label_long"].mean()
    short_pct = df_pd["label_short"].mean()
    print("✓ Label distribution:")
    print(f"  LONG: {long_pct:.2%}")
    print(f"  SHORT: {short_pct:.2%}")
    print(f"  NEUTRAL: {1 - long_pct - short_pct:.2%}")

    # Sample rows
    print("\n" + "=" * 80)
    print("SAMPLE ROWS")
    print("=" * 80)
    print(
        df_pd[
            [
                "timestamp",
                "entry_timestamp",
                "exit_timestamp",
                "close",
                "entry_close",
                "exit_close",
                "atr",
                "label_long",
                "label_short",
            ]
        ]
        .head(10)
        .to_string()
    )

    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)

    if entry_after and same_day_entry and same_day_exit and has_atr:
        print("\n✅ ALL CHECKS PASSED")
        return True
    else:
        print("\n❌ SOME CHECKS FAILED")
        return False


if __name__ == "__main__":
    success = test_single_symbol_day()
    sys.exit(0 if success else 1)
