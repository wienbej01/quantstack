#!/usr/bin/env python3
"""
Phase A Complete Pipeline Runner
Executes all 6 steps for BAC single-ticker pilot test
"""

import argparse
import json
import logging
import math
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yaml

from extensions.intraday_ml.data_prep import create_training_dataset

# Import ML modules
from extensions.intraday_ml.dataset_manifest import DatasetManifestBuilder
from extensions.intraday_ml_models.cv_runner import TimeSeriesCVRunner
from extensions.intraday_ml_models.train_lgbm import LightGBMTrainer
from extensions.intraday_ml_policies.calibration import compute_policy_calibration_stats
from typing import Any
from extensions.intraday_ml.reporting import (
    build_run_summary,
    summarize_round_trip_trades,
    write_run_summary,
    write_trade_report,
)
from extensions.intraday_ml.sip_membership import get_phase_symbols_with_sip

_SYMBOL_TOKEN = re.compile(r"^[A-Z0-9.\-]{1,6}$")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _normalize_symbol_list(symbols: Sequence[str] | None) -> list[str]:
    """Upper-case and de-duplicate a sequence of symbols."""
    if not symbols:
        return []

    normalized: list[str] = []
    for symbol in symbols:
        token = str(symbol).strip()
        if not token:
            continue
        upper_token = token.upper()
        if not _SYMBOL_TOKEN.match(upper_token):
            continue
        normalized.append(upper_token)

    return sorted(dict.fromkeys(normalized))


def _log_symbol_summary(label: str, symbols: list[str], limit: int = 10) -> None:
    """Print a short summary for potentially large symbol lists."""
    if not symbols:
        print(f"   {label}: 0 symbols")
        return

    preview = ", ".join(symbols[:limit])
    suffix = "" if len(symbols) <= limit else f" ... (+{len(symbols) - limit} more)"
    print(f"   {label}: {len(symbols)} symbols [{preview}{suffix}]")


def _summarize_feature_coverage(
    training_df: pd.DataFrame,
    oos_df: pd.DataFrame,
    feature_columns: list[str],
    artifact_dir: Path,
) -> Path | None:
    """Compute simple feature coverage stats for train vs OOS datasets."""

    if training_df.empty or oos_df.empty:
        return None

    available_columns = [
        col for col in feature_columns if col in training_df.columns and col in oos_df.columns
    ]
    if not available_columns:
        return None

    coverage_records = []
    for col in available_columns:
        train_non_null = 1.0 - training_df[col].isna().mean()
        oos_non_null = 1.0 - oos_df[col].isna().mean()
        coverage_records.append(
            {
                "feature": col,
                "train_non_null": float(train_non_null),
                "oos_non_null": float(oos_non_null),
                "abs_gap": float(abs(train_non_null - oos_non_null)),
            }
        )

    coverage_df = pd.DataFrame(coverage_records).sort_values("oos_non_null")
    coverage_path = artifact_dir / "feature_coverage.csv"
    coverage_df.to_csv(coverage_path, index=False)

    low_coverage = coverage_df.nsmallest(5, "oos_non_null")
    if not low_coverage.empty:
        print("   Feature coverage (lowest OOS non-null ratios):")
        for _, row in low_coverage.iterrows():
            print(
                f"     - {row['feature']}: train={row['train_non_null']:.3f}, "
                f"oos={row['oos_non_null']:.3f}"
            )

    return coverage_path


def _load_policy_config(policy_section: dict[str, Any]) -> dict[str, Any]:
    """Merge the base policy config with any overrides from the master config."""

    base_path = Path(
        policy_section.get(
            "policy_base_config", "configs/extensions/intraday_ml/policy_config.json"
        )
    )
    if base_path.exists():
        with open(base_path) as f:
            base_config = json.load(f)
    else:
        base_config = {}

    overrides = {
        key: value
        for key, value in policy_section.items()
        if value is not None and key != "policy_base_config"
    }
    base_config.update(overrides)
    return base_config


def _print_trade_readiness_summary(
    training_df: pd.DataFrame,
    feature_columns: list[str],
    model: Any,
    policy_cfg: dict[str, Any],
) -> None:
    """Log directional precision stats aligned with target trades/day goals."""

    if training_df.empty or not feature_columns:
        return
    if "label" not in training_df or "ts" not in training_df:
        return

    ts_series = pd.to_datetime(training_df["ts"], errors="coerce")
    if ts_series.isna().all():
        return

    trading_days = ts_series.dt.normalize().nunique()
    if trading_days == 0:
        return

    feature_matrix = training_df[feature_columns].copy()
    feature_matrix = feature_matrix.fillna(0.0)
    feature_matrix = feature_matrix.reset_index(drop=True)
    labels = training_df["label"].reset_index(drop=True)

    probabilities = model.predict_proba(feature_matrix)
    classes = [int(cls) for cls in model.classes_]
    class_positions = {int(cls): idx for idx, cls in enumerate(classes)}

    target_min = int(policy_cfg.get("target_trades_min", 3) or 3)
    target_max = int(policy_cfg.get("target_trades_max", max(target_min, 3)))
    trade_targets = sorted({max(target_min, 1), max(target_max, 1)})

    print("   Trade readiness diagnostics (training set):")
    print(f"     - Trading days observed: {trading_days}")

    base_rates = {
        direction: float((labels == direction).mean()) if len(labels) else 0.0
        for direction in (-1, 1)
    }

    for direction in (-1, 1):
        idx = class_positions.get(direction)
        if idx is None or probabilities.shape[0] == 0:
            continue
        dir_probs = probabilities[:, idx]
        order = np.argsort(dir_probs)[::-1]
        base_rate = base_rates.get(direction, 0.0)
        direction_label = "long" if direction == 1 else "short"

        for target_trades in trade_targets:
            top_k = min(len(order), max(1, int(trading_days * target_trades)))
            selected_idx = order[:top_k]
            selected_labels = labels.iloc[selected_idx]
            hit_rate = float((selected_labels == direction).mean()) if top_k else 0.0
            lift = hit_rate / base_rate if base_rate > 0 else float("inf")
            min_prob = float(dir_probs[selected_idx[-1]]) if top_k else float("nan")
            approx_trades_per_day = top_k / trading_days if trading_days else 0.0

            print(
                "     - Direction %s | target %.1f/day | realized %.2f/day | hit_rate %.2f%% | "
                "lift %.2fx | min_prob %.3f"
                % (
                    direction_label,
                    target_trades,
                    approx_trades_per_day,
                    hit_rate * 100.0,
                    lift,
                    min_prob,
                )
            )


def _apply_label_guard(
    training_df: pd.DataFrame,
    deployment_symbols: list[str],
    guard_cfg: dict[str, Any] | None,
    artifact_dir: Path,
) -> tuple[list[str], Path | None, list[str]]:
    """Drop deployment symbols that lack sufficient directional labels."""
    if not guard_cfg or not guard_cfg.get("enabled", True):
        return deployment_symbols, None, []

    min_per_direction = int(guard_cfg.get("min_per_direction", 0))
    min_total_directional = int(guard_cfg.get("min_total_directional", 0))
    drop_from_deployment = bool(guard_cfg.get("drop_from_deployment", False))
    report_filename = guard_cfg.get("report_filename", "label_guard_report.json")

    if training_df.empty or not deployment_symbols:
        return deployment_symbols, None, []

    label_counts = (
        training_df.groupby(["symbol", "label"])
        .size()
        .unstack(fill_value=0)
        .rename_axis(index="symbol")
    )
    label_counts.index = label_counts.index.str.upper()
    label_counts = label_counts.reindex(columns=[-1, 0, 1], fill_value=0)

    report: dict[str, dict[str, int | str | list[str] | None]] = {}
    insufficient: list[str] = []

    for symbol in deployment_symbols:
        if symbol in label_counts.index:
            stats = label_counts.loc[symbol]
        else:
            stats = pd.Series({-1: 0, 0: 0, 1: 0})

        long_hits = int(stats.get(1, 0))
        short_hits = int(stats.get(-1, 0))
        total_dir = long_hits + short_hits
        reasons: list[str] = []
        if min_per_direction and long_hits < min_per_direction:
            reasons.append("insufficient_long")
        if min_per_direction and short_hits < min_per_direction:
            reasons.append("insufficient_short")
        if min_total_directional and total_dir < min_total_directional:
            reasons.append("insufficient_total")

        status = "kept"
        if reasons and drop_from_deployment:
            insufficient.append(symbol)
            status = "dropped"

        report[symbol] = {
            "long_labels": long_hits,
            "short_labels": short_hits,
            "total_directional": total_dir,
            "status": status,
            "reasons": reasons or None,
        }

    report_path = artifact_dir / report_filename
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    filtered = [sym for sym in deployment_symbols if sym not in insufficient]
    return filtered, report_path, insufficient


def _evaluate_manifest_guard(
    universe_report: dict[str, dict],
    guard_cfg: dict[str, Any],
) -> tuple[dict[str, list[str]], set[str], set[str]]:
    """Evaluate manifest coverage guard thresholds and return diagnostics."""

    tolerance = float(guard_cfg.get("coverage_tolerance", 0.0) or 0.0)
    tolerance = max(0.0, min(1.0, tolerance))

    min_total_days = int(guard_cfg.get("min_total_days", 0))
    min_train_days = int(guard_cfg.get("min_train_days", 0))
    min_oos_days = int(guard_cfg.get("min_oos_days", 0))
    drop_from_training = bool(guard_cfg.get("drop_from_training", True))
    drop_from_deployment = bool(guard_cfg.get("drop_from_deployment", True))

    total_days_values = [
        int(entry.get("coverage", {}).get("total_days", 0) or 0)
        for entry in universe_report.values()
    ]
    train_days_values = [
        int(entry.get("coverage", {}).get("train_days", 0) or 0)
        for entry in universe_report.values()
    ]
    oos_days_values = [
        int(entry.get("coverage", {}).get("oos_days", 0) or 0)
        for entry in universe_report.values()
    ]

    max_total_days = max(total_days_values, default=0)
    max_train_days = max(train_days_values, default=0)
    max_oos_days = max(oos_days_values, default=0)

    def _resolve_threshold(base: int, maximum: int) -> int:
        if not maximum:
            return base
        if tolerance > 0:
            tol_required = math.ceil(maximum * (1.0 - tolerance))
            return max(base, tol_required)
        return base

    total_threshold = _resolve_threshold(min_total_days, max_total_days)
    train_threshold = _resolve_threshold(min_train_days, max_train_days)
    oos_threshold = _resolve_threshold(min_oos_days, max_oos_days)

    manifest_guard_reasons: dict[str, list[str]] = {}
    training_drops: set[str] = set()
    deployment_drops: set[str] = set()

    for symbol, entry in universe_report.items():
        sym_key = str(symbol).upper()
        coverage = entry.get("coverage", {})
        total_days = int(coverage.get("total_days", 0) or 0)
        train_days = int(coverage.get("train_days", 0) or 0)
        oos_days = int(coverage.get("oos_days", 0) or 0)

        reasons: list[str] = []
        if total_threshold and total_days < total_threshold:
            reasons.append("insufficient_total_days")
        if train_threshold and train_days < train_threshold:
            reasons.append("insufficient_train_days")
        if oos_threshold and oos_days < oos_threshold:
            reasons.append("insufficient_oos_days")

        if not reasons:
            continue

        manifest_guard_reasons[sym_key] = reasons

        training_reasons = {"insufficient_total_days", "insufficient_train_days"}
        deployment_reasons = {"insufficient_total_days", "insufficient_oos_days"}
        if drop_from_training and any(reason in training_reasons for reason in reasons):
            training_drops.add(sym_key)
        if drop_from_deployment and any(reason in deployment_reasons for reason in reasons):
            deployment_drops.add(sym_key)

    return manifest_guard_reasons, training_drops, deployment_drops


def _build_manifest_report(
    *,
    context: dict[str, Any],
    val_symbols: list[str],
    candidate_symbols: list[str],
    label_guard_dropped_set: set[str],
    label_guard_reasons: dict[str, list[str]],
) -> dict[str, Any]:
    """Construct manifest report combining diagnostics, guard status, and phases."""

    guard_drop_list = context.get("manifest_guard_drop_list", [])
    guard_drop_set = set(guard_drop_list)
    phase_sets = context.get("phase_symbols_requested", {})
    universe_report = context.get("universe_report", {}) or {}
    guard_reasons = context.get("manifest_guard_reasons", {})

    summary = {
        "candidate_symbols": context.get("candidate_symbol_count", 0),
        "post_sip_train": context.get("post_sip_train_count", 0),
        "post_sip_oos": context.get("post_sip_oos_count", 0),
        "manifest_symbols": context.get("manifest_symbols_count", 0),
        "post_manifest_train": context.get("post_manifest_train_count", 0),
        "post_manifest_oos": context.get("post_manifest_oos_count", 0),
        "dropped_by_manifest_guard": guard_drop_list,
        "dropped_by_label_guard": sorted(label_guard_dropped_set),
    }

    all_symbols: set[str] = set()
    all_symbols.update(str(sym).upper() for sym in candidate_symbols)
    all_symbols.update(context.get("manifest_symbol_set", set()))
    all_symbols.update(sym.upper() for sym in val_symbols)
    all_symbols.update(
        sym.upper()
        for sym in context.get("training_symbols_after_guard", [])
    )
    all_symbols.update(
        sym.upper()
        for sym in context.get("deployment_symbols_pre_label_guard", [])
    )
    all_symbols.update(guard_reasons.keys())
    all_symbols.update(universe_report.keys())
    all_symbols.update(label_guard_dropped_set)
    for phase_symbols in phase_sets.values():
        all_symbols.update(phase_symbols)

    symbols_report: dict[str, dict[str, Any]] = {}
    for symbol in sorted(all_symbols):
        diag = universe_report.get(symbol, {}) or {}
        coverage = diag.get("coverage") or {}
        symbols_report[symbol] = {
            "phases_requested": [
                phase
                for phase in ("train", "val", "oos")
                if symbol in phase_sets.get(phase, set())
            ],
            "coverage": {
                "total_days": int(coverage.get("total_days", 0) or 0),
                "train_days": int(coverage.get("train_days", 0) or 0),
                "val_days": int(coverage.get("val_days", 0) or 0),
                "oos_days": int(coverage.get("oos_days", 0) or 0),
            },
            "avg_daily_dollar_volume": _to_float(diag.get("avg_daily_dollar_volume")),
            "latest_close": _to_float(diag.get("latest_close")),
            "relative_volume": _to_float(diag.get("relative_volume")),
            "selected_in_universe": bool(diag.get("selected")),
            "screener_reasons": list(diag.get("reasons") or []),
            "manifest_guard_reasons": list(guard_reasons.get(symbol, [])),
            "dropped_by_manifest_guard": symbol in guard_drop_set,
            "dropped_by_label_guard": symbol in label_guard_dropped_set,
            "label_guard_reasons": list(label_guard_reasons.get(symbol, [])),
        }

    return {"summary": summary, "symbols": symbols_report}


def _to_float(value: Any) -> float | None:
    """Safely convert values to floats for reporting."""

    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def main():
    """Run complete Phase A pipeline."""
    parser = argparse.ArgumentParser(description="Run complete Phase A pipeline.")
    parser.add_argument("--config", type=str, help="Path to master YAML config file.")
    parser.add_argument("--symbol", type=str, help="Override symbol to run for.")
    args = parser.parse_args()

    print("🚀 Intraday ML Pipeline")
    print("=" * 60)

    # Load master config if provided
    master_config = {}
    if args.config:
        with open(args.config) as f:
            master_config = yaml.safe_load(f)

    # Setup paths
    artifact_dir = Path(master_config.get("artifacts", "artefacts/extensions/intraday_ml/phaseA"))
    artifact_dir.mkdir(parents=True, exist_ok=True)
    print(f"   Artifacts will be saved to: {artifact_dir}")

    try:
        # Load all configurations
        print("📋 Loading configurations...")
        configs = {}
        if args.config:
            print(f"   Master config: {args.config}")
            for name, path in master_config.get("includes", {}).items():
                with open(path) as f:
                    configs[name] = yaml.safe_load(f)
                print(f"✅ {name}: {path}")
        else:
            # Fallback to default hardcoded configs if --config is not provided
            print("   Using default hardcoded configs.")
            config_files = {
                "universe": "configs/extensions/intraday_ml/universe_single.yaml",
                "splits": "configs/extensions/intraday_ml/splits_pilot.yaml",
                "cuts": "configs/extensions/intraday_ml/cuts_10m.yaml",
                "features": "configs/extensions/intraday_ml/features_10m.yaml",
                "targets": "configs/extensions/intraday_ml/targets_loose.yaml",
                "model": "configs/extensions/intraday_ml/model_lgbm_loose.yaml",
                "cv": "configs/extensions/intraday_ml/cv/phaseA.yaml",
            }
            for name, path in config_files.items():
                with open(path) as f:
                    configs[name] = yaml.safe_load(f)
                print(f"✅ {name}: {path}")

        # Symbol override
        if args.symbol:
            print(f"   Symbol override: {args.symbol}")
            configs["universe"]["symbols"] = [args.symbol]

        policy_section = master_config.get("policy", {})
        label_guard_cfg = master_config.get("label_guard", {})
        manifest_guard_cfg = master_config.get("manifest_guard", {})
        policy_config = _load_policy_config(policy_section)
        session_timezone = policy_config.get("session_timezone", "America/New_York")
        policy_calibration_cfg = dict(policy_config.get("calibration", {}))
        calibration_stats_path: Path | None = None

        # Data loader config
        data_loader_config = master_config.get("data", {})
        data_loader_config.setdefault("root", "/home/jacobw/gcs-mount/gold")
        data_loader_config.setdefault("validate", True)
        data_loader_config.setdefault("sort", True)

        # SIP filter config
        sip_config = master_config.get("sip_filter", {"enabled": False})
        sip_enabled = sip_config.get("enabled", False)

        # Step 1: Build Dataset Manifest
        print("\n🔧 Step 1: Building dataset manifest...")

        # Ensure dates are strings
        for split in configs["splits"]:
            if "start" in configs["splits"][split]:
                configs["splits"][split]["start"] = str(configs["splits"][split]["start"])
            if "end" in configs["splits"][split]:
                configs["splits"][split]["end"] = str(configs["splits"][split]["end"])

        print(f"   Splits config after conversion: {configs['splits']}")

        candidate_symbols = _normalize_symbol_list(configs["universe"].get("symbols", ["BAC"]))
        if not candidate_symbols:
            raise RuntimeError("Universe configuration produced zero candidate symbols.")
        candidate_symbol_count = len(candidate_symbols)

        training_symbols_cfg = master_config.get("training_symbols")
        deployment_symbols_cfg = master_config.get("deployment_symbols")

        training_symbols_base = (
            _normalize_symbol_list(training_symbols_cfg)
            if training_symbols_cfg
            else candidate_symbols.copy()
        )
        deployment_symbols_base = (
            _normalize_symbol_list(deployment_symbols_cfg)
            if deployment_symbols_cfg
            else candidate_symbols.copy()
        )

        if args.symbol:
            override_list = _normalize_symbol_list([args.symbol])
            candidate_symbols = override_list
            training_symbols_base = override_list
            deployment_symbols_base = override_list

        phase_defaults = {
            "train": training_symbols_base,
            "val": candidate_symbols,
            "oos": deployment_symbols_base,
        }

        sip_log = lambda message: print(f"   {message}")
        resolved_phase_symbols: dict[str, list[str]] = {}

        if sip_enabled:
            for phase_name, base_list in phase_defaults.items():
                if phase_name not in configs["splits"]:
                    continue
                if not base_list:
                    continue
                resolved_phase_symbols[phase_name] = get_phase_symbols_with_sip(
                    splits_config=configs["splits"],
                    sip_config=sip_config,
                    candidate_symbols=base_list,
                    phase=phase_name,
                    log_fn=sip_log,
                )
        else:
            for phase_name, base_list in phase_defaults.items():
                if base_list:
                    resolved_phase_symbols[phase_name] = base_list

        phase_symbols_post_sip = {
            phase: resolved_phase_symbols.get(phase, [])
            for phase in ("train", "val", "oos")
        }
        training_symbols_post_sip = phase_symbols_post_sip["train"].copy()
        deployment_symbols_post_sip = phase_symbols_post_sip["oos"].copy()
        training_symbols = training_symbols_post_sip.copy()
        deployment_symbols = deployment_symbols_post_sip.copy()
        val_symbols = phase_symbols_post_sip["val"]
        phase_symbols_post_sip_sets = {
            phase: {symbol.upper() for symbol in symbols}
            for phase, symbols in phase_symbols_post_sip.items()
        }

        if not training_symbols:
            raise RuntimeError(
                "No training symbols available after applying SIP filtering. "
                "Ensure SIP membership exists for the training window."
            )
        if "oos" in configs["splits"] and not deployment_symbols:
            raise RuntimeError(
                "No deployment symbols available after applying SIP filtering. "
                "Ensure SIP membership exists for the OOS window."
            )

        _log_symbol_summary(
            "Training symbols (post-SIP)" if sip_enabled else "Training symbols",
            training_symbols,
        )
        if "oos" in configs["splits"]:
            _log_symbol_summary(
                "Deployment symbols (post-SIP)" if sip_enabled else "Deployment symbols",
                deployment_symbols,
            )

        manifest_sources = training_symbols + deployment_symbols + val_symbols
        manifest_candidate_symbols = _normalize_symbol_list(manifest_sources) or candidate_symbols

        builder = DatasetManifestBuilder(
            gold_root="/home/jacobw/gcs-mount/gold",
            universe_config=configs["universe"],
            cuts_config=configs["cuts"],
            splits_config=configs["splits"],
        )
        manifest_path = artifact_dir / "manifest.json"
        manifest = builder.build_manifest(
            candidate_symbols=manifest_candidate_symbols,
            output_path=manifest_path,
        )
        print(f"✅ Manifest created: {manifest_path}")
        _log_symbol_summary("Manifest symbols", manifest.symbols, limit=20)
        print(f"   Total days: {manifest.total_days}")

        available_symbols = sorted({str(symbol).upper() for symbol in manifest.symbols})

        missing_training = sorted(set(training_symbols) - set(available_symbols))
        missing_deployment = sorted(set(deployment_symbols) - set(available_symbols))
        if missing_training:
            print(
                "   Warning: Dropping training symbols absent from manifest: "
                + ", ".join(missing_training)
            )
            training_symbols = [s for s in training_symbols if s in available_symbols]
        if missing_deployment:
            print(
                "   Warning: Dropping deployment symbols absent from manifest: "
                + ", ".join(missing_deployment)
            )
            deployment_symbols = [s for s in deployment_symbols if s in available_symbols]

        _log_symbol_summary("Final training symbols", training_symbols)
        if "oos" in configs["splits"]:
            _log_symbol_summary("Final deployment symbols", deployment_symbols)

        manifest_guard_enabled = bool(manifest_guard_cfg.get("enabled", False))
        manifest_report_filename = manifest_guard_cfg.get(
            "report_filename", "manifest_report.json"
        )
        universe_report = builder.get_last_universe_report() or {}
        manifest_guard_reasons = {}
        training_guard_drops: set[str] = set()
        deployment_guard_drops: set[str] = set()
        if manifest_guard_enabled and universe_report:
            (
                manifest_guard_reasons,
                training_guard_drops,
                deployment_guard_drops,
            ) = _evaluate_manifest_guard(universe_report, manifest_guard_cfg)

        if training_guard_drops:
            training_symbols = [sym for sym in training_symbols if sym not in training_guard_drops]
        if deployment_guard_drops:
            deployment_symbols = [
                sym for sym in deployment_symbols if sym not in deployment_guard_drops
            ]

        manifest_guard_drop_list = sorted({*training_guard_drops, *deployment_guard_drops})
        manifest_symbol_set = {str(symbol).upper() for symbol in manifest.symbols}

        manifest_report_context = {
            "candidate_symbol_count": candidate_symbol_count,
            "post_sip_train_count": len(training_symbols_post_sip),
            "post_sip_oos_count": len(deployment_symbols_post_sip),
            "manifest_symbols_count": len(manifest.symbols),
            "post_manifest_train_count": len(training_symbols),
            "post_manifest_oos_count": len(deployment_symbols),
            "universe_report": universe_report,
            "manifest_guard_reasons": manifest_guard_reasons,
            "manifest_guard_drop_list": manifest_guard_drop_list,
            "manifest_guard_enabled": manifest_guard_enabled,
            "phase_symbols_requested": phase_symbols_post_sip_sets,
            "manifest_symbol_set": manifest_symbol_set,
            "training_symbols_after_guard": training_symbols.copy(),
            "deployment_symbols_pre_label_guard": deployment_symbols.copy(),
            "manifest_report_filename": manifest_report_filename,
        }

        # Step 2: Data Preparation (Features + Labels using sliding window)
        print("\n🔧 Step 2: Data preparation with aligned features and labels...")

        # Generate date list from splits config for training data
        from datetime import datetime, timedelta

        train_dates = configs["splits"]["train"]
        start_date = datetime.strptime(train_dates["start"], "%Y-%m-%d")
        end_date = datetime.strptime(train_dates["end"], "%Y-%m-%d")

        # We need additional future data for label computation
        # Add buffer period after training end for labeling horizons
        label_buffer_days = 7  # Add 7 days for label horizons
        extended_end_date = end_date + timedelta(days=label_buffer_days)

        # Create training dataset using the new sliding window approach
        training_data_path = artifact_dir / "training_data.parquet"

        train_loader_config = dict(data_loader_config)
        train_loader_config["dataset_kind"] = "train"

        training_data = create_training_dataset(
            symbols=training_symbols,
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=extended_end_date.strftime("%Y-%m-%d"),
            features_config=configs["features"],
            targets_config=configs["targets"],
            data_loader_config=train_loader_config,
            include_ohlcv=True,
        )

        # Check if we got any data
        if training_data.empty:
            print("❌ No training data generated. Check data availability and configurations.")
            return 1

        # Filter to training period only (exclude label buffer period)
        if "ts" in training_data.columns:
            training_data = training_data[training_data["ts"] <= pd.Timestamp(end_date)]
        else:
            print(f"❌ Training data missing 'ts' column. Columns: {list(training_data.columns)}")
            return 1

        # Save the aligned training data
        training_data.to_parquet(training_data_path)
        print(f"✅ Aligned training data created: {training_data_path}")
        print(f"   Shape: {training_data.shape}")
        print(
            f"   Features: {len([col for col in training_data.columns if col.startswith('f__')])}"
        )
        print(f"   Label distribution: {training_data['label'].value_counts().to_dict()}")

        deployment_symbols_filtered = deployment_symbols
        label_guard_report_path: Path | None = None
        dropped_symbols: list[str] = []
        if label_guard_cfg:
            deployment_symbols_filtered, label_guard_report_path, dropped_symbols = (
                _apply_label_guard(training_data, deployment_symbols, label_guard_cfg, artifact_dir)
            )
            if label_guard_report_path:
                print(f"✅ Label guard report saved: {label_guard_report_path}")
            if dropped_symbols:
                print(
                    "⚠️ Dropped deployment symbols due to insufficient directional labels: "
                    + ", ".join(dropped_symbols)
                )
            if not deployment_symbols_filtered:
                raise RuntimeError(
                    "All deployment symbols failed label guard checks. "
                    "Relax guard thresholds or extend the training window."
                )
            deployment_symbols = deployment_symbols_filtered
            resolved_phase_symbols["oos"] = deployment_symbols_filtered

        label_guard_dropped_set = {sym.upper() for sym in dropped_symbols}
        label_guard_reasons: dict[str, list[str]] = {}
        if label_guard_report_path and label_guard_report_path.exists():
            with open(label_guard_report_path) as f:
                raw_report = json.load(f)
            for sym, entry in raw_report.items():
                reasons = entry.get("reasons") or []
                label_guard_reasons[str(sym).upper()] = reasons

        manifest_report_path = artifact_dir / manifest_report_context["manifest_report_filename"]
        manifest_report = _build_manifest_report(
            context=manifest_report_context,
            val_symbols=val_symbols,
            candidate_symbols=candidate_symbols,
            label_guard_dropped_set=label_guard_dropped_set,
            label_guard_reasons=label_guard_reasons,
        )
        with open(manifest_report_path, "w") as f:
            json.dump(manifest_report, f, indent=2, sort_keys=True)

        summary = manifest_report["summary"]
        logger.info(
            "Manifest summary: %d candidate, %d post-SIP train, %d manifest, "
            "%d train post-guard, %d deploy post-guard",
            summary["candidate_symbols"],
            summary["post_sip_train"],
            summary["manifest_symbols"],
            summary["post_manifest_train"],
            summary["post_manifest_oos"],
        )
        if summary["dropped_by_manifest_guard"]:
            logger.warning(
                "Symbols dropped by manifest_guard: %s",
                ", ".join(summary["dropped_by_manifest_guard"]),
            )

        # Step 3: Train LightGBM Model
        print("\n🔧 Step 3: Training LightGBM model...")
        trainer = LightGBMTrainer(configs["model"])
        model_dir = artifact_dir / "model_lgbm"
        model_dir.mkdir(parents=True, exist_ok=True)

        # Separate features and labels from the aligned training data
        feature_columns = [col for col in training_data.columns if col.startswith("f__")]
        features_df = training_data[feature_columns]
        labels_series = training_data["label"]

        # For now, use all data for training (no validation split)
        # Generate simple hashes for reproducibility
        features_hash = hash(str(features_df.shape))
        targets_hash = hash(str(labels_series.value_counts().to_dict()))

        result = trainer.train_model(
            features=features_df,
            labels=labels_series,
            features_hash=str(features_hash),
            targets_hash=str(targets_hash),
        )

        if policy_calibration_cfg.get("enabled", True):
            calibration_stats = compute_policy_calibration_stats(
                model=result.model,
                data=training_data,
                feature_columns=feature_columns,
                calibration_config=policy_calibration_cfg,
                risk_config=policy_section.get("risk"),
            )
            stats_filename = policy_calibration_cfg.get("stats_filename", "policy_calibration.json")
            calibration_stats_path = artifact_dir / stats_filename
            with open(calibration_stats_path, "w") as f:
                json.dump(calibration_stats, f, indent=2)
            print(f"✅ Policy calibration stats saved: {calibration_stats_path}")

        # Save model
        import joblib

        joblib.dump(result.model, model_dir / "model.pkl")
        print(f"✅ Model trained: {model_dir}")

        # Print a concise metric summary to catch regressions early
        try:
            m = result.metrics or {}
            ll = m.get("log_loss")
            bll = m.get("baseline_log_loss")
            active_ll = m.get("active_log_loss", ll)
            baseline_delta = m.get("baseline_delta", 0.0)
            baseline_tol = m.get("baseline_tolerance", 1e-3)
            bri = m.get("brier_improvement")
            trade_density = m.get("trade_density")
            worse_than_baseline = (m.get("sanity", {}) or {}).get("worse_than_baseline")
            if ll is not None and bll is not None:
                msg1 = (
                    f"   Metrics: log_loss={ll:.6f} | baseline_log_loss={bll:.6f}"
                    f" | active_log_loss={active_ll:.6f}"
                )
                msg2 = (
                    f"   brier_improvement={bri:.6f} | trade_density={trade_density:.4f}"
                    f" | baseline_delta={baseline_delta:.6f} | baseline_tol={baseline_tol:.6f}"
                )
                print(msg1)
                print(msg2)
                if bool(worse_than_baseline):
                    logger.warning(
                        "PhaseA log-loss worse than frequency baseline: active=%.6f "
                        "baseline=%.6f (Δ=%.6f, tol=%.6f)",
                        active_ll,
                        bll,
                        baseline_delta,
                        baseline_tol,
                    )
        except Exception:
            # Do not fail the pipeline on metrics printing
            pass

        try:
            _print_trade_readiness_summary(training_data, feature_columns, result.model, policy_section)
        except Exception as exc:  # pragma: no cover - diagnostics only
            print(f"⚠️ Trade readiness diagnostics failed: {exc}")

        # Step 4: Cross-Validation
        if master_config.get("run_cv", True):
            print("\n🔧 Step 4: Running cross-validation...")
            cv_runner = TimeSeriesCVRunner(configs["cv"])
            cv_report_path = artifact_dir / "cv_report.json"

            # Load training data for CV
            training_data_for_cv = pd.read_parquet(training_data_path)
            training_data_for_cv = training_data_for_cv.set_index(["symbol", "ts"])
            features_for_cv = training_data_for_cv[
                [col for col in training_data_for_cv.columns if col.startswith("f__")]
            ]
            labels_for_cv = training_data_for_cv["label"]
            context_columns_for_cv = [
                column
                for column in ["open", "high", "low", "close", "volume"]
                if column in training_data_for_cv.columns
            ]
            context_data_for_cv = (
                training_data_for_cv[context_columns_for_cv] if context_columns_for_cv else None
            )

            cv_result = cv_runner.run_cv(
                features=features_for_cv,
                labels=labels_for_cv,
                model_trainer=trainer,
                model_config=configs["model"],
                context_data=context_data_for_cv,
            )
            cv_runner.save_cv_results(cv_result, cv_report_path)
            print(f"✅ Cross-validation completed: {cv_report_path}")
        else:
            print("\nSkipping cross-validation.")

        # Step 5: Generate and persist OOS feature set
        print("\n🔧 Step 5: Generating OOS feature set...")
        feature_coverage_path: Path | None = None
        oos_dates = configs["splits"]["oos"]
        oos_start_date = datetime.strptime(oos_dates["start"], "%Y-%m-%d")
        oos_end_date = datetime.strptime(oos_dates["end"], "%Y-%m-%d")

        oos_loader_config = dict(data_loader_config)
        oos_loader_config["dataset_kind"] = "oos"

        oos_data = create_training_dataset(
            symbols=deployment_symbols,
            start_date=oos_start_date.strftime("%Y-%m-%d"),
            end_date=oos_end_date.strftime("%Y-%m-%d"),
            features_config=configs["features"],
            targets_config=configs["targets"],
            data_loader_config=oos_loader_config,
            include_ohlcv=True,
        )

        if oos_data.empty:
            print("❌ No OOS data generated. Check data availability and configurations.")
            return 1

        # Normalize timestamps to UTC for downstream policy/backtest steps
        oos_data["ts"] = pd.to_datetime(oos_data["ts"], errors="raise")
        if oos_data["ts"].dt.tz is None:
            oos_data["ts"] = oos_data["ts"].dt.tz_localize(session_timezone)
        oos_data["ts"] = oos_data["ts"].dt.tz_convert("UTC")

        oos_feature_path = artifact_dir / "oos_features.parquet"
        oos_data.to_parquet(oos_feature_path)
        print(f"✅ OOS features created: {oos_feature_path}")
        print(f"   Shape: {oos_data.shape}")

        # Step 6: Generate OOS predictions
        print("\n🔧 Step 6: Generating OOS predictions...")
        import joblib

        model = joblib.load(model_dir / "model.pkl")

        oos_feature_columns = [col for col in oos_data.columns if col.startswith("f__")]
        oos_features = oos_data[oos_feature_columns]

        feature_coverage_path = _summarize_feature_coverage(
            training_data, oos_data, oos_feature_columns, artifact_dir
        )

        oos_predictions = model.predict_proba(oos_features)
        oos_predictions_df = pd.DataFrame(
            oos_predictions,
            columns=[f"prob_c{i}" for i in range(oos_predictions.shape[1])],
        )
        # Derive robust probability columns using actual class mapping
        try:
            classes = [int(cls) for cls in model.classes_]
            class_positions = {int(cls): idx for idx, cls in enumerate(classes)}
            # Provide label-keyed columns for clarity
            for cls, idx in class_positions.items():
                oos_predictions_df[f"prob_{cls}"] = oos_predictions[:, idx]
            # Standardized names expected by policy layer
            if -1 in class_positions:
                oos_predictions_df["prob_short"] = oos_predictions[:, class_positions[-1]]
            if 0 in class_positions:
                oos_predictions_df["prob_neutral"] = oos_predictions[:, class_positions[0]]
            if 1 in class_positions:
                oos_predictions_df["prob_long"] = oos_predictions[:, class_positions[1]]
        except Exception:
            # If anything goes wrong, continue with generic c0/c1/c2 columns only
            pass
        oos_predictions_df["ts"] = oos_data["ts"]
        oos_predictions_df["symbol"] = oos_data["symbol"]

        oos_predictions_path = artifact_dir / "oos_predictions.parquet"
        oos_predictions_df.to_parquet(oos_predictions_path)
        print(f"✅ OOS predictions created: {oos_predictions_path}")
        print(f"   Shape: {oos_predictions_df.shape}")

        # Print OOS data columns for debugging
        print(f"   OOS data columns: {list(oos_data.columns)}")

        # Step 7: Generate Orders from OOS Predictions
        print("\n🔧 Step 7: Generating orders from OOS predictions...")
        from extensions.intraday_ml_policies.intraday_ml_decision_policy import (
            IntradayMLDecisionPolicy,
        )

        calibration_cfg_for_policy = dict(policy_config.get("calibration", {}))
        stats_filename = calibration_cfg_for_policy.pop("stats_filename", None)
        if calibration_stats_path:
            calibration_cfg_for_policy["stats_path"] = str(calibration_stats_path)
        elif stats_filename:
            calibration_cfg_for_policy["stats_path"] = str(artifact_dir / stats_filename)
        if calibration_cfg_for_policy and calibration_cfg_for_policy.get("enabled", True):
            policy_config["calibration"] = calibration_cfg_for_policy
        else:
            policy_config.pop("calibration", None)

        policy_config = {k: v for k, v in policy_config.items() if v is not None}

        policy = IntradayMLDecisionPolicy(policy_config)

        # Rename prediction columns for policy only if standardized names are missing
        if not {"prob_long", "prob_short"}.issubset(set(oos_predictions_df.columns)):
            oos_predictions_df = oos_predictions_df.rename(
                columns={
                    "prob_c0": "prob_short",
                    "prob_c1": "prob_neutral",
                    "prob_c2": "prob_long",
                }
            )

        required_feature_columns = policy.get_required_feature_columns()
        merged_signals = oos_predictions_df
        if required_feature_columns:
            feature_columns = ["ts", "symbol"] + sorted(required_feature_columns)
            available_columns = [col for col in feature_columns if col in oos_data.columns]
            missing_cols = sorted(set(required_feature_columns) - set(oos_data.columns))
            if missing_cols:
                print(
                    "⚠️ Warning: Missing required feature columns for policy checks: "
                    + ", ".join(missing_cols)
                )
            if len(available_columns) >= 2:
                feature_frame = (
                    oos_data[available_columns]
                    .drop_duplicates(subset=["ts", "symbol"])
                    .reset_index(drop=True)
                )
                merged_signals = merged_signals.merge(
                    feature_frame,
                    on=["ts", "symbol"],
                    how="left",
                    validate="one_to_one",
                )

        # Process signals
        orders_df, rejections_df = policy.process_signals(merged_signals)

        # Save orders and rejections
        orders_path = artifact_dir / "oos_orders.parquet"
        rejections_path = artifact_dir / "oos_rejections.parquet"
        orders_df.to_parquet(orders_path)
        rejections_df.to_parquet(rejections_path)

        print(f"✅ Orders generated: {orders_path}")
        print(f"   Total orders: {len(orders_df)}")
        print(f"✅ Rejections logged: {rejections_path}")
        print(f"   Total rejections: {len(rejections_df)}")

        if not orders_df.empty:
            order_reason_counts = orders_df["reason"].value_counts().sort_values(ascending=False)
            print("   Order reasons:")
            for reason, count in order_reason_counts.items():
                print(f"     - {reason}: {count}")

        if not rejections_df.empty:
            rejection_counts = rejections_df["reason"].value_counts().sort_values(ascending=False)
            print("   Rejection reasons:")
            for reason, count in rejection_counts.items():
                print(f"     - {reason}: {count}")
            rejection_summary_path = artifact_dir / "rejection_summary.csv"
            rejection_counts.to_csv(rejection_summary_path, header=["count"])
            print(f"   Rejection summary saved: {rejection_summary_path}")
        else:
            print("   Rejection reasons: none")

        # Save policy config for reproducibility
        policy_config_path = artifact_dir / "policy_config.json"
        with open(policy_config_path, "w") as f:
            json.dump(policy_config, f, indent=2)
        print(f"✅ Policy config saved: {policy_config_path}")

        # Step 8: Run Backtest
        print("\n🔧 Step 8: Running backtest...")
        from extensions.intraday_ml.backtest import intraday_ml_run_backtest

        backtest_config = master_config.get("backtest", {})
        backtest_config["artifacts_path"] = str(artifact_dir)
        intraday_constraints = backtest_config.setdefault("intraday_constraints", {})
        intraday_constraints.setdefault("session_timezone", session_timezone)
        backtest_artifacts = intraday_ml_run_backtest(
            bars=oos_data, orders=orders_df, cfg=backtest_config
        )

        print("✅ Backtest completed.")
        metrics_dict = backtest_artifacts.get("metrics", {})
        if metrics_dict:
            print("   Metrics:")
            for k, v in metrics_dict.items():
                print(f"     - {k}: {v}")

        trade_orders_df = backtest_artifacts.get("policy_orders", backtest_artifacts.get("orders"))
        trade_summary_df = summarize_round_trip_trades(
            backtest_artifacts.get("fills"), trade_orders_df
        )
        if not trade_summary_df.empty:
            trade_summary_path = artifact_dir / "trade_summary.parquet"
            trade_summary_df.to_parquet(trade_summary_path, index=False)
            trade_report_path = artifact_dir / "trade_summary.md"
            write_trade_report(
                trade_summary_df,
                trade_report_path,
                max_rows=50,
                target_range=(
                    policy_config.get("target_trades_min", 3),
                    policy_config.get("target_trades_max", 5),
                ),
            )
            print(f"   Trade summary saved: {trade_summary_path} ({len(trade_summary_df)} trades)")
        else:
            print("   Trade summary: no completed trades")

        run_summary = build_run_summary(
            metrics=metrics_dict,
            orders_df=orders_df,
            rejections_df=rejections_df,
            policy_config=policy_config,
            artifacts_dir=artifact_dir,
            feature_coverage_path=feature_coverage_path,
            timestamp=datetime.now(timezone.utc),
        )
        write_run_summary(run_summary, artifact_dir / "pilot_report.json")

        # Summary
        print("\n🎉 Phase A Pipeline Completed Successfully!")
        print("=" * 60)
        print("📊 Generated Artifacts:")
        for artifact in artifact_dir.glob("*"):
            size_mb = artifact.stat().st_size / (1024 * 1024) if artifact.is_file() else 0
            print(f"   - {artifact.name} ({size_mb:.1f} MB)")

        print("\n📋 Phase A Summary:")
        print(f"   - Manifest symbols: {', '.join(available_symbols)}")
        print(f"   - Training symbols: {', '.join(training_symbols)}")
        print(f"   - Deployment symbols: {', '.join(deployment_symbols)}")
        if label_guard_report_path:
            print(f"   - Label guard report: {label_guard_report_path}")
        print(f"   - Train: {train_dates['start']} to {train_dates['end']}")
        test_dates = configs["splits"].get("test", {})
        oos_split = configs["splits"].get("oos", {})

        def _format_range(split_cfg: dict[str, str] | None) -> str:
            if not split_cfg:
                return "n/a"
            start = split_cfg.get("start", "n/a")
            end = split_cfg.get("end", "n/a")
            return f"{start} to {end}"

        print(f"   - Validation: {_format_range(test_dates)}")
        print(f"   - OOS: {_format_range(oos_split)}")
        print("   - Data: Aligned features+labels via sliding window")
        print("   - Model: LightGBM tri-class")

        status_path = artifact_dir / "phaseA_status.json"
        phase_status = {
            "phase": "A",
            "manifest_symbols": available_symbols,
            "training_symbols": training_symbols,
            "deployment_symbols": deployment_symbols,
            "train_window": train_dates,
            "test_window": test_dates,
            "oos_window": oos_split,
            "label_guard_report": str(label_guard_report_path) if label_guard_report_path else None,
        }
        with open(status_path, "w") as f:
            json.dump(phase_status, f, indent=2)
        print(f"   - Status file: {status_path}")

        cv_summary = "skipped"
        if master_config.get("run_cv", True):
            if "cv_result" in locals() and cv_result:
                executed_folds = len(cv_result.splits)
                method = cv_runner.validation_method.replace("_", " ")
                cv_summary = f"{executed_folds} fold(s) {method}"
            else:
                cv_summary = "configured but not executed"
        print(f"   - CV: {cv_summary}")

        total_trades = backtest_artifacts.get("metrics", {}).get("total_trades")
        if total_trades is not None:
            print(f"   - OOS trades: {total_trades}")

        return 0

    except Exception as e:
        print(f"\n❌ Pipeline failed: {e}")
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
