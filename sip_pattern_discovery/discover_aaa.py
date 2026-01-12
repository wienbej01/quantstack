#!/usr/bin/env python3
"""
AAA Pattern Discovery - Integrated system with overfitting filters and 3-period validation
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).parent))

from src.aaa_scorer import AAAScorer
from src.data_loader import load_sip_filtered_data
from src.event_filter import EventFilter
from src.features import compute_all_features
from src.llm_analysis import analyze_patterns_with_llm, format_patterns_for_llm

# AAA filters
from src.overfitting_filter import OverfittingFilter
from src.pattern_engine import discover_patterns
from src.regime_filter import RegimeFilter
from src.targets import generate_targets
from src.temporal_split import TemporalSplit
from src.validation_backtest import validate_patterns
from src.validation_gate import ValidationGate


def load_config(config_path: Path) -> dict:
    """Load AAA configuration."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def apply_aaa_filters(
    patterns_df: pd.DataFrame,
    overfit_filter: OverfittingFilter,
    event_filter: EventFilter,
    regime_filter: RegimeFilter,
    current_regime: str,
    require_event: bool = True,
    require_regime_match: bool = True,
) -> pd.DataFrame:
    """Apply AAA filters to discovered patterns."""

    if patterns_df.empty:
        return patterns_df

    initial_count = len(patterns_df)

    # Filter 1: Event-based only
    if require_event:
        patterns_df = patterns_df[
            patterns_df["rule"].apply(event_filter.is_event_based)
        ].copy()
        print(f"  After event filter: {len(patterns_df)}/{initial_count} patterns")

    # Filter 2: Overfitting check
    if len(patterns_df) > 0:  # Only if patterns remain
        patterns_df["overfit_check"] = patterns_df.apply(
            lambda row: overfit_filter.is_overfit(row.to_dict()), axis=1
        )
        patterns_df["is_overfit"] = patterns_df["overfit_check"].apply(lambda x: x[0])
        patterns_df["overfit_reason"] = patterns_df["overfit_check"].apply(
            lambda x: x[1]
        )

        rejected = patterns_df[patterns_df["is_overfit"]]
        if len(rejected) > 0:
            print(f"  Rejected {len(rejected)} overfit patterns:")
            for _, row in rejected.iterrows():
                print(f"    - {row['rule'][:50]}... : {row['overfit_reason']}")

        patterns_df = patterns_df[~patterns_df["is_overfit"]].copy()
        patterns_df = patterns_df.drop(
            columns=["overfit_check", "is_overfit", "overfit_reason"]
        )
        print(f"  After overfit filter: {len(patterns_df)}/{initial_count} patterns")
    else:
        print(
            f"  After overfit filter: 0/{initial_count} patterns (no patterns to check)"
        )

    # Filter 3: Regime match
    if require_regime_match and current_regime and len(patterns_df) > 0:
        patterns_df = patterns_df[patterns_df["regime"] == current_regime]
        print(
            f"  After regime filter: {len(patterns_df)}/{initial_count} patterns (regime: {current_regime})"
        )
    elif len(patterns_df) > 0:
        print(
            f"  After regime filter: {len(patterns_df)}/{initial_count} patterns (no regime filter)"
        )
    else:
        print(
            f"  After regime filter: 0/{initial_count} patterns (no patterns to check)"
        )

    return patterns_df


def main():
    parser = argparse.ArgumentParser(
        description="AAA Pattern Discovery with overfitting filters and 3-period validation"
    )

    parser.add_argument("--start-date", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="End date YYYY-MM-DD")
    parser.add_argument(
        "--horizons",
        default="30,60,90,120",
        help="Forward horizons in minutes (comma-separated)",
    )
    parser.add_argument(
        "--config",
        default="config/aaa_config.yaml",
        help="AAA configuration file",
    )
    parser.add_argument("--output-dir", default="output_aaa", help="Output directory")
    parser.add_argument("--skip-llm", action="store_true", help="Skip LLM analysis")
    parser.add_argument(
        "--skip-validation", action="store_true", help="Skip 3-period validation"
    )
    parser.add_argument(
        "--use-aaa-scoring",
        action="store_true",
        help="Rank by AAA score instead of t-stat",
    )
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

    # Load configuration
    config_path = Path(__file__).parent / args.config
    config = load_config(config_path)

    sip_dir = Path(args.sip_dir)
    gold_dir = Path(args.gold_dir)
    output_dir = Path(__file__).parent / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("AAA PATTERN DISCOVERY (Overfitting Filters + 3-Period Validation)")
    print("=" * 80)
    print(f"Date range: {args.start_date} to {args.end_date}")
    print(f"Horizons: {horizons} minutes")
    print(f"AAA Scoring: {args.use_aaa_scoring}")
    print(f"Output: {output_dir}")
    print("=" * 80)

    # Initialize AAA filters
    print("\nInitializing AAA filters...")
    overfit_filter = OverfittingFilter(
        max_win_rate=config["aaa_criteria"]["max_win_rate"],
        max_sharpe=config["aaa_criteria"]["max_sharpe"],
        max_expectancy=config["aaa_criteria"]["max_expectancy"],
        min_samples=config["aaa_criteria"]["min_samples"],
    )

    regime_filter = RegimeFilter(
        sma_period=config["regime_detection"]["sma_period"],
        vol_threshold=config["regime_detection"]["vol_threshold"],
    )

    event_filter = EventFilter()

    temporal_split = TemporalSplit(
        scan_months=config["temporal_periods"]["scan_months"],
        validation_months=config["temporal_periods"]["validation_months"],
        oos_months=config["temporal_periods"]["oos_months"],
    )

    validation_gate = ValidationGate(
        max_win_rate_drop=config["validation_gates"]["max_win_rate_drop"],
        max_expectancy_drop_pct=config["validation_gates"]["max_expectancy_drop_pct"],
        max_sharpe_drop_pct=config["validation_gates"]["max_sharpe_drop_pct"],
        min_validation_trades=config["validation_gates"]["min_validation_trades"],
    )

    print("✅ AAA filters initialized")

    # Load data
    print("\n[1/5] Loading SIP-filtered data...")
    cache_file = output_dir / "cached_data.parquet"
    spy_cache_file = output_dir / "cached_spy_data.parquet"
    metadata_cache_file = output_dir / "cached_metadata.json"

    if cache_file.exists() and spy_cache_file.exists():
        print("  Loading from cache...")
        df = pd.read_parquet(cache_file)
        spy_df = pd.read_parquet(spy_cache_file)
        with open(metadata_cache_file) as f:
            metadata = json.load(f)
        print(f"  ✅ Loaded {len(df):,} bars from cache")
    else:
        print("  Loading from source (this may take 2-3 minutes)...")
        lookback_days = (
            config["temporal_periods"]["scan_months"]
            + config["temporal_periods"]["validation_months"]
            + 1
        )
        df, spy_df, metadata = load_sip_filtered_data(
            args.start_date,
            args.end_date,
            lookback_days,
            sip_dir,
            gold_dir,
        )
        print(f"  Caching for future runs...")
        df.to_parquet(cache_file)
        spy_df.to_parquet(spy_cache_file)
        with open(metadata_cache_file, "w") as f:
            json.dump(metadata, f, indent=2, default=str)
        print(f"  ✅ Loaded and cached {len(df):,} bars")

    # Detect current regime
    print("\n[2/5] Detecting current market regime...")
    current_regime = regime_filter.detect_regime(spy_df)
    print(f"✅ Current regime: {current_regime}")

    # Compute features
    print("\n[3/5] Computing features...")
    features_cache_file = output_dir / "cached_features.parquet"
    if features_cache_file.exists():
        print("  Loading features from cache...")
        df = pd.read_parquet(features_cache_file)
        print(f"  ✅ Loaded {len(df):,} bars with features")
    else:
        print("  Computing features (this may take 1-2 minutes)...")
        df = compute_all_features(df, spy_df)
        print("  Caching features...")
        df.to_parquet(features_cache_file)
        print(f"  ✅ Computed and cached features")

    # Generate targets
    print("  Generating forward returns...")
    targets_cache_file = output_dir / "cached_targets.parquet"
    if targets_cache_file.exists():
        print("  Loading targets from cache...")
        df = pd.read_parquet(targets_cache_file)
    else:
        print("  Computing forward returns...")
        df = generate_targets(df, horizons)
        print("  Caching targets...")
        df.to_parquet(targets_cache_file)

    print(f"✅ Features and targets ready ({len(df):,} bars)")

    # Split data for validation
    if not args.skip_validation:
        print("\n[4/5] Splitting data for 3-period validation...")
        scan_df, val_df, oos_df = temporal_split.split_data(df, args.end_date)
        period_info = temporal_split.get_period_info(df, args.end_date)

        print(
            f"  Scan period: {period_info['scan']['start']} to {period_info['scan']['end']} ({period_info['scan']['days']} days)"
        )
        print(
            f"  Validation period: {period_info['validation']['start']} to {period_info['validation']['end']} ({period_info['validation']['days']} days)"
        )
        print(
            f"  OOS period: {period_info['oos']['start']} to {period_info['oos']['end']} ({period_info['oos']['days']} days)"
        )
    else:
        scan_df = df
        print("\n[4/5] Skipping validation split (using full dataset)")

    # Discover patterns
    print("\n[5/5] Discovering patterns with AAA filters...")

    # Feature columns
    high_alpha_events = [
        "rel_underperform_extreme",
        "rel_outperform_extreme",
        "price_up_vol_weak",
        "price_down_vol_weak",
        "at_session_high",
        "at_session_low",
        "vwap_cross_up",
        "vwap_cross_down",
    ]
    state_features = [
        "ret_60m",
        "rel_strength_60m",
        "session_range_pct",
        "rvol",
        "atr_14",
        "price_vs_vwap_pct",
    ]
    time_context = ["is_first_hour", "is_power_hour"]

    feature_cols = [
        f
        for f in high_alpha_events + state_features + time_context
        if f in scan_df.columns
    ]

    # Define regimes
    regimes = {
        "bull_low_vol": (df["spy_above_sma20"] == True)
        & (df.get("spy_high_vol", False) == False),
        "bull_high_vol": (df["spy_above_sma20"] == True)
        & (df.get("spy_high_vol", False) == True),
        "bear_low_vol": (df["spy_above_sma20"] == False)
        & (df.get("spy_high_vol", False) == False),
        "bear_high_vol": (df["spy_above_sma20"] == False)
        & (df.get("spy_high_vol", False) == True),
    }

    all_patterns = []

    for horizon in horizons:
        return_col = f"fwd_ret_{horizon}m"
        if return_col not in scan_df.columns:
            continue

        for regime_name, regime_mask in regimes.items():
            # Apply regime mask to scan_df
            scan_regime_mask = regime_mask.loc[scan_df.index]
            df_regime = scan_df[scan_regime_mask].copy()

            # Apply regime mask to val_df
            val_regime_mask = regime_mask.loc[val_df.index]
            val_df_regime = val_df[val_regime_mask].copy()

            if len(df_regime) < config["aaa_criteria"]["min_samples"]:
                continue

            print(f"\n{'=' * 60}")
            print(f"REGIME: {regime_name} | HORIZON: {horizon}m")
            print(
                f"SAMPLES: {len(df_regime):,} | MIN_REQUIRED: {config['aaa_criteria']['min_samples']:,}"
            )
            print("=" * 60)

            # Discover LONG patterns
            print(f"\nDiscovering LONG patterns...")
            long_patterns = discover_patterns(
                df_regime,
                feature_cols,
                return_col,
                direction="LONG",
                min_t_stat=3.0,  # Lower threshold for testing
                min_expectancy=0.005,  # Lower threshold (0.5% vs 2%)
                min_trades=config["aaa_criteria"]["min_samples"],
                max_patterns=config["deployment"]["max_strategies"] * 3,
                use_aaa_scoring=args.use_aaa_scoring,
                current_regime=current_regime,
            )

            if not long_patterns.empty:
                long_patterns["regime"] = regime_name

                # Apply AAA filters
                long_patterns = apply_aaa_filters(
                    long_patterns,
                    overfit_filter,
                    event_filter,
                    regime_filter,
                    current_regime,
                    require_event=config["aaa_criteria"]["require_event_based"],
                    require_regime_match=config["aaa_criteria"]["require_regime_match"],
                )

                # Validate on holdout period
                if not long_patterns.empty and not args.skip_validation:
                    print(
                        f"\n  Validating {len(long_patterns)} LONG patterns on holdout period..."
                    )
                    long_patterns_list = long_patterns.to_dict("records")
                    validated = validate_patterns(
                        long_patterns_list,
                        df_regime,
                        val_df_regime,
                        validation_gate,
                    )

                    if validated:
                        long_patterns = pd.DataFrame(validated)
                        print(
                            f"  ✅ {len(long_patterns)} LONG patterns passed validation"
                        )
                    else:
                        print(f"  ⚠️ No LONG patterns passed validation")
                        long_patterns = pd.DataFrame()

                if not long_patterns.empty:
                    long_file = (
                        output_dir / f"patterns_long_{horizon}m_{regime_name}.csv"
                    )
                    long_patterns.to_csv(long_file, index=False)
                    print(f"✅ Saved {len(long_patterns)} validated AAA LONG patterns")
                    all_patterns.append(long_patterns)

            # Discover SHORT patterns
            print(f"\nDiscovering SHORT patterns...")
            short_patterns = discover_patterns(
                df_regime,
                feature_cols,
                return_col,
                direction="SHORT",
                min_t_stat=3.0,
                min_expectancy=0.005,
                min_trades=config["aaa_criteria"]["min_samples"],
                max_patterns=config["deployment"]["max_strategies"] * 3,
                use_aaa_scoring=args.use_aaa_scoring,
                current_regime=current_regime,
            )

            if not short_patterns.empty:
                short_patterns["regime"] = regime_name

                short_patterns = apply_aaa_filters(
                    short_patterns,
                    overfit_filter,
                    event_filter,
                    regime_filter,
                    current_regime,
                    require_event=config["aaa_criteria"]["require_event_based"],
                    require_regime_match=config["aaa_criteria"]["require_regime_match"],
                )

                # Validate on holdout period
                if not short_patterns.empty and not args.skip_validation:
                    print(
                        f"\n  Validating {len(short_patterns)} SHORT patterns on holdout period..."
                    )
                    short_patterns_list = short_patterns.to_dict("records")
                    validated = validate_patterns(
                        short_patterns_list,
                        df_regime,
                        val_df_regime,
                        validation_gate,
                    )

                    if validated:
                        short_patterns = pd.DataFrame(validated)
                        print(
                            f"  ✅ {len(short_patterns)} SHORT patterns passed validation"
                        )
                    else:
                        print(f"  ⚠️ No SHORT patterns passed validation")
                        short_patterns = pd.DataFrame()

                if not short_patterns.empty:
                    short_file = (
                        output_dir / f"patterns_short_{horizon}m_{regime_name}.csv"
                    )
                    short_patterns.to_csv(short_file, index=False)
                    print(
                        f"✅ Saved {len(short_patterns)} validated AAA SHORT patterns"
                    )
                    all_patterns.append(short_patterns)

    # Consolidate and rank
    if all_patterns:
        all_patterns_df = pd.concat(all_patterns, ignore_index=True)

        # Rank by AAA score or t-stat
        if args.use_aaa_scoring and "aaa_score" in all_patterns_df.columns:
            all_patterns_df = all_patterns_df.sort_values("aaa_score", ascending=False)
        else:
            all_patterns_df = all_patterns_df.sort_values("t_stat", ascending=False)

        all_file = output_dir / "patterns_all_aaa.csv"
        all_patterns_df.to_csv(all_file, index=False)

        print(f"\n{'=' * 80}")
        print(f"✅ DISCOVERY COMPLETE: {len(all_patterns_df)} AAA patterns")
        print(f"✅ Saved to {all_file}")
        print("=" * 80)

        # LLM analysis
        if not args.skip_llm:
            print("\nRunning LLM analysis on top patterns...")
            top_patterns = all_patterns_df.head(
                config["llm_analysis"]["max_patterns_to_analyze"]
            )
            llm_output = format_patterns_for_llm(
                top_patterns, "AAA Patterns", top_n=len(top_patterns)
            )

            llm_file = output_dir / "llm_analysis_aaa.md"
            with open(llm_file, "w") as f:
                f.write(llm_output)
            print(f"✅ LLM analysis saved to {llm_file}")
    else:
        print("\n⚠️ No patterns passed AAA filters")

    return 0


if __name__ == "__main__":
    sys.exit(main())
