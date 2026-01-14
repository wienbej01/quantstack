#!/usr/bin/env python3
"""
AAA Pattern Discovery - Integrated system with overfitting filters and 3-period validation

STREAMED PIPELINE: Processes data month-by-month to avoid full-year memory pressure.
"""

import argparse
import gc
import json
import sys
import tracemalloc
from datetime import date
from pathlib import Path

import pandas as pd
import psutil
import yaml

sys.path.insert(0, str(Path(__file__).parent))


def log_memory(stage: str) -> None:
    """Log current memory usage for debugging memory issues."""
    process = psutil.Process()
    mem_gb = process.memory_info().rss / 1e9
    if tracemalloc.is_tracing():
        current, peak = tracemalloc.get_traced_memory()
        print(f"[MEMORY] {stage}: RSS={mem_gb:.2f}GB, Peak={peak / 1e9:.2f}GB")
    else:
        print(f"[MEMORY] {stage}: RSS={mem_gb:.2f}GB")


def month_keys_for_range(start_date: date, end_date: date) -> list[str]:
    """Return YYYY_MM month keys covering a date range."""
    months = pd.period_range(start=start_date, end=end_date, freq="M")
    return [month.strftime("%Y_%m") for month in months]


def load_monthly_cache(
    cache_dir: Path,
    start_date: date,
    end_date: date,
    *,
    columns: list[str] | None = None,
    end_inclusive: bool = True,
) -> pd.DataFrame:
    """Load per-month cache files for a date range and filter by date."""
    month_keys = month_keys_for_range(start_date, end_date)
    dfs: list[pd.DataFrame] = []

    for month_key in month_keys:
        month_file = cache_dir / f"features_targets_{month_key}.parquet"
        if not month_file.exists():
            raise RuntimeError(f"Missing monthly cache file: {month_file}")
        read_columns = columns
        if columns is not None:
            try:
                import pyarrow.parquet as pq

                available = set(pq.ParquetFile(month_file).schema.names)
                read_columns = [col for col in columns if col in available]
            except Exception:
                read_columns = None

        month_df = pd.read_parquet(month_file, columns=read_columns)
        if "date" in month_df.columns:
            if end_inclusive:
                mask = (month_df["date"] >= start_date) & (month_df["date"] <= end_date)
            else:
                mask = (month_df["date"] >= start_date) & (month_df["date"] < end_date)
            month_df = month_df.loc[mask]
        dfs.append(month_df)

    if not dfs:
        raise RuntimeError("No monthly cache files loaded for the requested date range.")

    return pd.concat(dfs, ignore_index=True)


def load_volume_baseline_map(baseline_file: Path) -> dict[str, pd.Series]:
    """Load per-symbol volume baseline into a dict of Series keyed by symbol."""
    baseline_df = pd.read_parquet(baseline_file)
    if baseline_df.empty:
        return {}

    baseline_map: dict[str, pd.Series] = {}
    for symbol, group in baseline_df.groupby("symbol"):
        baseline_map[symbol] = group.set_index("minute_of_day")["avg_volume"]

    return baseline_map


def build_monthly_feature_target_cache(
    daily_cache_dir: Path,
    sip_dir: Path,
    spy_df: pd.DataFrame,
    volume_baseline: dict[str, pd.Series],
    start_date: str,
    end_date: str,
    horizons: list[int],
    output_dir: Path,
    keep_cols: list[str],
    rebuild: bool = False,
    warmup_days: int = 5,
    lookahead_days: int = 3,
) -> Path:
    """Build per-month feature/target cache without loading full-year data."""
    monthly_cache_dir = output_dir / "monthly_cache"
    monthly_cache_dir.mkdir(parents=True, exist_ok=True)

    trading_days = get_trading_days(start_date, end_date, sip_dir)
    if not trading_days:
        raise RuntimeError("No trading days found for the requested range.")

    day_to_idx = {day: idx for idx, day in enumerate(trading_days)}
    month_keys = month_keys_for_range(
        pd.to_datetime(start_date).date(),
        pd.to_datetime(end_date).date(),
    )

    for month_key in month_keys:
        month_file = monthly_cache_dir / f"features_targets_{month_key}.parquet"
        if month_file.exists() and not rebuild:
            continue

        month_start = pd.Period(month_key).start_time.date()
        month_end = pd.Period(month_key).end_time.date()

        month_days = [
            day for day in trading_days
            if month_start <= pd.to_datetime(day).date() <= month_end
        ]
        if not month_days:
            continue

        start_idx = day_to_idx[month_days[0]]
        end_idx = day_to_idx[month_days[-1]]
        warmup_start = max(0, start_idx - warmup_days)
        lookahead_end = min(len(trading_days) - 1, end_idx + lookahead_days)

        load_start = trading_days[warmup_start]
        load_end = trading_days[lookahead_end]

        print(f"\nBuilding cache for {month_key} ({load_start} -> {load_end})...")
        df = load_daily_cache_range(daily_cache_dir, load_start, load_end)
        if df.empty:
            print(f"  ⚠️ No data loaded for {month_key}")
            continue

        df = optimize_dataframe(df, exclude_cols={"ts"})
        df = compute_all_features(
            df,
            spy_df=spy_df,
            n_workers=1,
            volume_baseline=volume_baseline,
        )
        df = generate_targets(df, horizons, inplace=True)

        df["date"] = pd.to_datetime(df["ts"], unit="ns", utc=True).dt.date
        month_mask = (df["date"] >= month_start) & (df["date"] <= month_end)
        available_cols = [col for col in keep_cols if col in df.columns]
        df = df.loc[month_mask, available_cols]
        df = optimize_dataframe(df, exclude_cols={"ts"})

        df.to_parquet(month_file, index=False)
        print(f"  ✅ Saved {month_file.name}")

        del df
        gc.collect()

    return monthly_cache_dir


from src.data_loader import (
    build_daily_sip_cache,
    compute_volume_baseline,
    get_trading_days,
    load_daily_cache_range,
    load_symbol_bars_range,
)
from src.event_filter import EventFilter
from src.features import compute_all_features
from src.llm_analysis import format_patterns_for_llm
from src.memory_utils import optimize_dataframe

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
        patterns_df = patterns_df[patterns_df["rule"].apply(event_filter.is_event_based)].copy()
        print(f"  After event filter: {len(patterns_df)}/{initial_count} patterns")

    # Filter 2: Overfitting check
    if len(patterns_df) > 0:  # Only if patterns remain
        patterns_df["overfit_check"] = patterns_df.apply(
            lambda row: overfit_filter.is_overfit(row.to_dict()), axis=1
        )
        patterns_df["is_overfit"] = patterns_df["overfit_check"].apply(lambda x: x[0])
        patterns_df["overfit_reason"] = patterns_df["overfit_check"].apply(lambda x: x[1])

        rejected = patterns_df[patterns_df["is_overfit"]]
        if len(rejected) > 0:
            print(f"  Rejected {len(rejected)} overfit patterns:")
            for _, row in rejected.iterrows():
                print(f"    - {row['rule'][:50]}... : {row['overfit_reason']}")

        patterns_df = patterns_df[~patterns_df["is_overfit"]].copy()
        patterns_df = patterns_df.drop(columns=["overfit_check", "is_overfit", "overfit_reason"])
        print(f"  After overfit filter: {len(patterns_df)}/{initial_count} patterns")
    else:
        print(f"  After overfit filter: 0/{initial_count} patterns (no patterns to check)")

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
        print(f"  After regime filter: 0/{initial_count} patterns (no patterns to check)")

    return patterns_df


def main():
    # Start memory tracking
    tracemalloc.start()
    log_memory("Start")

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
    parser.add_argument("--skip-validation", action="store_true", help="Skip 3-period validation")
    parser.add_argument(
        "--use-aaa-scoring",
        action="store_true",
        help="Rank by AAA score instead of t-stat",
    )
    parser.add_argument(
        "--feature-workers",
        type=int,
        default=1,
        help="Deprecated (streamed pipeline forces n_workers=1 for memory safety).",
    )
    parser.add_argument(
        "--use-monthly-cache",
        action="store_true",
        help="Deprecated (streamed pipeline always uses monthly cache).",
    )
    parser.add_argument(
        "--rebuild-monthly-cache",
        action="store_true",
        help="Rebuild per-month cache files from the current dataset.",
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
    start_dt = pd.to_datetime(args.start_date).date()
    end_dt = pd.to_datetime(args.end_date).date()

    # Load configuration
    config_path = Path(__file__).parent / args.config
    config = load_config(config_path)

    sip_dir = Path(args.sip_dir)
    gold_dir = Path(args.gold_dir)
    output_dir = Path(__file__).parent / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("AAA PATTERN DISCOVERY (Overfitting Filters + 3-Period Validation)")
    print("STREAMED PIPELINE (MONTH-BY-MONTH)")
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
    print("\n[1/7] Building daily SIP cache...")
    metadata_cache_file = output_dir / "cached_metadata.json"
    daily_cache_dir, metadata = build_daily_sip_cache(
        args.start_date,
        args.end_date,
        sip_dir,
        gold_dir,
        output_dir,
    )
    with open(metadata_cache_file, "w") as f:
        json.dump(metadata, f, indent=2, default=str)
    print(f"  ✅ Daily cache ready at {daily_cache_dir}")

    print("\n[2/7] Loading SPY data for regime features...")
    lookback_days = (
        config["temporal_periods"]["scan_months"]
        + config["temporal_periods"]["validation_months"]
        + config["temporal_periods"]["oos_months"]
        + 1
    ) * 30
    spy_start = (pd.to_datetime(args.start_date) - pd.Timedelta(days=lookback_days + 60)).date()
    spy_df = load_symbol_bars_range(
        "SPY",
        spy_start.strftime("%Y-%m-%d"),
        args.end_date,
        gold_dir,
    )
    if spy_df.empty:
        print("  ⚠️ No SPY data found")
    else:
        print(f"  ✅ Loaded {len(spy_df):,} SPY bars")
    spy_df = optimize_dataframe(spy_df, exclude_cols={"ts"})

    print("\n[3/7] Detecting current market regime...")
    current_regime = regime_filter.detect_regime(spy_df)
    print(f"✅ Current regime: {current_regime}")

    print("\n[4/7] Building volume baseline...")
    baseline_file = compute_volume_baseline(
        daily_cache_dir,
        args.start_date,
        args.end_date,
        output_dir,
    )
    volume_baseline = load_volume_baseline_map(baseline_file)
    print(f"  ✅ Volume baseline ready at {baseline_file}")

    # Columns required for discovery/validation and cache loading.
    required_features = [
        "rel_underperform_extreme",
        "rel_outperform_extreme",
        "price_up_vol_weak",
        "price_down_vol_weak",
        "at_session_high",
        "at_session_low",
        "vwap_cross_up",
        "vwap_cross_down",
        "ret_60m",
        "rel_strength_60m",
        "session_range_pct",
        "rvol",
        "atr_14",
        "price_vs_vwap_pct",
        "is_first_hour",
        "is_power_hour",
    ]
    return_cols = [f"fwd_ret_{h}m" for h in horizons]
    keep_cols = {
        "ts",
        "symbol",
        "date",
        "spy_above_sma20",
        "spy_high_vol",
        *required_features,
        *return_cols,
    }
    keep_cols_list = list(keep_cols)
    print("\n[5/7] Building per-month feature/target cache...")
    monthly_cache_dir = build_monthly_feature_target_cache(
        daily_cache_dir,
        sip_dir,
        spy_df,
        volume_baseline,
        args.start_date,
        args.end_date,
        horizons,
        output_dir,
        keep_cols_list,
        rebuild=args.rebuild_monthly_cache,
        warmup_days=5,
        lookahead_days=3,
    )
    log_memory("After monthly cache build")

    # Split data for validation (load per-month cache)
    val_df_path = None
    oos_df_path = None

    if not args.skip_validation:
        print("\n[6/7] Splitting data for 3-period validation...")
        boundaries = temporal_split.get_boundaries(args.end_date)
        scan_df = load_monthly_cache(
            monthly_cache_dir,
            boundaries["scan_start"],
            boundaries["val_start"],
            columns=keep_cols_list,
            end_inclusive=False,
        )
        val_df = load_monthly_cache(
            monthly_cache_dir,
            boundaries["val_start"],
            boundaries["oos_start"],
            columns=keep_cols_list,
            end_inclusive=False,
        )
        oos_df = load_monthly_cache(
            monthly_cache_dir,
            boundaries["oos_start"],
            boundaries["end_date"],
            columns=keep_cols_list,
            end_inclusive=True,
        )
        period_info = {
            "scan": {
                "start": scan_df["date"].min(),
                "end": scan_df["date"].max(),
                "days": len(scan_df["date"].unique()),
                "bars": len(scan_df),
            },
            "validation": {
                "start": val_df["date"].min(),
                "end": val_df["date"].max(),
                "days": len(val_df["date"].unique()),
                "bars": len(val_df),
            },
            "oos": {
                "start": oos_df["date"].min(),
                "end": oos_df["date"].max(),
                "days": len(oos_df["date"].unique()),
                "bars": len(oos_df),
            },
        }
        for split_df in (scan_df, val_df, oos_df):
            if "date" in split_df.columns:
                split_df.drop(columns=["date"], inplace=True)

        print(
            "  Scan period: "
            f"{period_info['scan']['start']} to {period_info['scan']['end']} "
            f"({period_info['scan']['days']} days)"
        )
        print(
            "  Validation period: "
            f"{period_info['validation']['start']} to {period_info['validation']['end']} "
            f"({period_info['validation']['days']} days)"
        )
        print(
            "  OOS period: "
            f"{period_info['oos']['start']} to {period_info['oos']['end']} "
            f"({period_info['oos']['days']} days)"
        )

        # MEMORY-OPTIMIZED: Write val_df and oos_df to disk, free memory
        print("  Writing validation data to disk to free memory...")
        val_df_path = output_dir / "temp_validation.parquet"
        val_df.to_parquet(val_df_path, index=False)
        del val_df  # Free memory

        oos_df_path = output_dir / "temp_oos.parquet"
        oos_df.to_parquet(oos_df_path, index=False)
        del oos_df  # Free memory

        gc.collect()
        log_memory("After temporal split (val/oos written to disk)")
    else:
        scan_df = load_monthly_cache(
            monthly_cache_dir,
            start_dt,
            end_dt,
            columns=keep_cols_list,
            end_inclusive=True,
        )
        print("\n[6/7] Skipping validation split (using full dataset)")
        log_memory("After temporal split (no validation)")

    # Discover patterns
    print("\n[7/7] Discovering patterns with AAA filters...")
    log_memory("Before pattern discovery")

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
        f for f in high_alpha_events + state_features + time_context if f in scan_df.columns
    ]

    # Define regimes from scan_df (memory-efficient: avoid keeping full df in memory)
    # After temporal split, we only work with scan_df for pattern discovery
    regimes = {
        "bull_low_vol": (scan_df["spy_above_sma20"] == True)
        & (scan_df.get("spy_high_vol", False) == False),
        "bull_high_vol": (scan_df["spy_above_sma20"] == True)
        & (scan_df.get("spy_high_vol", False) == True),
        "bear_low_vol": (scan_df["spy_above_sma20"] == False)
        & (scan_df.get("spy_high_vol", False) == False),
        "bear_high_vol": (scan_df["spy_above_sma20"] == False)
        & (scan_df.get("spy_high_vol", False) == True),
    }

    all_patterns = []

    for horizon in horizons:
        return_col = f"fwd_ret_{horizon}m"
        if return_col not in scan_df.columns:
            continue

        for regime_name, regime_mask in regimes.items():
            # Apply regime mask to scan_df (no index lookup needed now)
            df_regime = scan_df[regime_mask].copy()

            # Apply regime mask to val_df (load from disk if needed)
            val_df_regime = None
            if val_df_path is not None:
                # MEMORY-OPTIMIZED: Load only needed columns and filter by regime
                val_cols = ["ts", "symbol", return_col, "spy_above_sma20", "spy_high_vol"]
                val_cols += feature_cols
                val_cols = [col for col in val_cols if col in scan_df.columns]
                val_df_full = pd.read_parquet(val_df_path, columns=val_cols)
                val_spy_above = val_df_full.get("spy_above_sma20", True)
                val_spy_high_vol = val_df_full.get("spy_high_vol", False)
                val_regime_mask = {
                    "bull_low_vol": (val_spy_above == True) & (val_spy_high_vol == False),
                    "bull_high_vol": (val_spy_above == True) & (val_spy_high_vol == True),
                    "bear_low_vol": (val_spy_above == False) & (val_spy_high_vol == False),
                    "bear_high_vol": (val_spy_above == False) & (val_spy_high_vol == True),
                }[regime_name]
                val_df_regime = val_df_full[val_regime_mask].copy()
                del val_df_full  # Free immediately
                gc.collect()

            if len(df_regime) < config["aaa_criteria"]["min_samples"]:
                if val_df_regime is not None:
                    del val_df_regime
                continue

            print(f"\n{'=' * 60}")
            print(f"REGIME: {regime_name} | HORIZON: {horizon}m")
            print(
                f"SAMPLES: {len(df_regime):,} | MIN_REQUIRED: {config['aaa_criteria']['min_samples']:,}"
            )
            print("=" * 60)

            # Discover LONG patterns
            print("\nDiscovering LONG patterns...")
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
                if not long_patterns.empty and val_df_regime is not None:
                    print(f"\n  Validating {len(long_patterns)} LONG patterns on holdout period...")
                    long_patterns_list = long_patterns.to_dict("records")
                    validated = validate_patterns(
                        long_patterns_list,
                        df_regime,
                        val_df_regime,
                        validation_gate,
                    )

                    if validated:
                        long_patterns = pd.DataFrame(validated)
                        print(f"  ✅ {len(long_patterns)} LONG patterns passed validation")
                    else:
                        print("  ⚠️ No LONG patterns passed validation")
                        long_patterns = pd.DataFrame()

                if not long_patterns.empty:
                    long_file = output_dir / f"patterns_long_{horizon}m_{regime_name}.csv"
                    long_patterns.to_csv(long_file, index=False)
                    print(f"✅ Saved {len(long_patterns)} validated AAA LONG patterns")
                    all_patterns.append(long_patterns)

            # Discover SHORT patterns
            print("\nDiscovering SHORT patterns...")
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
                if not short_patterns.empty and val_df_regime is not None:
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
                        print(f"  ✅ {len(short_patterns)} SHORT patterns passed validation")
                    else:
                        print("  ⚠️ No SHORT patterns passed validation")
                        short_patterns = pd.DataFrame()

                if not short_patterns.empty:
                    short_file = output_dir / f"patterns_short_{horizon}m_{regime_name}.csv"
                    short_patterns.to_csv(short_file, index=False)
                    print(f"✅ Saved {len(short_patterns)} validated AAA SHORT patterns")
                    all_patterns.append(short_patterns)

            # MEMORY-OPTIMIZED: Explicit cleanup before next iteration
            del df_regime, long_patterns, short_patterns
            if val_df_regime is not None:
                del val_df_regime
            gc.collect()
            log_memory(f"After {regime_name}/{horizon}m")

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
            top_patterns = all_patterns_df.head(config["llm_analysis"]["max_patterns_to_analyze"])
            llm_output = format_patterns_for_llm(
                top_patterns, "AAA Patterns", top_n=len(top_patterns)
            )

            llm_file = output_dir / "llm_analysis_aaa.md"
            with open(llm_file, "w") as f:
                f.write(llm_output)
            print(f"✅ LLM analysis saved to {llm_file}")
    else:
        print("\n⚠️ No patterns passed AAA filters")

    # Cleanup temp files
    if val_df_path is not None and val_df_path.exists():
        val_df_path.unlink()
        print("Cleaned up temporary validation file")
    if oos_df_path is not None and oos_df_path.exists():
        oos_df_path.unlink()
        print("Cleaned up temporary OOS file")

    log_memory("Final (before exit)")
    tracemalloc.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())
