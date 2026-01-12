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

    # HIGH ALPHA EVENT features (actual entry signals)
    high_alpha_events = [
        # Cross-ticker relative strength (HIGHEST ALPHA)
        "rel_underperform_extreme",  # Stock underperforming SPY by >1%
        "rel_outperform_extreme",  # Stock outperforming SPY by >1%
        # Volume-price divergence (HIGH ALPHA)
        "price_up_vol_weak",  # Price up but volume weak = bearish
        "price_down_vol_weak",  # Price down but volume weak = bullish
        "price_up_vol_strong",  # Price up on strong volume = bullish
        "price_down_vol_strong",  # Price down on strong volume = bearish
        # Session range (MEDIUM ALPHA)
        "at_session_high",  # At session high = potential reversal
        "at_session_low",  # At session low = potential reversal
        "new_session_high",  # Breaking session high = continuation
        "new_session_low",  # Breaking session low = continuation
        # VWAP crosses (MEDIUM ALPHA)
        "vwap_cross_up",
        "vwap_cross_down",
        "avwap_cross_up",
        "avwap_cross_down",
    ]

    # STATE features (for context, discretized)
    state_features = [
        "ret_60m",  # Recent momentum
        "rel_strength_60m",  # Relative strength vs SPY
        "session_range_pct",  # Position in session range
        "rvol",  # Relative volume
        "atr_14",  # Volatility
        "price_vs_vwap_pct",  # Distance from VWAP
    ]

    # Time context (as filters, not entry signals)
    time_context = [
        "is_first_hour",
        "is_power_hour",
    ]

    # Build feature list from available columns
    available_events = [f for f in high_alpha_events if f in df.columns]
    available_states = [f for f in state_features if f in df.columns]
    available_time = [f for f in time_context if f in df.columns]

    print(f"\nFeature Summary:")
    print(f"  High-alpha events: {len(available_events)}")
    print(f"  State features: {len(available_states)}")
    print(f"  Time context: {len(available_time)}")

    feature_cols = available_events + available_states + available_time

    # Define regimes (for data segmentation, not as features)
    regimes = {
        "bull": df["spy_above_sma20"] == True,
        "bear": df["spy_above_sma20"] == False,
    }

    # Add volatility split if available
    if "spy_high_vol" in df.columns:
        regimes = {
            "bull_low_vol": (df["spy_above_sma20"] == True)
            & (df["spy_high_vol"] == False),
            "bull_high_vol": (df["spy_above_sma20"] == True)
            & (df["spy_high_vol"] == True),
            "bear_low_vol": (df["spy_above_sma20"] == False)
            & (df["spy_high_vol"] == False),
            "bear_high_vol": (df["spy_above_sma20"] == False)
            & (df["spy_high_vol"] == True),
        }

    # Print regime distribution
    print("\n" + "=" * 80)
    print("REGIME DISTRIBUTION")
    print("=" * 80)
    for regime_name, regime_mask in regimes.items():
        n_samples = regime_mask.sum()
        pct = n_samples / len(df) * 100
        print(f"{regime_name:20s}: {n_samples:6,} samples ({pct:5.1f}%)")

    all_patterns = []

    for horizon in horizons:
        return_col = f"fwd_ret_{horizon}m"

        if return_col not in df.columns:
            print(f"  Skipping {horizon}m - no return column")
            continue

        # Discover patterns for each regime
        for regime_name, regime_mask in regimes.items():
            df_regime = df[regime_mask].copy()

            if len(df_regime) < args.min_trades * 2:
                print(
                    f"\n[{regime_name}] Skipping - insufficient samples ({len(df_regime)})"
                )
                continue

            print(f"\n{'=' * 80}")
            print(
                f"REGIME: {regime_name.upper()} | HORIZON: {horizon}m | SAMPLES: {len(df_regime):,}"
            )
            print("=" * 80)

            # LONG patterns
            print(f"\nDiscovering LONG patterns...")
            long_patterns = discover_patterns(
                df_regime,
                feature_cols,
                return_col,
                direction="LONG",
                min_t_stat=args.min_t_stat,
                min_expectancy=args.min_expectancy,
                min_trades=args.min_trades,
                max_patterns=args.max_patterns,
            )

            if not long_patterns.empty:
                long_patterns["regime"] = regime_name
                long_file = output_dir / f"patterns_long_{horizon}m_{regime_name}.csv"
                long_patterns.to_csv(long_file, index=False)
                print(f"  Saved {len(long_patterns)} LONG patterns to {long_file}")
                all_patterns.append(long_patterns)

            # SHORT patterns
            print(f"\nDiscovering SHORT patterns...")
            short_patterns = discover_patterns(
                df_regime,
                feature_cols,
                return_col,
                direction="SHORT",
                min_t_stat=args.min_t_stat,
                min_expectancy=args.min_expectancy,
                min_trades=args.min_trades,
                max_patterns=args.max_patterns,
            )

            if not short_patterns.empty:
                short_patterns["regime"] = regime_name
                short_file = output_dir / f"patterns_short_{horizon}m_{regime_name}.csv"
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
            "n_samples" if "n_samples" in combined.columns else "n_trades",
        ]
        cols = [c for c in cols if c in combined.columns]
        print(combined[cols].head(10).to_string(index=False))

        # LLM analysis
        if not args.skip_llm:
            from src.llm_analysis import analyze_consolidated_patterns

            print("\n[5/5] Running consolidated LLM analysis...")

            # Single consolidated analysis (recommended)
            consolidated_file = output_dir / "llm_analysis_consolidated.md"
            analyze_consolidated_patterns(
                combined,
                consolidated_file,
                top_n=30,
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
