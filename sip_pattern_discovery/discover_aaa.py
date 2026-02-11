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
import yaml

sys.path.insert(0, str(Path(__file__).parent))

try:
    import psutil
except ModuleNotFoundError:
    psutil = None


def log_memory(stage: str) -> None:
    """Log current memory usage for debugging memory issues."""
    if psutil is None:
        print(f"[MEMORY] {stage}: psutil not available")
        return

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
        raise RuntimeError(
            "No monthly cache files loaded for the requested date range."
        )

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

    def missing_columns(month_file: Path, required_cols: list[str]) -> list[str] | None:
        try:
            import pyarrow.parquet as pq
        except Exception:
            return None

        try:
            available = set(pq.ParquetFile(month_file).schema.names)
        except Exception:
            return None

        return [col for col in required_cols if col not in available]

    for month_key in month_keys:
        month_file = monthly_cache_dir / f"features_targets_{month_key}.parquet"
        if month_file.exists() and not rebuild:
            missing = missing_columns(month_file, keep_cols)
            if missing is None or not missing:
                continue
            print(f"  ⚠️ {month_file.name} missing {len(missing)} columns; rebuilding")

        month_period = pd.Period(month_key.replace("_", "-"), freq="M")
        month_start = month_period.start_time.date()
        month_end = month_period.end_time.date()

        month_days = [
            day
            for day in trading_days
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
from src.pattern_engine import discover_patterns, discretize_features
from src.regime_filter import RegimeFilter
from src.targets import generate_targets
from src.temporal_split import TemporalSplit
from src.validation_backtest import validate_patterns_with_diagnostics
from src.validation_gate import ValidationGate


def load_config(config_path: Path) -> dict:
    """Load AAA configuration."""
    with open(config_path) as f:
        return yaml.safe_load(f)


def apply_aaa_filters(
    patterns_df: pd.DataFrame,
    overfit_filter: OverfittingFilter,
    event_filter: EventFilter,
    _regime_filter: RegimeFilter,
    current_regime: str,
    require_event: bool = True,
    require_regime_match: bool = True,
    overfit_policy: str = "reject",
    min_aaa_score: float | None = None,
    filter_out: bool = True,
) -> pd.DataFrame:
    """Apply AAA filters to discovered patterns."""

    if patterns_df.empty:
        return patterns_df

    patterns_df = patterns_df.copy()
    initial_count = len(patterns_df)

    patterns_df["is_event_based"] = patterns_df["rule"].apply(
        event_filter.is_event_based
    )
    patterns_df["passes_event_filter"] = True
    if require_event:
        patterns_df["passes_event_filter"] = patterns_df["is_event_based"]

    # Overfitting check (always computed for diagnostics)
    patterns_df["overfit_check"] = patterns_df.apply(
        lambda row: overfit_filter.is_overfit(row.to_dict()), axis=1
    )
    patterns_df["is_overfit"] = patterns_df["overfit_check"].apply(lambda x: x[0])
    patterns_df["overfit_reason"] = patterns_df["overfit_check"].apply(lambda x: x[1])
    patterns_df["overfit_risk"] = patterns_df.apply(
        lambda row: overfit_filter.calculate_overfit_risk(row.to_dict()), axis=1
    )
    patterns_df["passes_overfit_filter"] = ~patterns_df["is_overfit"]

    patterns_df["passes_regime_filter"] = True
    if require_regime_match and current_regime:
        patterns_df["passes_regime_filter"] = (
            patterns_df.get("regime") == current_regime
        )

    patterns_df["passes_aaa_score"] = True
    if min_aaa_score is not None:
        if "aaa_score" in patterns_df.columns:
            patterns_df["passes_aaa_score"] = patterns_df["aaa_score"] >= min_aaa_score
        else:
            print("  ⚠️ min_aaa_score set but aaa_score missing; skipping filter")

    overfit_policy_normalized = str(overfit_policy).strip().lower()
    if overfit_policy_normalized not in {"reject", "score_only"}:
        raise ValueError(
            f"Invalid overfit_policy={overfit_policy!r}. Expected 'reject' or 'score_only'."
        )

    # Apply filters (but keep diagnostics columns).
    mask = (
        patterns_df["passes_event_filter"]
        & patterns_df["passes_regime_filter"]
        & patterns_df["passes_aaa_score"]
    )
    if overfit_policy_normalized == "reject":
        mask = mask & patterns_df["passes_overfit_filter"]

    patterns_df["passes_aaa_filters"] = mask
    filtered = patterns_df[mask].copy() if filter_out else patterns_df.copy()

    print(
        f"  Event filter: {patterns_df['passes_event_filter'].sum()}/{initial_count} pass"
    )
    print(
        f"  Overfit filter ({overfit_policy_normalized}): "
        f"{patterns_df['passes_overfit_filter'].sum()}/{initial_count} pass"
    )
    print(
        f"  Regime filter: {patterns_df['passes_regime_filter'].sum()}/{initial_count} pass"
    )
    print(
        f"  AAA score filter: {patterns_df['passes_aaa_score'].sum()}/{initial_count} pass"
    )
    print(f"✅ {int(mask.sum())}/{initial_count} patterns passed AAA filters")

    return filtered


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
    parser.add_argument(
        "--skip-validation", action="store_true", help="Skip 3-period validation"
    )
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

    diagnostics_cfg = config.get("diagnostics", {})
    diagnostics_enabled = bool(diagnostics_cfg.get("enabled", True))
    diagnostics_dir = output_dir / "diagnostics"
    segments_dir = diagnostics_dir / "segments"
    if diagnostics_enabled:
        segments_dir.mkdir(parents=True, exist_ok=True)
        run_config_file = diagnostics_dir / "run_config.json"
        with open(run_config_file, "w") as f:
            json.dump(
                {
                    "start_date": args.start_date,
                    "end_date": args.end_date,
                    "horizons": horizons,
                    "config_path": str(config_path),
                    "config": config,
                },
                f,
                indent=2,
                default=str,
            )

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

    event_filter_cfg = config.get("event_filter", {})
    event_keywords = event_filter_cfg.get("keywords") or config.get(
        "aaa_criteria", {}
    ).get("event_keywords")
    event_filter = EventFilter(
        event_keywords=event_keywords,
        trigger_keywords=event_filter_cfg.get("trigger_keywords"),
        context_keywords=event_filter_cfg.get("context_keywords"),
        require_trigger=bool(event_filter_cfg.get("require_trigger", True)),
    )

    temporal_split = TemporalSplit(
        scan_months=config["temporal_periods"]["scan_months"],
        validation_months=config["temporal_periods"]["validation_months"],
        oos_months=config["temporal_periods"]["oos_months"],
    )

    validation_gates_cfg = config.get("validation_gates", {})
    validation_gate = ValidationGate(
        max_win_rate_drop=validation_gates_cfg["max_win_rate_drop"],
        max_expectancy_drop_pct=validation_gates_cfg["max_expectancy_drop_pct"],
        max_sharpe_drop_pct=validation_gates_cfg["max_sharpe_drop_pct"],
        min_validation_trades=validation_gates_cfg["min_validation_trades"],
        cost_bps=float(validation_gates_cfg.get("cost_bps", 0.0)),
        min_net_expectancy_bps=validation_gates_cfg.get("min_net_expectancy_bps"),
    )
    dedupe_by_symbol_day = bool(validation_gates_cfg.get("dedupe_by_symbol_day", False))
    dedupe_policy = str(validation_gates_cfg.get("dedupe_policy", "first"))
    if dedupe_policy not in {"first", "last"}:
        raise ValueError(
            "validation_gates.dedupe_policy must be 'first' or 'last', "
            f"got {dedupe_policy!r}"
        )

    min_aaa_score = config.get("deployment", {}).get("min_aaa_score")
    if min_aaa_score is not None:
        try:
            min_aaa_score = float(min_aaa_score)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"deployment.min_aaa_score must be numeric, got {min_aaa_score!r}"
            ) from exc
        if min_aaa_score <= 0:
            min_aaa_score = None

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
    spy_start = (
        pd.to_datetime(args.start_date) - pd.Timedelta(days=lookback_days + 60)
    ).date()
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
        "price_up_vol_strong",
        "price_down_vol_strong",
        "at_session_high",
        "at_session_low",
        "new_session_high",
        "new_session_low",
        "vwap_cross_up",
        "vwap_cross_down",
        "avwap_cross_up",
        "avwap_cross_down",
        "ret_5m",
        "ret_15m",
        "ret_30m",
        "ret_60m",
        "ret_5m_turned_positive",
        "ret_5m_turned_negative",
        "ret_15m_turned_positive",
        "ret_15m_turned_negative",
        "ret_30m_turned_positive",
        "ret_30m_turned_negative",
        "ret_60m_turned_positive",
        "ret_60m_turned_negative",
        "rel_strength_60m",
        "session_range_pct",
        "rvol",
        "atr_14",
        "price_vs_vwap_pct",
        "is_first_hour",
        "is_power_hour",
        "first_hour_start",
        "power_hour_start",
        "last_30min_start",
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
        "price_up_vol_strong",
        "price_down_vol_strong",
        "at_session_high",
        "at_session_low",
        "new_session_high",
        "new_session_low",
        "vwap_cross_up",
        "vwap_cross_down",
        "avwap_cross_up",
        "avwap_cross_down",
        "ret_5m_turned_positive",
        "ret_5m_turned_negative",
        "ret_15m_turned_positive",
        "ret_15m_turned_negative",
        "ret_30m_turned_positive",
        "ret_30m_turned_negative",
        "ret_60m_turned_positive",
        "ret_60m_turned_negative",
    ]
    state_features = [
        "ret_5m",
        "ret_15m",
        "ret_30m",
        "ret_60m",
        "rel_strength_60m",
        "session_range_pct",
        "rvol",
        "atr_14",
        "price_vs_vwap_pct",
    ]
    time_context = [
        "is_first_hour",
        "is_power_hour",
        "first_hour_start",
        "power_hour_start",
        "last_30min_start",
    ]

    feature_cols = [
        f
        for f in high_alpha_events + state_features + time_context
        if f in scan_df.columns
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

    discovery_cfg = config.get("discovery", {})
    n_bins = int(discovery_cfg.get("n_bins", 5))
    max_conditions = int(discovery_cfg.get("max_conditions", 2))
    min_t_stat = float(discovery_cfg.get("min_t_stat", 3.0))
    min_expectancy = float(discovery_cfg.get("min_expectancy", 0.005))
    discovery_min_samples = int(
        discovery_cfg.get("min_samples", config["aaa_criteria"]["min_samples"])
    )
    max_patterns_pre_filter = int(
        discovery_cfg.get(
            "max_patterns_pre_filter",
            config["deployment"]["max_strategies"] * 25,
        )
    )
    actionable_bin_values = discovery_cfg.get("actionable_bin_values")
    include_false_for_binary = bool(
        discovery_cfg.get("include_false_for_binary", False)
    )
    max_candidate_rules = discovery_cfg.get("max_candidate_rules")
    if max_candidate_rules is not None:
        max_candidate_rules = int(max_candidate_rules)

    overfit_policy = config.get("aaa_criteria", {}).get("overfit_policy", "reject")

    segment_summaries: list[dict] = []
    all_patterns: list[pd.DataFrame] = []

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
                val_cols = [
                    "ts",
                    "symbol",
                    return_col,
                    "spy_above_sma20",
                    "spy_high_vol",
                ]
                val_cols += feature_cols
                val_cols = [col for col in val_cols if col in scan_df.columns]
                val_df_full = pd.read_parquet(val_df_path, columns=val_cols)
                val_spy_above = val_df_full.get("spy_above_sma20", True)
                val_spy_high_vol = val_df_full.get("spy_high_vol", False)
                val_regime_mask = {
                    "bull_low_vol": (val_spy_above == True)
                    & (val_spy_high_vol == False),
                    "bull_high_vol": (val_spy_above == True)
                    & (val_spy_high_vol == True),
                    "bear_low_vol": (val_spy_above == False)
                    & (val_spy_high_vol == False),
                    "bear_high_vol": (val_spy_above == False)
                    & (val_spy_high_vol == True),
                }[regime_name]
                val_df_regime = val_df_full[val_regime_mask].copy()
                del val_df_full  # Free immediately
                gc.collect()

            if len(df_regime) < discovery_min_samples:
                if val_df_regime is not None:
                    del val_df_regime
                continue

            print(f"\n{'=' * 60}")
            print(f"REGIME: {regime_name} | HORIZON: {horizon}m")
            print(
                f"SAMPLES: {len(df_regime):,} | MIN_REQUIRED: {discovery_min_samples:,}"
            )
            print("=" * 60)

            segment_key_base = f"{regime_name}__{horizon}m"
            bin_edges: dict[str, list[float] | None] | None = None

            # Discover LONG patterns
            print("\nDiscovering LONG patterns...")
            long_raw, bin_edges = discover_patterns(
                df_regime,
                feature_cols,
                return_col,
                direction="LONG",
                min_t_stat=min_t_stat,
                min_expectancy=min_expectancy,
                min_trades=discovery_min_samples,
                max_patterns=max_patterns_pre_filter,
                max_conditions=max_conditions,
                n_bins=n_bins,
                use_aaa_scoring=args.use_aaa_scoring,
                current_regime=current_regime,
                actionable_bin_values=actionable_bin_values,
                include_false_for_binary=include_false_for_binary,
                max_candidate_rules=max_candidate_rules,
                return_bin_edges=True,
            )
            if not long_raw.empty:
                long_raw["regime"] = regime_name

            if diagnostics_enabled and bin_edges is not None:
                edges_file = segments_dir / f"{segment_key_base}__bin_edges.json"
                with open(edges_file, "w") as f:
                    json.dump(bin_edges, f, indent=2, default=str)

            # Prepare validation binning (must match scan bin edges).
            if bin_edges is not None and val_df_regime is not None:
                val_df_regime, _ = discretize_features(
                    val_df_regime,
                    feature_cols,
                    n_bins,
                    bin_edges=bin_edges,
                )

            long_candidates = long_raw
            if not long_candidates.empty:
                long_candidates = apply_aaa_filters(
                    long_candidates,
                    overfit_filter,
                    event_filter,
                    regime_filter,
                    current_regime,
                    require_event=config["aaa_criteria"]["require_event_based"],
                    require_regime_match=config["aaa_criteria"]["require_regime_match"],
                    overfit_policy=overfit_policy,
                    min_aaa_score=min_aaa_score,
                    filter_out=False,
                )

            long_validation_df = pd.DataFrame()
            long_validation_diag_df = pd.DataFrame()
            if (
                not args.skip_validation
                and val_df_regime is not None
                and not long_candidates.empty
            ):
                to_validate = long_candidates[
                    long_candidates["passes_aaa_filters"]
                ].copy()
                if not to_validate.empty:
                    print(
                        f"\n  Validating {len(to_validate)} LONG patterns on holdout period..."
                    )
                    validated, diagnostics = validate_patterns_with_diagnostics(
                        to_validate.to_dict("records"),
                        df_regime,
                        val_df_regime,
                        validation_gate,
                        dedupe_by_symbol_day=dedupe_by_symbol_day,
                        dedupe_policy=dedupe_policy,
                        recompute_scan_metrics=dedupe_by_symbol_day,
                    )
                    long_validation_diag_df = pd.DataFrame(diagnostics)
                    if validated:
                        long_validation_df = pd.DataFrame(validated)

            if not long_candidates.empty and not long_validation_diag_df.empty:
                long_candidates = long_candidates.merge(
                    long_validation_diag_df,
                    on=["rule", "direction", "horizon"],
                    how="left",
                )

            long_final = long_candidates
            if not long_final.empty:
                final_mask = long_final["passes_aaa_filters"]
                if not args.skip_validation and val_df_regime is not None:
                    if "validation_passed" not in long_final.columns:
                        long_final["validation_passed"] = False
                    final_mask = final_mask & (long_final["validation_passed"] == True)
                long_final = long_final[final_mask].copy()

            if diagnostics_enabled:
                candidates_file = (
                    segments_dir / f"{segment_key_base}__long_candidates.csv"
                )
                long_candidates.to_csv(candidates_file, index=False)

            long_summary: dict = {
                "regime": regime_name,
                "horizon_m": horizon,
                "direction": "LONG",
                "return_col": return_col,
                "n_rows_scan": int(len(df_regime)),
                "n_rows_val": (
                    int(len(val_df_regime)) if val_df_regime is not None else 0
                ),
                "n_patterns_raw": int(len(long_raw)),
                "n_pass_event_filter": (
                    int(long_candidates["passes_event_filter"].sum())
                    if not long_candidates.empty
                    else 0
                ),
                "n_pass_overfit_filter": (
                    int(long_candidates["passes_overfit_filter"].sum())
                    if not long_candidates.empty
                    else 0
                ),
                "n_pass_regime_filter": (
                    int(long_candidates["passes_regime_filter"].sum())
                    if not long_candidates.empty
                    else 0
                ),
                "n_pass_aaa_score": (
                    int(long_candidates["passes_aaa_score"].sum())
                    if (
                        not long_candidates.empty
                        and "passes_aaa_score" in long_candidates
                    )
                    else 0
                ),
                "n_pass_aaa_filters": (
                    int(long_candidates["passes_aaa_filters"].sum())
                    if not long_candidates.empty
                    else 0
                ),
                "n_pass_validation": (
                    int(long_final["validation_passed"].sum())
                    if (
                        not args.skip_validation
                        and val_df_regime is not None
                        and not long_final.empty
                    )
                    else (int(len(long_final)) if not long_final.empty else 0)
                ),
            }
            if (
                diagnostics_enabled
                and not long_candidates.empty
                and "overfit_reason" in long_candidates
            ):
                rejected = long_candidates[long_candidates["is_overfit"]]
                long_summary["top_overfit_reasons"] = (
                    rejected["overfit_reason"].value_counts().head(10).to_dict()
                    if not rejected.empty
                    else {}
                )
            if (
                diagnostics_enabled
                and not long_validation_diag_df.empty
                and "validation_reason" in long_validation_diag_df
            ):
                long_summary["top_validation_reasons"] = (
                    long_validation_diag_df["validation_reason"]
                    .value_counts()
                    .head(10)
                    .to_dict()
                )

            segment_summaries.append(long_summary)

            if diagnostics_enabled:
                summary_file = diagnostics_dir / "summary.json"
                with open(summary_file, "w") as f:
                    json.dump(segment_summaries, f, indent=2, default=str)

            if not long_final.empty:
                long_file = output_dir / f"patterns_long_{horizon}m_{regime_name}.csv"
                long_final.to_csv(long_file, index=False)
                print(f"✅ Saved {len(long_final)} validated AAA LONG patterns")
                all_patterns.append(long_final)

            # Discover SHORT patterns
            print("\nDiscovering SHORT patterns...")
            short_raw = discover_patterns(
                df_regime,
                feature_cols,
                return_col,
                direction="SHORT",
                min_t_stat=min_t_stat,
                min_expectancy=min_expectancy,
                min_trades=discovery_min_samples,
                max_patterns=max_patterns_pre_filter,
                max_conditions=max_conditions,
                n_bins=n_bins,
                use_aaa_scoring=args.use_aaa_scoring,
                current_regime=current_regime,
                actionable_bin_values=actionable_bin_values,
                include_false_for_binary=include_false_for_binary,
                max_candidate_rules=max_candidate_rules,
                bin_edges=bin_edges,
            )

            if not short_raw.empty:
                short_raw["regime"] = regime_name

            short_candidates = short_raw
            if not short_candidates.empty:
                short_candidates = apply_aaa_filters(
                    short_candidates,
                    overfit_filter,
                    event_filter,
                    regime_filter,
                    current_regime,
                    require_event=config["aaa_criteria"]["require_event_based"],
                    require_regime_match=config["aaa_criteria"]["require_regime_match"],
                    overfit_policy=overfit_policy,
                    min_aaa_score=min_aaa_score,
                    filter_out=False,
                )

            short_validation_diag_df = pd.DataFrame()
            if (
                not args.skip_validation
                and val_df_regime is not None
                and not short_candidates.empty
            ):
                to_validate = short_candidates[
                    short_candidates["passes_aaa_filters"]
                ].copy()
                if not to_validate.empty:
                    print(
                        f"\n  Validating {len(to_validate)} SHORT patterns on holdout period..."
                    )
                    validated, diagnostics = validate_patterns_with_diagnostics(
                        to_validate.to_dict("records"),
                        df_regime,
                        val_df_regime,
                        validation_gate,
                        dedupe_by_symbol_day=dedupe_by_symbol_day,
                        dedupe_policy=dedupe_policy,
                        recompute_scan_metrics=dedupe_by_symbol_day,
                    )
                    short_validation_diag_df = pd.DataFrame(diagnostics)

            if not short_candidates.empty and not short_validation_diag_df.empty:
                short_candidates = short_candidates.merge(
                    short_validation_diag_df,
                    on=["rule", "direction", "horizon"],
                    how="left",
                )

            short_final = short_candidates
            if not short_final.empty:
                final_mask = short_final["passes_aaa_filters"]
                if not args.skip_validation and val_df_regime is not None:
                    if "validation_passed" not in short_final.columns:
                        short_final["validation_passed"] = False
                    final_mask = final_mask & (short_final["validation_passed"] == True)
                short_final = short_final[final_mask].copy()

            if diagnostics_enabled:
                candidates_file = (
                    segments_dir / f"{segment_key_base}__short_candidates.csv"
                )
                short_candidates.to_csv(candidates_file, index=False)

            short_summary: dict = {
                "regime": regime_name,
                "horizon_m": horizon,
                "direction": "SHORT",
                "return_col": return_col,
                "n_rows_scan": int(len(df_regime)),
                "n_rows_val": (
                    int(len(val_df_regime)) if val_df_regime is not None else 0
                ),
                "n_patterns_raw": int(len(short_raw)),
                "n_pass_event_filter": (
                    int(short_candidates["passes_event_filter"].sum())
                    if not short_candidates.empty
                    else 0
                ),
                "n_pass_overfit_filter": (
                    int(short_candidates["passes_overfit_filter"].sum())
                    if not short_candidates.empty
                    else 0
                ),
                "n_pass_regime_filter": (
                    int(short_candidates["passes_regime_filter"].sum())
                    if not short_candidates.empty
                    else 0
                ),
                "n_pass_aaa_score": (
                    int(short_candidates["passes_aaa_score"].sum())
                    if (
                        not short_candidates.empty
                        and "passes_aaa_score" in short_candidates
                    )
                    else 0
                ),
                "n_pass_aaa_filters": (
                    int(short_candidates["passes_aaa_filters"].sum())
                    if not short_candidates.empty
                    else 0
                ),
                "n_pass_validation": (
                    int(short_final["validation_passed"].sum())
                    if (
                        not args.skip_validation
                        and val_df_regime is not None
                        and not short_final.empty
                    )
                    else (int(len(short_final)) if not short_final.empty else 0)
                ),
            }
            if (
                diagnostics_enabled
                and not short_candidates.empty
                and "overfit_reason" in short_candidates
            ):
                rejected = short_candidates[short_candidates["is_overfit"]]
                short_summary["top_overfit_reasons"] = (
                    rejected["overfit_reason"].value_counts().head(10).to_dict()
                    if not rejected.empty
                    else {}
                )
            if (
                diagnostics_enabled
                and not short_validation_diag_df.empty
                and "validation_reason" in short_validation_diag_df
            ):
                short_summary["top_validation_reasons"] = (
                    short_validation_diag_df["validation_reason"]
                    .value_counts()
                    .head(10)
                    .to_dict()
                )

            segment_summaries.append(short_summary)

            if diagnostics_enabled:
                summary_file = diagnostics_dir / "summary.json"
                with open(summary_file, "w") as f:
                    json.dump(segment_summaries, f, indent=2, default=str)

            if not short_final.empty:
                short_file = output_dir / f"patterns_short_{horizon}m_{regime_name}.csv"
                short_final.to_csv(short_file, index=False)
                print(f"✅ Saved {len(short_final)} validated AAA SHORT patterns")
                all_patterns.append(short_final)

            # MEMORY-OPTIMIZED: Explicit cleanup before next iteration
            del df_regime, long_raw, long_candidates, long_final
            del short_raw, short_candidates, short_final
            if val_df_regime is not None:
                del val_df_regime
            gc.collect()
            log_memory(f"After {regime_name}/{horizon}m")

    if diagnostics_enabled:
        from collections import Counter

        totals = {
            "segments": len(segment_summaries),
            "raw_patterns": sum(s.get("n_patterns_raw", 0) for s in segment_summaries),
            "pass_event": sum(
                s.get("n_pass_event_filter", 0) for s in segment_summaries
            ),
            "pass_overfit": sum(
                s.get("n_pass_overfit_filter", 0) for s in segment_summaries
            ),
            "pass_regime": sum(
                s.get("n_pass_regime_filter", 0) for s in segment_summaries
            ),
            "pass_aaa_score": sum(
                s.get("n_pass_aaa_score", 0) for s in segment_summaries
            ),
            "pass_aaa_filters": sum(
                s.get("n_pass_aaa_filters", 0) for s in segment_summaries
            ),
            "pass_validation": sum(
                s.get("n_pass_validation", 0) for s in segment_summaries
            ),
        }

        overfit_reasons: Counter[str] = Counter()
        validation_reasons: Counter[str] = Counter()
        for seg in segment_summaries:
            for reason, count in (seg.get("top_overfit_reasons") or {}).items():
                overfit_reasons[str(reason)] += int(count)
            for reason, count in (seg.get("top_validation_reasons") or {}).items():
                validation_reasons[str(reason)] += int(count)

        report_lines = [
            "# AAA Discovery Diagnostics",
            "",
            f"- Date range: {args.start_date} to {args.end_date}",
            f"- Horizons: {', '.join(str(h) for h in horizons)}",
            f"- Current regime: {current_regime}",
            f"- Require event-based: {config['aaa_criteria']['require_event_based']}",
            f"- Overfit policy: {overfit_policy}",
            f"- Min AAA score: {min_aaa_score if min_aaa_score is not None else 'none'}",
            f"- Validation cost (bps): {validation_gate.cost_bps:.1f}",
            (
                "- Min net expectancy (bps): "
                f"{validation_gate.min_net_expectancy_bps}"
                if validation_gate.min_net_expectancy_bps is not None
                else "- Min net expectancy (bps): none"
            ),
            f"- Dedupe by symbol/day: {dedupe_by_symbol_day} ({dedupe_policy})",
            f"- Validation enabled: {not args.skip_validation}",
            "",
            "## Totals",
            f"- Segments: {totals['segments']}",
            f"- Raw patterns: {totals['raw_patterns']}",
            f"- Pass event filter: {totals['pass_event']}",
            f"- Pass overfit filter: {totals['pass_overfit']}",
            f"- Pass regime filter: {totals['pass_regime']}",
            f"- Pass AAA score: {totals['pass_aaa_score']}",
            f"- Pass AAA filters: {totals['pass_aaa_filters']}",
            f"- Pass validation: {totals['pass_validation']}",
            "",
            "## Top Overfit Rejections",
        ]

        for reason, count in overfit_reasons.most_common(20):
            report_lines.append(f"- {count}: {reason}")

        report_lines.append("")
        report_lines.append("## Top Validation Rejections")
        for reason, count in validation_reasons.most_common(20):
            report_lines.append(f"- {count}: {reason}")

        report_file = diagnostics_dir / "report.md"
        with open(report_file, "w") as f:
            f.write("\n".join(report_lines) + "\n")
        print(f"✅ Diagnostics report saved to {report_file}")

    # Consolidate and rank
    all_file = output_dir / "patterns_all_aaa.csv"
    if all_patterns:
        all_patterns_df = pd.concat(all_patterns, ignore_index=True)

        # Rank by AAA score or t-stat
        if args.use_aaa_scoring and "aaa_score" in all_patterns_df.columns:
            all_patterns_df = all_patterns_df.sort_values("aaa_score", ascending=False)
        else:
            all_patterns_df = all_patterns_df.sort_values("t_stat", ascending=False)

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
                top_patterns,
                "AAA Patterns",
                top_n=len(top_patterns),
            )

            llm_file = output_dir / "llm_analysis_aaa.md"
            with open(llm_file, "w") as f:
                f.write(llm_output)
            print(f"✅ LLM analysis saved to {llm_file}")
    else:
        pd.DataFrame().to_csv(all_file, index=False)
        print("\n⚠️ No patterns passed AAA filters/validation")
        print(f"✅ Wrote empty {all_file}")

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
