#!/usr/bin/env python3
"""SIP Pattern Discovery CLI - Find high-lift trading patterns from 1m data."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from src.data_loader import load_sip_filtered_data
from src.features import compute_all_features
from src.llm_analysis import analyze_patterns_with_llm
from src.pattern_engine import discover_patterns
from src.targets import generate_targets


def main():
    parser = argparse.ArgumentParser(
        description="Discover trading patterns from SIP-filtered 1m data"
    )

    parser.add_argument("--start-date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument(
        "--horizons",
        default="60,120,180",
        help="Forward horizons in minutes (comma-separated)",
    )
    parser.add_argument(
        "--min-lift",
        type=float,
        default=3.0,
        help="Minimum lift threshold (higher = fewer, better patterns)",
    )
    parser.add_argument(
        "--min-support",
        type=float,
        default=0.01,
        help="Minimum support threshold (higher = more frequent patterns)",
    )
    parser.add_argument(
        "--max-p-value",
        type=float,
        default=0.001,
        help="Maximum p-value for significance (lower = more significant)",
    )
    parser.add_argument(
        "--max-patterns",
        type=int,
        default=10,
        help="Maximum patterns per direction (top N only)",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=5,
        help="Days of lookback for feature warmup",
    )
    parser.add_argument("--output-dir", default="output", help="Output directory")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM analysis")
    parser.add_argument(
        "--sip-dir",
        default="/home/jacobw/intraday_stack/data/daily_sip",
        help="SIP directory",
    )
    parser.add_argument(
        "--gold-dir",
        default="/home/jacobw/gcs-mount/gold/stocks/1m",
        help="Gold data directory",
    )

    args = parser.parse_args()

    # Parse horizons
    horizons = [int(h) for h in args.horizons.split(",")]

    # Setup paths
    sip_dir = Path(args.sip_dir)
    gold_dir = Path(args.gold_dir)
    output_dir = Path(__file__).parent / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("SIP PATTERN DISCOVERY")
    print("=" * 80)
    print(f"Date range: {args.start_date} to {args.end_date}")
    print(f"Horizons: {horizons} minutes")
    print(f"Min lift: {args.min_lift}x")
    print(f"Min support: {args.min_support:.2%}")
    print(f"Max p-value: {args.max_p_value}")
    print(f"Output: {output_dir}")
    print("=" * 80)

    # Step 1: Load data
    print("\n[1/5] Loading SIP-filtered data...")
    df, metadata = load_sip_filtered_data(
        args.start_date,
        args.end_date,
        args.lookback_days,
        sip_dir,
        gold_dir,
    )

    if df.empty:
        print("ERROR: No data loaded. Check date range and data paths.")
        return 1

    print(f"Loaded {len(df):,} bars")
    print(f"Symbols: {metadata['unique_symbols']}")
    print(f"Trading days: {metadata['trading_days']}")

    # Step 2: Compute features
    print("\n[2/5] Computing features...")
    df = compute_all_features(df)

    # Step 3: Generate targets
    print("\n[3/5] Generating targets...")
    df = generate_targets(df, horizons)

    # Step 4: Discover patterns
    print("\n[4/5] Discovering patterns...")

    feature_cols = [
        "ret_5m",
        "ret_15m",
        "ret_30m",
        "ret_60m",
        "price_vs_vwap_pct",
        "price_vs_session_avwap_pct",
        "rvol",
        "atr_14",
        "is_first_hour",
        "is_power_hour",
    ]

    all_patterns = {}

    for horizon in horizons:
        # Discover UP patterns
        up_target_col = f"up_{horizon}m"
        if up_target_col in df.columns:
            print(f"\nDiscovering UP patterns for {up_target_col}...")
            up_patterns = discover_patterns(
                df,
                feature_cols,
                up_target_col,
                min_lift=args.min_lift,
                min_support=args.min_support,
                max_p_value=args.max_p_value,
            )

            if not up_patterns.empty:
                print(f"Found {len(up_patterns)} UP patterns for {up_target_col}")
                up_patterns["direction"] = "LONG"
                up_patterns["target"] = up_target_col

                # Keep only top N highest-lift patterns
                up_patterns = up_patterns.head(args.max_patterns)
                print(f"Keeping top {len(up_patterns)} highest-lift UP patterns")

                # Save UP patterns
                up_patterns_file = output_dir / f"patterns_up_{horizon}m.csv"
                up_patterns.to_csv(up_patterns_file, index=False)
                print(f"Saved to {up_patterns_file}")

                all_patterns[f"up_{horizon}m"] = up_patterns

        # Discover DOWN patterns
        down_target_col = f"down_{horizon}m"
        if down_target_col in df.columns:
            print(f"\nDiscovering DOWN patterns for {down_target_col}...")
            down_patterns = discover_patterns(
                df,
                feature_cols,
                down_target_col,
                min_lift=args.min_lift,
                min_support=args.min_support,
                max_p_value=args.max_p_value,
            )

            if not down_patterns.empty:
                print(f"Found {len(down_patterns)} DOWN patterns for {down_target_col}")
                down_patterns["direction"] = "SHORT"
                down_patterns["target"] = down_target_col

                # Keep only top N highest-lift patterns
                down_patterns = down_patterns.head(args.max_patterns)
                print(f"Keeping top {len(down_patterns)} highest-lift DOWN patterns")

                # Save DOWN patterns
                down_patterns_file = output_dir / f"patterns_down_{horizon}m.csv"
                down_patterns.to_csv(down_patterns_file, index=False)
                print(f"Saved to {down_patterns_file}")

                all_patterns[f"down_{horizon}m"] = down_patterns

        # Combine UP and DOWN patterns for this horizon
        horizon_patterns = []
        if f"up_{horizon}m" in all_patterns:
            horizon_patterns.append(all_patterns[f"up_{horizon}m"])
        if f"down_{horizon}m" in all_patterns:
            horizon_patterns.append(all_patterns[f"down_{horizon}m"])

        if horizon_patterns:
            combined = pd.concat(horizon_patterns, ignore_index=True)
            combined = combined.sort_values("lift", ascending=False).reset_index(
                drop=True
            )

            # Save combined patterns
            combined_file = output_dir / f"patterns_combined_{horizon}m.csv"
            combined.to_csv(combined_file, index=False)
            print(f"Saved combined patterns to {combined_file}")

            all_patterns[f"combined_{horizon}m"] = combined

    # Step 5: LLM analysis
    if not args.skip_llm and all_patterns:
        print("\n[5/5] Running LLM analysis...")

        for target_col, patterns in all_patterns.items():
            if "combined" in target_col:
                continue  # Skip combined files for LLM analysis

            horizon = int(target_col.split("_")[1].replace("m", ""))
            direction = "UP" if "up_" in target_col else "DOWN"
            report_file = output_dir / f"llm_analysis_{direction.lower()}_{horizon}m.md"

            analyze_patterns_with_llm(
                patterns,
                target_col,
                horizon,
                report_file,
                top_n=20,
            )
    else:
        print("\n[5/5] Skipping LLM analysis")

    # Save metadata
    metadata["run_timestamp"] = datetime.now().isoformat()
    metadata["args"] = vars(args)
    metadata["patterns_found"] = {k: len(v) for k, v in all_patterns.items()}

    metadata_file = output_dir / "discovery_metadata.json"
    with open(metadata_file, "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    print("\n" + "=" * 80)
    print("DISCOVERY COMPLETE")
    print("=" * 80)
    print(f"Output directory: {output_dir}")
    print(f"Patterns found: {sum(len(v) for v in all_patterns.values())}")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
