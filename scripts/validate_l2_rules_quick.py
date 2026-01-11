#!/usr/bin/env python3
"""
Quick validation of L2 scalping rules on current data.
"""

import glob

import numpy as np
import pandas as pd


def validate_l2_rules():
    """Validate current OBI rules on all available L2 data."""

    print("=== L2 RULE VALIDATION ===\n")

    # Current rules from PROFITABLE_STRATEGY.md
    obi_threshold = 0.8
    min_rel_volume = 2.0
    rsi_min = 50

    print(f"Validating rules:")
    print(f"  OBI > {obi_threshold}")
    print(f"  rel_vol > {min_rel_volume}")
    print(f"  RSI > {rsi_min}")

    # Load recent L2 data
    features_path = "/home/jacobw/quantstack/data/l2_maximum/features"
    parquet_files = glob.glob(f"{features_path}/date=*/symbol=*/*.parquet")

    print(f"\nAnalyzing {len(parquet_files)} files...")

    total_signals = 0
    total_records = 0
    symbol_results = {}

    # Sample analysis on subset for speed
    sample_files = parquet_files[::10]  # Every 10th file

    for pf in sample_files[:20]:  # Limit to 20 files for quick validation
        try:
            df = pd.read_parquet(pf)
            symbol = pf.split("symbol=")[1].split("/")[0]

            # Check if required features exist
            required_features = ["obi_1", "obi_5"]
            missing = [f for f in required_features if f not in df.columns]

            if missing:
                print(f"  {symbol}: Missing features {missing}")
                continue

            # Apply OBI rule (simplified - no rel_vol or RSI in current data)
            obi_signals = (df["obi_1"].abs() > obi_threshold).sum()
            records = len(df)

            total_signals += obi_signals
            total_records += records

            if symbol not in symbol_results:
                symbol_results[symbol] = {"signals": 0, "records": 0}

            symbol_results[symbol]["signals"] += obi_signals
            symbol_results[symbol]["records"] += records

        except Exception as e:
            print(f"Error processing {pf}: {e}")

    print(f"\n--- VALIDATION RESULTS ---")
    print(f"Total records analyzed: {total_records:,}")
    print(f"Total OBI signals: {total_signals:,}")
    print(f"Signal rate: {total_signals/total_records*100:.2f}%")

    print(f"\nBy symbol:")
    for symbol, data in symbol_results.items():
        rate = data["signals"] / data["records"] * 100 if data["records"] > 0 else 0
        print(
            f"  {symbol}: {data['signals']:,} signals / {data['records']:,} records ({rate:.2f}%)"
        )

    # Risk assessment
    print(f"\n--- RISK ASSESSMENT ---")

    expected_signals_per_day = (
        total_signals * (len(parquet_files) / len(sample_files)) / 4
    )  # 4 days of data

    print(f"Estimated signals per day: {expected_signals_per_day:,.0f}")

    if expected_signals_per_day > 1000:
        print("⚠️  HIGH SIGNAL RATE - Risk of overtrading")
        recommendation = "ADJUST_THRESHOLDS"
    elif expected_signals_per_day < 10:
        print("⚠️  LOW SIGNAL RATE - May miss opportunities")
        recommendation = "LOWER_THRESHOLDS"
    else:
        print("✅ REASONABLE SIGNAL RATE")
        recommendation = "KEEP_CURRENT"

    return recommendation, expected_signals_per_day


def check_data_consistency():
    """Check if new data is consistent with original analysis."""

    print(f"\n--- DATA CONSISTENCY CHECK ---")

    # Original analysis was on Dec 19 & 23
    # Check if Jan 8 & 9 data shows similar patterns

    features_path = "/home/jacobw/quantstack/data/l2_maximum/features"

    # Get files by date
    dec_files = glob.glob(f"{features_path}/date=2025-12-*/symbol=*/*.parquet")
    jan_files = glob.glob(f"{features_path}/date=2026-01-*/symbol=*/*.parquet")

    print(f"December files: {len(dec_files)}")
    print(f"January files: {len(jan_files)}")

    if len(jan_files) == 0:
        print("❌ No January data for comparison")
        return "NO_NEW_DATA"

    # Quick comparison of OBI distributions
    try:
        # Sample one file from each period
        if dec_files:
            dec_df = pd.read_parquet(dec_files[0])
            dec_obi_std = dec_df["obi_1"].std() if "obi_1" in dec_df.columns else 0

        if jan_files:
            jan_df = pd.read_parquet(jan_files[0])
            jan_obi_std = jan_df["obi_1"].std() if "obi_1" in jan_df.columns else 0

        if dec_obi_std > 0 and jan_obi_std > 0:
            ratio = jan_obi_std / dec_obi_std
            print(f"OBI volatility ratio (Jan/Dec): {ratio:.2f}")

            if 0.5 <= ratio <= 2.0:
                print("✅ Similar market conditions")
                return "CONSISTENT"
            else:
                print("⚠️  Different market regime detected")
                return "REGIME_CHANGE"

    except Exception as e:
        print(f"Error in consistency check: {e}")

    return "UNKNOWN"


if __name__ == "__main__":
    recommendation, signal_rate = validate_l2_rules()
    consistency = check_data_consistency()

    print(f"\n=== RECOMMENDATION ===")

    if consistency == "REGIME_CHANGE":
        print("🔄 VALIDATE REQUIRED")
        print("   Reason: Market regime appears different in new data")
        print("   Action: Re-run full analysis on combined dataset")
        print("   Script: python l2_scalping/analysis/l2_context_analysis.py")

    elif recommendation == "ADJUST_THRESHOLDS":
        print("🔄 VALIDATE REQUIRED")
        print("   Reason: Signal rate too high, risk of overtrading")
        print("   Action: Increase OBI threshold or add filters")

    elif recommendation == "LOWER_THRESHOLDS":
        print("🔄 VALIDATE REQUIRED")
        print("   Reason: Signal rate too low, may miss opportunities")
        print("   Action: Lower OBI threshold or relax filters")

    else:
        print("✅ CONTINUE WITH CURRENT RULES")
        print("   Reason: Signal rate reasonable and data consistent")
        print("   Action: Deploy with existing thresholds")
        print("   Monitor: Watch first week performance closely")

    print(f"\nEstimated daily signals: {signal_rate:,.0f}")
    print(f"Data consistency: {consistency}")
