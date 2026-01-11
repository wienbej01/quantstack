#!/usr/bin/env python3
"""SIP Pattern Discovery CLI - Find statistically significant trading patterns."""

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
        description="Discover trading patterns ranked by t-statistic"
    )

    parser.add_argument("--start-date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument(
        "--horizons",
        default="30,60,90,180",
        help="Forward horizons in minutes (comma-separated)",
    )
    parser.add_argument(
        "--min-t-stat",
        type=float,
        default=2.0,
        help="Minimum t-statistic (2.0 = 95%% confidence)",
    )
    parser.add_argument(
        "--min-expectancy",
        type=float,
        default=0.1,
        help="Minimum expectancy per trade (%%)",
    )
    parser.add_argument(
        "--min-trades",
        type=int,
        default=50,
        help="Minimum number of trades for pattern",
    )
    parser.add_argument(
        "--max-patterns",
        type=int,
        default=10,
        help="Maximum patterns per direction per horizon",
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

    horizons = [int(h) for h in args.horizons.split(",")]

    sip_dir = Path(args.sip_dir)
    gold_dir = Path(args.gold_dir)
    output_dir = Path(__file__).parent / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("SIP PATTERN DISCOVERY (t-statistic ranking)")
    print("=" * 80)
    print(f"Date range: {args.start_date} to {args.end_date}")
    print(f"Horizons: {horizons} minutes")
    print(f"Min t-stat: {args.min_t_stat} (95%+ confidence)")
    print(f"Min expectancy: {args.min_expectancy}% per trade")
    print(f"Min trades: {args.min_trades}")
    print(f"Output: {output_dir}")
    print("=" * 80)

    # Step 1: Load data (with caching)
    print("\n[1/4] Loading SIP-filtered data...")

    cache_file = output_dir / "cached_data.parquet"
    spy_cache_file = output_dir / "cached_spy_data.parquet"
    metadata_cache_file = output_dir / "cached_metadata.json"

    if cache_file.exists() and spy_cache_file.exists() and metadata_cache_file.exists():
        print("  Found cached data, loading from cache...")
        df = pd.read_parquet(cache_file)
        spy_df = pd.read_parquet(spy_cache_file)
        with open(metadata_cache_file) as f:
            metadata = json.load(f)
        print(f"  Loaded {len(df):,} bars from cache")
    else:
        print("  No cache found, loading from source...")
        df, spy_df, metadata = load_sip_filtered_data(
            args.start_date,
            args.end_date,
            args.lookback_days,
            sip_dir,
            gold_dir,
        )

        if df.empty:
            print("ERROR: No data loaded. Check date range and data paths.")
            return 1

        # Cache the data
        print("  Caching data for future runs...")
        df.to_parquet(cache_file)
        spy_df.to_parquet(spy_cache_file)
        with open(metadata_cache_file, "w") as f:
            json.dump(metadata, f, indent=2, default=str)

    print(f"Loaded {len(df):,} bars")
    print(f"Symbols: {metadata['unique_symbols']}")
    print(f"Trading days: {metadata['trading_days']}")

    # Step 2: Compute features (with caching)
    print("\n[2/4] Computing features...")

    features_cache_file = output_dir / "cached_features.parquet"

    if features_cache_file.exists():
        print("  Found cached features, loading from cache...")
        df = pd.read_parquet(features_cache_file)
        print(f"  Loaded {len(df):,} bars with features from cache")
    else:
        print("  No feature cache found, computing features...")
        df = compute_all_features(df, spy_df)

        # Cache the features
        print("  Caching features for future runs...")
        df.to_parquet(features_cache_file)

    # Step 3: Generate targets (with caching)
    print("\n[3/4] Generating forward returns...")

    targets_cache_file = output_dir / "cached_targets.parquet"

    if targets_cache_file.exists():
        print("  Found cached targets, loading from cache...")
        df = pd.read_parquet(targets_cache_file)
        print(f"  Loaded {len(df):,} bars with targets from cache")
    else:
        print("  No target cache found, generating targets...")
        df = generate_targets(df, horizons)

        # Cache the targets
        print("  Caching targets for future runs...")
        df.to_parquet(targets_cache_file)

    # Step 4: Discover patterns
    print("\n[4/4] Discovering patterns...")

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
        "spy_above_sma20",
        "spy_ret_60m",
    ]

    all_patterns = []

    for horizon in horizons:
        return_col = f"fwd_ret_{horizon}m"

        if return_col not in df.columns:
            print(f"  Skipping {horizon}m - no return column")
            continue

        # LONG patterns (positive returns)
        print(f"\nDiscovering LONG patterns for {horizon}m horizon...")
        long_patterns = discover_patterns(
            df,
            feature_cols,
            return_col,
            direction="LONG",
            min_t_stat=args.min_t_stat,
            min_expectancy=args.min_expectancy,
            min_trades=args.min_trades,
            max_patterns=args.max_patterns,
        )

        if not long_patterns.empty:
            long_file = output_dir / f"patterns_long_{horizon}m.csv"
            long_patterns.to_csv(long_file, index=False)
            print(f"  Saved {len(long_patterns)} LONG patterns to {long_file}")
            all_patterns.append(long_patterns)

        # SHORT patterns (negative returns)
        print(f"\nDiscovering SHORT patterns for {horizon}m horizon...")
        short_patterns = discover_patterns(
            df,
            feature_cols,
            return_col,
            direction="SHORT",
            min_t_stat=args.min_t_stat,
            min_expectancy=args.min_expectancy,
            min_trades=args.min_trades,
            max_patterns=args.max_patterns,
        )

        if not short_patterns.empty:
            short_file = output_dir / f"patterns_short_{horizon}m.csv"
            short_patterns.to_csv(short_file, index=False)
            print(f"  Saved {len(short_patterns)} SHORT patterns to {short_file}")
            all_patterns.append(short_patterns)

    # Combine all patterns
    if all_patterns:
        combined = pd.concat(all_patterns, ignore_index=True)
        combined = combined.sort_values("t_stat", ascending=False).reset_index(
            drop=True
        )

        combined_file = output_dir / "patterns_all.csv"
        combined.to_csv(combined_file, index=False)
        print(f"\nSaved {len(combined)} total patterns to {combined_file}")

        # Print top patterns
        print("\n" + "=" * 80)
        print("TOP 10 PATTERNS BY T-STATISTIC")
        print("=" * 80)
        cols = [
            "rule",
            "direction",
            "horizon",
            "t_stat",
            "expectancy",
            "win_rate",
            "profit_factor",
            "n_trades",
        ]
        print(combined[cols].head(10).to_string(index=False))

        # LLM analysis
        if not args.skip_llm:
            print("\n[5/5] Running LLM analysis...")

            # Analyze top patterns per horizon/direction
            for horizon in horizons:
                for direction in ["LONG", "SHORT"]:
                    patterns_subset = combined[
                        (combined["horizon"] == f"fwd_ret_{horizon}m")
                        & (combined["direction"] == direction)
                    ]

                    if not patterns_subset.empty:
                        report_file = (
                            output_dir
                            / f"llm_analysis_{direction.lower()}_{horizon}m.md"
                        )
                        analyze_patterns_with_llm(
                            patterns_subset,
                            f"fwd_ret_{horizon}m",
                            horizon,
                            report_file,
                            top_n=min(10, len(patterns_subset)),
                        )
        else:
            print("\n[5/5] Skipping LLM analysis")
    else:
        print("\nNo patterns found meeting criteria")

    # Save metadata
    metadata["run_timestamp"] = datetime.now().isoformat()
    metadata["args"] = vars(args)
    metadata["total_patterns"] = len(combined) if all_patterns else 0

    metadata_file = output_dir / "discovery_metadata.json"
    with open(metadata_file, "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    print("\n" + "=" * 80)
    print("DISCOVERY COMPLETE")
    print("=" * 80)
    print(f"Output directory: {output_dir}")
    print(f"Total patterns found: {len(combined) if all_patterns else 0}")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    sys.exit(main())
