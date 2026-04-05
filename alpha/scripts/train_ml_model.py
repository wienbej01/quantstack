#!/usr/bin/env python
"""End-to-end ML model training script.

Usage:
    python scripts/train_ml_model.py [--horizon 180] [--grid-search] [--save-path models/xgb_best.pkl]
"""

import argparse
from dataclasses import asdict
import json
import logging
import os
import resource
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

from src.data.ml_compact_cache import CompactCacheConfig, save_compact_cache
from src.data.ml_dataset import MLDatasetBuilder, optimize_memory
from src.data.ml_label_artifacts import LabelArtifactConfig
from src.data.ml_labels import (
    WalkForwardFold,
    generate_labels,
    temporal_split,
    walk_forward_folds,
)
from src.features.ml_features import (
    add_side_aware_context_features,
    compute_ml_features,
    get_ml_feature_columns,
    get_side_aware_context_columns,
)
from src.models.xgb_trainer import (
    fit_probability_calibrator,
    grid_search,
    predict_calibrated_proba,
    permutation_test,
    QualityGate,
    quality_gate_failures,
    resolve_training_folds,
    save_model,
    select_confidence_threshold,
    train_walk_forward,
)
from src.models.two_stage_trainer import train_two_stage_walk_forward
from src.models.two_stage_trainer import train_two_stage_xgb_walk_forward

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def _configure_runtime(cpu_limit: int, memory_limit_gb: float | None) -> None:
    """Apply conservative runtime limits before heavy imports begin work."""
    thread_cap = max(1, cpu_limit)
    for var in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[var] = str(thread_cap)

    if memory_limit_gb is None:
        return

    limit_bytes = int(memory_limit_gb * (1024**3))
    try:
        current_soft, current_hard = resource.getrlimit(resource.RLIMIT_AS)
        hard_limit = (
            current_hard
            if current_hard not in (-1, resource.RLIM_INFINITY)
            else limit_bytes
        )
        resource.setrlimit(
            resource.RLIMIT_AS, (min(limit_bytes, hard_limit), hard_limit)
        )
        logger.info("Applied RAM limit: %.2f GB", memory_limit_gb)
    except (OSError, ValueError) as exc:
        logger.warning("Could not apply RAM limit %.2f GB: %s", memory_limit_gb, exc)


def _prepare_chunk(
    chunk: pd.DataFrame,
    horizon: int,
    label_threshold_method: str,
    label_fixed_bps: float,
    max_rows_per_symbol_day: int | None,
) -> pd.DataFrame:
    """Compute ML-ready features and labels for one symbol-day."""
    ordered = chunk.sort_values("ts_utc").reset_index(drop=True)
    if max_rows_per_symbol_day is not None and len(ordered) > max_rows_per_symbol_day:
        step = max(1, len(ordered) // max_rows_per_symbol_day)
        ordered = (
            ordered.iloc[::step].head(max_rows_per_symbol_day).reset_index(drop=True)
        )

    featured = compute_ml_features(ordered)
    labeled = generate_labels(
        featured,
        horizons_seconds=[horizon],
        threshold_method=label_threshold_method,
        fixed_bps=label_fixed_bps,
    )
    label_col = f"label_{horizon}s"
    labeled = labeled[labeled[label_col].notna()].reset_index(drop=True)
    return optimize_memory(labeled)


def _evenly_spaced_take(df: pd.DataFrame, n_rows: int) -> pd.DataFrame:
    """Take approximately evenly spaced rows from a frame."""
    if n_rows >= len(df):
        return df.reset_index(drop=True)
    positions = np.linspace(0, len(df) - 1, num=n_rows, dtype=int)
    return df.iloc[positions].reset_index(drop=True)


def _build_training_dataframe(
    builder: MLDatasetBuilder,
    horizon: int,
    label_threshold_method: str,
    label_fixed_bps: float,
    max_rows_per_symbol_day: int | None,
    max_total_rows: int | None,
    spill_dir: Path | None,
    balanced_by_date: bool,
    max_rows_per_date: int | None,
) -> pd.DataFrame:
    """Build the labeled training dataframe with bounded peak memory."""
    frames: list[pd.DataFrame] = []
    spilled_paths: list[Path] = []
    total_rows = 0
    rows_by_date: dict[str, int] = {}

    if spill_dir is not None:
        spill_dir.mkdir(parents=True, exist_ok=True)

    for idx, chunk in enumerate(
        builder.iter_symbol_days(balanced_by_date=balanced_by_date), start=1
    ):
        prepared = _prepare_chunk(
            chunk,
            horizon=horizon,
            label_threshold_method=label_threshold_method,
            label_fixed_bps=label_fixed_bps,
            max_rows_per_symbol_day=max_rows_per_symbol_day,
        )
        if prepared.empty:
            continue

        date = str(prepared["date"].iloc[0])
        if max_rows_per_date is not None:
            date_rows = rows_by_date.get(date, 0)
            if date_rows >= max_rows_per_date:
                logger.info(
                    "Skipping chunk %s: %s date budget exhausted at %s rows",
                    idx,
                    date,
                    date_rows,
                )
                continue
            remaining_date_rows = max_rows_per_date - date_rows
            if len(prepared) > remaining_date_rows:
                prepared = prepared.head(remaining_date_rows).reset_index(drop=True)

        if max_total_rows is not None and total_rows >= max_total_rows:
            logger.info(
                "Reached max-total-rows=%s; stopping dataset build", max_total_rows
            )
            break

        if max_total_rows is not None and total_rows + len(prepared) > max_total_rows:
            remaining = max_total_rows - total_rows
            prepared = prepared.head(remaining).reset_index(drop=True)

        if prepared.empty:
            continue

        total_rows += len(prepared)
        rows_by_date[date] = rows_by_date.get(date, 0) + len(prepared)
        logger.info(
            "Prepared chunk %s: %s/%s rows=%s date_total=%s global_total=%s",
            idx,
            prepared["symbol"].iloc[0],
            date,
            len(prepared),
            rows_by_date[date],
            total_rows,
        )

        if spill_dir is not None:
            out_path = spill_dir / f"chunk_{idx:05d}.parquet"
            prepared.to_parquet(out_path, index=False)
            spilled_paths.append(out_path)
        else:
            frames.append(prepared)

    if spill_dir is not None:
        if not spilled_paths:
            return pd.DataFrame()
        logger.info(
            "Reloading %s spilled chunks from %s", len(spilled_paths), spill_dir
        )
        return optimize_memory(
            pd.concat(
                (pd.read_parquet(path) for path in spilled_paths), ignore_index=True
            )
        )

    if not frames:
        return pd.DataFrame()
    return optimize_memory(pd.concat(frames, ignore_index=True))


def _load_manifest(manifest_path: Path) -> dict:
    """Load a JSON manifest from disk."""
    return json.loads(manifest_path.read_text())


def _desired_label_config(args: argparse.Namespace) -> LabelArtifactConfig:
    """Build the desired label configuration for cache/artifact generation."""
    return LabelArtifactConfig(
        horizons_seconds=(args.horizon,),
        threshold_method=args.label_threshold_method,
        fixed_bps=args.label_fixed_bps,
    )


def _compact_cache_matches_config(
    manifest: dict, label_config: LabelArtifactConfig
) -> bool:
    """Check whether the on-disk compact cache uses the requested label settings."""
    actual = manifest.get("config", {}).get("label_config", {})
    if not actual:
        return False

    actual_horizons = set(int(value) for value in actual.get("horizons_seconds", []))
    expected_horizons = set(label_config.horizons_seconds)
    if not expected_horizons.issubset(actual_horizons):
        return False

    return (
        actual.get("threshold_method") == label_config.threshold_method
        and float(actual.get("fixed_bps", 0.0)) == float(label_config.fixed_bps)
        and actual.get("label_mode") == label_config.label_mode
        and float(actual.get("stop_bps", 0.0)) == float(label_config.stop_bps)
        and float(actual.get("take_profit_bps", 0.0))
        == float(label_config.take_profit_bps)
        and actual.get("direction") == label_config.direction
        and actual.get("tie_break_policy") == label_config.tie_break_policy
    )


def _build_training_dataframe_from_compact_cache(
    cache_dir: Path,
    max_total_rows: int | None,
    max_rows_per_date: int | None,
    sampling_strategy: str,
) -> pd.DataFrame:
    """Load compact cache rows under explicit date and global quotas."""
    manifest_path = cache_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Compact cache manifest missing: {manifest_path}")

    manifest = _load_manifest(manifest_path)
    entries = manifest.get("entries", [])
    if not entries:
        return pd.DataFrame()

    per_date_entries: dict[str, list[dict]] = {}
    for entry in entries:
        per_date_entries.setdefault(str(entry["date"]), []).append(entry)

    rows_by_date: dict[str, int] = {}
    total_rows = 0
    frames: list[pd.DataFrame] = []

    def _repair_source_type(
        frame: pd.DataFrame, fallback_source: str | None
    ) -> pd.Series:
        inferred = None
        if "source_is_features" in frame.columns:
            inferred = pd.Series("unknown", index=frame.index, dtype="object")
            inferred = inferred.where(
                pd.to_numeric(frame["source_is_features"], errors="coerce") <= 0.0,
                "features",
            )
            if "source_is_raw" in frame.columns:
                inferred = inferred.where(
                    pd.to_numeric(frame["source_is_raw"], errors="coerce") <= 0.0,
                    "raw",
                )
            if "source_is_unknown" in frame.columns:
                inferred = inferred.where(
                    pd.to_numeric(frame["source_is_unknown"], errors="coerce") <= 0.0,
                    "unknown",
                )

        if "source_type" not in frame.columns:
            frame["source_type"] = (
                inferred if inferred is not None else (fallback_source or "unknown")
            )
        else:
            if inferred is not None:
                missing = frame["source_type"].isna() | frame["source_type"].astype(
                    str
                ).isin(["nan", "None", "unknown"])
                frame.loc[missing, "source_type"] = inferred.loc[missing]
            frame["source_type"] = frame["source_type"].fillna(
                fallback_source or "unknown"
            )

        frame["source_type"] = (
            frame["source_type"]
            .astype(str)
            .replace(
                {
                    "nan": fallback_source or "unknown",
                    "None": fallback_source or "unknown",
                }
            )
        )
        return frame["source_type"]

    def _primary_source_type(entry: dict, frame: pd.DataFrame) -> pd.Series:
        source = None
        source_counts = entry.get("source_counts", {})
        if isinstance(source_counts, dict):
            ranked = sorted(
                (
                    (key, int(value))
                    for key, value in source_counts.items()
                    if key not in {"nan", "None", None}
                ),
                key=lambda item: item[1],
                reverse=True,
            )
            if ranked:
                source = ranked[0][0]
        return _repair_source_type(frame, source or "unknown")

    if sampling_strategy == "balanced_by_date":
        active_dates = sorted(per_date_entries)
        date_positions = {date: 0 for date in active_dates}
        pending = True
        while pending:
            pending = False
            for date in active_dates:
                date_entries = per_date_entries[date]
                idx = date_positions[date]
                if idx >= len(date_entries):
                    continue
                pending = True
                entry = date_entries[idx]
                date_positions[date] += 1

                if max_total_rows is not None and total_rows >= max_total_rows:
                    return (
                        optimize_memory(pd.concat(frames, ignore_index=True))
                        if frames
                        else pd.DataFrame()
                    )

                current_date_rows = rows_by_date.get(date, 0)
                if (
                    max_rows_per_date is not None
                    and current_date_rows >= max_rows_per_date
                ):
                    continue

                frame = pd.read_parquet(entry["path"])
                _primary_source_type(entry, frame)
                remaining_date = (
                    max_rows_per_date - current_date_rows
                    if max_rows_per_date is not None
                    else len(frame)
                )
                remaining_global = (
                    max_total_rows - total_rows
                    if max_total_rows is not None
                    else len(frame)
                )
                keep_rows = min(len(frame), remaining_date, remaining_global)
                if keep_rows <= 0:
                    continue
                frame = _evenly_spaced_take(frame.sort_values("ts_utc"), keep_rows)
                frames.append(frame)
                rows_by_date[date] = current_date_rows + len(frame)
                total_rows += len(frame)
    else:
        for entry in sorted(
            entries, key=lambda item: (str(item["date"]), str(item["symbol"]))
        ):
            if max_total_rows is not None and total_rows >= max_total_rows:
                break
            date = str(entry["date"])
            current_date_rows = rows_by_date.get(date, 0)
            if max_rows_per_date is not None and current_date_rows >= max_rows_per_date:
                continue
            frame = pd.read_parquet(entry["path"])
            _primary_source_type(entry, frame)
            remaining_date = (
                max_rows_per_date - current_date_rows
                if max_rows_per_date is not None
                else len(frame)
            )
            remaining_global = (
                max_total_rows - total_rows
                if max_total_rows is not None
                else len(frame)
            )
            keep_rows = min(len(frame), remaining_date, remaining_global)
            if keep_rows <= 0:
                continue
            frame = _evenly_spaced_take(frame.sort_values("ts_utc"), keep_rows)
            frames.append(frame)
            rows_by_date[date] = current_date_rows + len(frame)
            total_rows += len(frame)

    if not frames:
        return pd.DataFrame()

    return optimize_memory(pd.concat(frames, ignore_index=True))


def _fallback_folds(split_info) -> list[WalkForwardFold]:
    """Build fallback folds for small capped runs."""
    if split_info.train_dates and split_info.val_dates:
        return [WalkForwardFold(0, split_info.train_dates, split_info.val_dates)]

    non_test_dates = split_info.train_dates + split_info.val_dates
    if len(non_test_dates) >= 2:
        return [WalkForwardFold(0, non_test_dates[:-1], [non_test_dates[-1]])]

    return []


def _build_quality_gate(args: argparse.Namespace) -> QualityGate:
    """Convert CLI thresholds into a gate config."""
    return QualityGate(
        min_val_accuracy=args.min_val_accuracy,
        max_train_val_gap=args.max_train_val_gap,
        min_test_accuracy=args.min_test_accuracy,
        require_walk_forward=args.require_walk_forward,
        min_folds=args.min_folds,
    )


def _load_or_build_compact_cache(args: argparse.Namespace) -> pd.DataFrame:
    """Load compact cache rows or build them if missing."""
    cache_dir = Path(args.compact_cache_dir)
    manifest_path = cache_dir / "manifest.json"
    desired_label_config = _desired_label_config(args)
    needs_rebuild = not manifest_path.exists()

    if manifest_path.exists():
        manifest = _load_manifest(manifest_path)
        if not _compact_cache_matches_config(manifest, desired_label_config):
            logger.info(
                "Compact cache config mismatch in %s; rebuilding with label config %s",
                cache_dir,
                desired_label_config,
            )
            needs_rebuild = True

    if needs_rebuild:
        if args.train_source == "snapshot_fallback":
            return pd.DataFrame()
        logger.info("Building compact cache in %s", cache_dir)
        save_compact_cache(
            output_dir=cache_dir,
            label_config=desired_label_config,
            compact_config=CompactCacheConfig(
                bucket_seconds=args.compact_bucket_seconds
            ),
            sample_rows_per_symbol_day=args.compact_rows_per_symbol_day,
        )

    if not manifest_path.exists():
        return pd.DataFrame()

    df = _build_training_dataframe_from_compact_cache(
        cache_dir=cache_dir,
        max_total_rows=args.max_total_rows,
        max_rows_per_date=args.max_rows_per_date,
        sampling_strategy=args.sampling_strategy,
    )
    if not df.empty:
        logger.info(
            "Loaded compact-cache training dataset from %s with %s rows",
            cache_dir,
            len(df),
        )
    return df


def _coverage_summary(df: pd.DataFrame) -> dict[str, object]:
    """Summarize date, symbol, and session coverage for a training dataframe."""
    rows_by_date = (
        df.groupby("date").size().sort_index().astype(int).to_dict()
        if "date" in df.columns and not df.empty
        else {}
    )
    rows_by_symbol = (
        df.groupby("symbol").size().sort_values(ascending=False).astype(int).to_dict()
        if "symbol" in df.columns and not df.empty
        else {}
    )
    rows_by_session = (
        df.groupby("session_bucket").size().sort_index().astype(int).to_dict()
        if "session_bucket" in df.columns and not df.empty
        else {}
    )
    rows_by_source = (
        df.groupby("source_type").size().sort_index().astype(int).to_dict()
        if "source_type" in df.columns and not df.empty
        else {}
    )
    return {
        "rows": int(len(df)),
        "dates": (
            int(df["date"].nunique()) if "date" in df.columns and not df.empty else 0
        ),
        "symbols": (
            int(df["symbol"].nunique())
            if "symbol" in df.columns and not df.empty
            else 0
        ),
        "rows_by_date": {str(key): int(value) for key, value in rows_by_date.items()},
        "rows_by_symbol": {
            str(key): int(value) for key, value in rows_by_symbol.items()
        },
        "rows_by_session": {
            str(key): int(value) for key, value in rows_by_session.items()
        },
        "rows_by_source": {
            str(key): int(value) for key, value in rows_by_source.items()
        },
    }


def _label_summary(
    df: pd.DataFrame, label_col: str, model_family: str
) -> dict[str, object]:
    """Summarize label coverage for the selected training target."""
    if label_col not in df.columns or df.empty:
        return {}

    valid = df[df[label_col].notna()].copy()
    if valid.empty:
        return {"rows_with_labels": 0}

    label_counts = valid[label_col].astype(int).value_counts().sort_index().to_dict()
    summary: dict[str, object] = {
        "rows_with_labels": int(len(valid)),
        "rows_by_label": {str(key): int(value) for key, value in label_counts.items()},
    }
    if model_family in {"two_stage_logistic", "two_stage_xgb"}:
        eligible = (valid[label_col].astype(int) != 1).astype(int)
        direction = valid.loc[eligible == 1, label_col].astype(int).map({0: 0, 2: 1})
        summary["stage1_rows_by_label"] = {
            "0": int((eligible == 0).sum()),
            "1": int((eligible == 1).sum()),
        }
        summary["stage2_rows_by_label"] = {
            str(key): int(value)
            for key, value in direction.value_counts().sort_index().to_dict().items()
        }
    return summary


def _apply_training_balance_weights(
    df: pd.DataFrame,
    label_col: str | None = None,
) -> np.ndarray:
    """Build conservative balancing weights across source, date, session, and symbol."""
    if df.empty:
        return np.array([], dtype=np.float64)

    weights = np.ones(len(df), dtype=np.float64)
    for column in ("source_type", "date", "session_bucket", "symbol"):
        if column not in df.columns:
            continue
        counts = df[column].value_counts(dropna=False)
        column_counts = df[column].map(counts).astype(float).to_numpy()
        weights *= 1.0 / np.sqrt(np.maximum(column_counts, 1.0))

    if label_col is not None and label_col in df.columns:
        valid = df[label_col].notna()
        if bool(valid.any()):
            counts = df.loc[valid, label_col].astype(int).value_counts(dropna=False)
            label_weights = np.ones(len(df), dtype=np.float64)
            label_weights[valid.to_numpy()] = 1.0 / np.sqrt(
                np.maximum(
                    df.loc[valid, label_col]
                    .astype(int)
                    .map(counts)
                    .to_numpy(dtype=float),
                    1.0,
                )
            )
            weights *= label_weights

    weights = np.where(np.isfinite(weights), weights, 0.0)
    mean_weight = float(weights.mean()) if len(weights) else 1.0
    if mean_weight <= 0:
        return np.ones(len(df), dtype=np.float64)
    return weights / mean_weight


def _align_training_rows_to_live_scoring(
    df: pd.DataFrame,
    bucket_seconds: int,
) -> pd.DataFrame:
    """Approximate live scoring by keeping the last snapshot per symbol/date/bar bucket."""
    if df.empty:
        return df
    if bucket_seconds <= 0:
        raise ValueError(f"bucket_seconds must be positive, got {bucket_seconds}")

    aligned = df.copy()
    aligned["ts_utc"] = pd.to_datetime(aligned["ts_utc"], utc=True)
    aligned["_live_bucket"] = aligned["ts_utc"].dt.floor(f"{bucket_seconds}s")
    aligned = (
        aligned.sort_values(["symbol", "date", "_live_bucket", "ts_utc"])
        .groupby(["symbol", "date", "_live_bucket"], as_index=False)
        .tail(1)
        .drop(columns=["_live_bucket"])
        .reset_index(drop=True)
    )
    if "source_type" in aligned.columns:
        aligned["source_type"] = (
            aligned["source_type"]
            .fillna("unknown")
            .astype(str)
            .replace({"nan": "unknown", "None": "unknown"})
        )
    return optimize_memory(aligned)


def _augment_training_context_features(
    df: pd.DataFrame,
    enable_side_aware_context_features: bool,
) -> pd.DataFrame:
    """Derive lightweight context-interaction features that must match live scoring."""
    if not enable_side_aware_context_features or df.empty:
        return df
    augmented = add_side_aware_context_features(df)
    return optimize_memory(augmented)


def _derive_executable_edge_labels(
    df: pd.DataFrame,
    horizon: int,
    edge_bps: float,
    spread_weight: float,
    open_penalty_bps: float,
    raw_penalty_bps: float,
) -> tuple[pd.DataFrame, str]:
    """Create a cost-aware 3-class label for two-stage models.

    Stage-1 positive means absolute forward move clears an executable edge floor.
    Stage-2 direction is then the sign of that move.
    """
    ret_col = f"ret_fwd_{horizon}s"
    if ret_col not in df.columns:
        raise RuntimeError(
            f"Required return column missing for executable-edge labels: {ret_col}"
        )

    label_col = f"label_exec_edge_{horizon}s"
    derived = df.copy()
    returns = pd.to_numeric(derived[ret_col], errors="coerce")
    spread = pd.to_numeric(
        (
            derived["spread"]
            if "spread" in derived.columns
            else pd.Series(np.nan, index=derived.index)
        ),
        errors="coerce",
    )
    mid = pd.to_numeric(
        (
            derived["mid"]
            if "mid" in derived.columns
            else pd.Series(np.nan, index=derived.index)
        ),
        errors="coerce",
    )
    spread_bps = (
        (spread / mid.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        * 10000.0
    ).clip(lower=0.0)
    session_bucket = pd.to_numeric(
        derived.get("session_bucket"), errors="coerce"
    ).fillna(1.0)
    source_type = (
        derived.get("source_type", pd.Series("unknown", index=derived.index))
        .fillna("unknown")
        .astype(str)
    )
    dynamic_floor_bps = (
        float(edge_bps)
        + spread_bps * float(spread_weight)
        + np.where(session_bucket == 0.0, float(open_penalty_bps), 0.0)
        + np.where(source_type == "raw", float(raw_penalty_bps), 0.0)
    )
    threshold = dynamic_floor_bps / 10000.0
    labels = np.full(len(derived), np.nan, dtype=np.float32)
    labels[returns <= -threshold] = 0
    labels[(returns > -threshold) & (returns < threshold)] = 1
    labels[returns >= threshold] = 2
    labels[returns.isna().to_numpy()] = np.nan
    derived[label_col] = labels
    derived[f"edge_floor_bps_{horizon}s"] = dynamic_floor_bps.astype(np.float32)
    return derived, label_col


def _validation_rows(
    df: pd.DataFrame,
    split_info,
    feature_cols: list[str],
    label_col: str,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract validation features/labels for calibration and threshold selection."""
    val_df = df.loc[
        df["date"].isin(split_info.val_dates) & df[label_col].notna()
    ].copy()
    if val_df.empty:
        raise RuntimeError(
            "Validation slice is empty; cannot fit calibrator or select threshold"
        )
    X_val = np.nan_to_num(val_df[feature_cols].to_numpy(dtype=np.float32, copy=True))
    y_val = val_df[label_col].to_numpy(dtype=int, copy=False)
    return X_val, y_val


def _write_training_reports(
    report_dir: Path,
    dataset_summary: dict[str, object],
    label_summary: dict[str, object],
    split_info,
    fold_strategy: str,
    result,
    test_accuracy: float | None,
    best_params: dict | None = None,
    grid_results: list[dict] | None = None,
    calibration_summary: dict | None = None,
    feature_summary: dict | None = None,
) -> None:
    """Persist machine-readable and markdown training reports."""
    report_dir.mkdir(parents=True, exist_ok=True)
    fold_rows = [
        {
            "fold_idx": fold.fold_idx,
            "train_acc": fold.train_acc,
            "val_acc": fold.val_acc,
        }
        for fold in result.fold_results
    ]
    payload = {
        "dataset_summary": dataset_summary,
        "label_summary": label_summary,
        "split_info": {
            "train_dates": split_info.train_dates,
            "val_dates": split_info.val_dates,
            "test_dates": split_info.test_dates,
            "train_symbols": split_info.train_symbols,
            "holdout_symbols": split_info.holdout_symbols,
        },
        "fold_strategy": fold_strategy,
        "model_family": result.model_family,
        "fold_metrics": fold_rows,
        "mean_val_accuracy": result.mean_val_acc,
        "train_val_gap": result.train_val_gap,
        "test_accuracy": test_accuracy,
        "best_params": best_params,
        "calibration_summary": calibration_summary,
        "feature_summary": feature_summary,
    }
    (report_dir / "training_metrics.json").write_text(json.dumps(payload, indent=2))
    if grid_results is not None:
        (report_dir / "grid_results.json").write_text(
            json.dumps(grid_results, indent=2)
        )

    top_features = sorted(
        result.fold_results[result.best_fold_idx].feature_importance.items(),
        key=lambda item: item[1],
        reverse=True,
    )[:20]
    lines = [
        "# ML Training Report",
        "",
        f"- rows: {dataset_summary['rows']}",
        f"- dates: {dataset_summary['dates']}",
        f"- symbols: {dataset_summary['symbols']}",
        f"- model family: {result.model_family}",
        f"- fold strategy: {fold_strategy}",
        f"- mean val accuracy: {result.mean_val_acc:.3f}",
        f"- train/val gap: {result.train_val_gap:.3f}",
        (
            f"- test accuracy: {test_accuracy:.3f}"
            if test_accuracy is not None
            else "- test accuracy: unavailable"
        ),
        (
            f"- best params: {best_params}"
            if best_params
            else "- best params: default constrained baseline"
        ),
        (
            f"- recommended threshold: {result.recommended_threshold:.2f}"
            if result.recommended_threshold is not None
            else "- recommended threshold: unavailable"
        ),
        "",
        "## Coverage",
        "",
        f"- rows by source: {dataset_summary.get('rows_by_source', {})}",
        f"- rows by session: {dataset_summary.get('rows_by_session', {})}",
        f"- label summary: {label_summary}",
        "",
        "## Top Features",
        "",
    ]
    lines.extend(f"- {name}: {importance:.4f}" for name, importance in top_features)
    if calibration_summary:
        lines.extend(
            [
                "",
                "## Calibration",
                "",
                f"- method: {calibration_summary['method']}",
                f"- validation rows: {calibration_summary['validation_rows']}",
                (
                    f"- min directional precision: {calibration_summary['min_directional_precision']:.2f}"
                    if "min_directional_precision" in calibration_summary
                    else None
                ),
                (
                    f"- min trigger count: {calibration_summary['min_trigger_count']}"
                    if "min_trigger_count" in calibration_summary
                    else None
                ),
                (
                    f"- recommended threshold: {calibration_summary['recommended_threshold']:.2f}"
                    if calibration_summary["recommended_threshold"] is not None
                    else "- recommended threshold: unavailable"
                ),
                "",
                "### Threshold Sweep",
                "",
            ]
        )
        lines = [line for line in lines if line is not None]
        for row in calibration_summary["threshold_selection"]:
            lines.append(
                f"- `{row['threshold']:.2f}`: trigger_count={row['trigger_count']}, "
                f"activation={row['activation_rate']:.2%}, "
                f"directional_precision={row['directional_precision']:.3f}, "
                f"tradeoff={row['tradeoff_score']:.4f}"
            )
    if feature_summary:
        lines.extend(
            [
                "",
                "## Feature Sets",
                "",
                f"- stage1 feature count: {feature_summary['stage1_count']}",
                f"- stage2 feature count: {feature_summary['stage2_count']}",
                f"- stage1 sample: {feature_summary['stage1_sample']}",
                f"- stage2 sample: {feature_summary['stage2_sample']}",
            ]
        )
    (report_dir / "training_report.md").write_text("\n".join(lines) + "\n")


def _select_training_universe(df: pd.DataFrame, split_info) -> pd.DataFrame:
    """Restrict model fitting to the non-holdout symbol universe."""
    if not split_info.train_symbols:
        return df.copy()
    return df[df["symbol"].isin(split_info.train_symbols)].copy()


def _evaluate_test_accuracy(
    df: pd.DataFrame,
    split_info,
    feature_cols: list[str],
    label_col: str,
    model,
    calibrator=None,
) -> float | None:
    """Evaluate on held-out test rows, preferring symbol holdouts when available."""
    test_mask = df["date"].isin(split_info.test_dates)
    if split_info.holdout_symbols:
        holdout_mask = df["symbol"].isin(split_info.holdout_symbols)
        if bool((test_mask & holdout_mask).sum()):
            test_mask = test_mask & holdout_mask

    eval_df = df.loc[test_mask & df[label_col].notna()].copy()
    if eval_df.empty:
        logger.warning("Test accuracy unavailable: no held-out rows with valid labels")
        return None

    X_test = np.nan_to_num(eval_df[feature_cols].to_numpy(dtype=np.float32, copy=True))
    y_test = eval_df[label_col].to_numpy(dtype=int, copy=False)
    if calibrator is None:
        test_pred = model.predict(X_test)
    else:
        calibrated_probs = predict_calibrated_proba(model, X_test, calibrator)
        test_pred = np.asarray(np.argmax(calibrated_probs, axis=1), dtype=int)
    from sklearn.metrics import accuracy_score

    return float(accuracy_score(y_test, test_pred))


def main():
    parser = argparse.ArgumentParser(description="Train ML model on L2 data")
    parser.add_argument(
        "--horizon", type=int, default=180, help="Forward return horizon in seconds"
    )
    parser.add_argument(
        "--model-family",
        choices=["xgb_multiclass", "two_stage_logistic", "two_stage_xgb"],
        default="xgb_multiclass",
        help="Model family to train",
    )
    parser.add_argument(
        "--stage1-edge-bps",
        type=float,
        default=12.0,
        help="Minimum forward edge in bps required for a stage-1 trade label",
    )
    parser.add_argument(
        "--stage1-spread-weight",
        type=float,
        default=0.50,
        help="Additional stage-1 edge floor multiplier applied to current spread in bps",
    )
    parser.add_argument(
        "--stage1-open-penalty-bps",
        type=float,
        default=2.0,
        help="Extra stage-1 edge floor applied during the opening session bucket",
    )
    parser.add_argument(
        "--stage1-raw-penalty-bps",
        type=float,
        default=2.0,
        help="Extra stage-1 edge floor applied to raw-source rows",
    )
    parser.add_argument(
        "--label-threshold-method",
        choices=["fixed", "quantile"],
        default="fixed",
        help="How to convert forward returns into classes",
    )
    parser.add_argument(
        "--label-fixed-bps",
        type=float,
        default=10.0,
        help="Absolute basis-point threshold when using fixed labels",
    )
    parser.add_argument(
        "--grid-search", action="store_true", help="Run hyperparameter grid search"
    )
    parser.add_argument(
        "--save-path", default="models/xgb_best.pkl", help="Model save path"
    )
    parser.add_argument(
        "--min-snapshots", type=int, default=100, help="Min snapshots per symbol-day"
    )
    parser.add_argument(
        "--cpu-limit", type=int, default=4, help="Max CPU threads for training/runtime"
    )
    parser.add_argument(
        "--memory-limit-gb", type=float, default=12.0, help="Best-effort RAM limit"
    )
    parser.add_argument(
        "--max-rows-per-symbol-day",
        type=int,
        default=10000,
        help="Cap rows per symbol-day after deterministic downsampling",
    )
    parser.add_argument(
        "--max-total-rows", type=int, default=800000, help="Optional global row cap"
    )
    parser.add_argument(
        "--max-rows-per-date",
        type=int,
        default=22000,
        help="Cap total rows per date to preserve temporal breadth on laptop runs",
    )
    parser.add_argument(
        "--sampling-strategy",
        choices=["balanced_by_date", "sequential"],
        default="balanced_by_date",
        help="How to traverse symbol-days when building the dataset",
    )
    parser.add_argument(
        "--spill-dir",
        default="output/ml_training_spill_laptop",
        help="Directory for on-disk intermediate parquet chunks",
    )
    parser.add_argument(
        "--train-source",
        choices=["compact_cache", "auto", "snapshot_fallback"],
        default="compact_cache",
        help="Preferred training source",
    )
    parser.add_argument(
        "--use-compact-cache",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--compact-cache-dir",
        default="output/ml_compact_cache",
        help="Directory for compact cached feature parquet",
    )
    parser.add_argument(
        "--compact-bucket-seconds",
        type=int,
        default=1,
        help="Bucket size when building compact cache",
    )
    parser.add_argument(
        "--compact-rows-per-symbol-day",
        type=int,
        default=4000,
        help="Event-aware sample size per symbol-day when building compact cache",
    )
    parser.add_argument(
        "--xgb-n-jobs", type=int, default=None, help="Explicit XGBoost thread count"
    )
    parser.add_argument(
        "--min-val-accuracy",
        type=float,
        default=0.38,
        help="Minimum mean validation accuracy",
    )
    parser.add_argument(
        "--max-train-val-gap",
        type=float,
        default=0.15,
        help="Maximum train/validation accuracy gap",
    )
    parser.add_argument(
        "--min-test-accuracy", type=float, default=0.34, help="Minimum test accuracy"
    )
    parser.add_argument(
        "--min-folds", type=int, default=2, help="Minimum completed validation folds"
    )
    parser.add_argument(
        "--min-dates", type=int, default=15, help="Minimum distinct dates required"
    )
    parser.add_argument(
        "--min-session-buckets",
        type=int,
        default=4,
        help="Minimum represented session buckets required before training",
    )
    parser.add_argument(
        "--report-dir",
        default="output/ml_training_reports",
        help="Directory for training coverage and fold reports",
    )
    parser.add_argument(
        "--threshold-grid",
        default="0.35,0.40,0.45,0.50,0.55",
        help="Comma-separated validation thresholds for calibration-driven selection",
    )
    parser.add_argument(
        "--threshold-min-directional-precision",
        type=float,
        default=0.45,
        help="Minimum validation directional precision required when choosing an entry threshold",
    )
    parser.add_argument(
        "--threshold-min-trigger-count",
        type=int,
        default=20,
        help="Minimum validation trigger count required when choosing an entry threshold",
    )
    parser.add_argument(
        "--alignment-bucket-seconds",
        type=int,
        default=60,
        help="Live-alignment bucket size used to keep one training row per bar interval",
    )
    parser.add_argument(
        "--live-aligned-rows",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep only the last snapshot per symbol/date/bar bucket to match live bar scoring",
    )
    parser.add_argument(
        "--side-aware-context-features",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Add symmetric side-aware regime/context interaction features for the next model iteration",
    )
    parser.add_argument(
        "--side-aware-context-stage",
        choices=["both", "stage2_only"],
        default="both",
        help="Choose whether side-aware context features feed both stages or only the direction stage",
    )
    parser.add_argument(
        "--fit-calibrator",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Fit validation-only probability calibration and threshold selection metadata",
    )
    parser.add_argument(
        "--allow-temporal-holdout",
        action="store_true",
        help="Allow saving a model trained without walk-forward validation",
    )
    args = parser.parse_args()
    if args.use_compact_cache:
        args.train_source = "compact_cache"
    args.require_walk_forward = not args.allow_temporal_holdout
    _configure_runtime(cpu_limit=args.cpu_limit, memory_limit_gb=args.memory_limit_gb)

    # Step 1: Build or load training dataset
    df = _load_or_build_compact_cache(args)
    if df.empty and args.train_source != "compact_cache":
        logger.info("Building unified ML dataset incrementally...")
        builder = MLDatasetBuilder(min_snapshots=args.min_snapshots)
        spill_dir = Path(args.spill_dir) if args.spill_dir else None
        df = _build_training_dataframe(
            builder=builder,
            horizon=args.horizon,
            label_threshold_method=args.label_threshold_method,
            label_fixed_bps=args.label_fixed_bps,
            max_rows_per_symbol_day=args.max_rows_per_symbol_day,
            max_total_rows=args.max_total_rows,
            spill_dir=spill_dir,
            balanced_by_date=args.sampling_strategy == "balanced_by_date",
            max_rows_per_date=args.max_rows_per_date,
        )
    if df.empty:
        logger.error("No data loaded. Exiting.")
        return

    if args.live_aligned_rows:
        pre_alignment_rows = len(df)
        df = _align_training_rows_to_live_scoring(
            df, bucket_seconds=args.alignment_bucket_seconds
        )
        logger.info(
            "Live-aligned training rows at %ss buckets: %s -> %s rows",
            args.alignment_bucket_seconds,
            pre_alignment_rows,
            len(df),
        )

    if args.side_aware_context_features:
        pre_context_cols = len(df.columns)
        df = _augment_training_context_features(
            df,
            enable_side_aware_context_features=args.side_aware_context_features,
        )
        logger.info(
            "Added side-aware context features: %s -> %s columns",
            pre_context_cols,
            len(df.columns),
        )

    dataset_summary = _coverage_summary(df)
    if dataset_summary["dates"] < args.min_dates:
        raise RuntimeError(
            f"Dataset has only {dataset_summary['dates']} dates, require at least {args.min_dates}"
        )
    if len(dataset_summary["rows_by_session"]) < args.min_session_buckets:
        raise RuntimeError(
            "Dataset session coverage is insufficient: "
            f"{len(dataset_summary['rows_by_session'])} buckets present, "
            f"require at least {args.min_session_buckets}"
        )

    logger.info(
        "Prepared dataset: %s rows, %s symbols, %s dates",
        len(df),
        df["symbol"].nunique(),
        df["date"].nunique(),
    )

    # Step 2: Get feature columns
    if args.model_family in {"two_stage_logistic", "two_stage_xgb"}:
        df, label_col = _derive_executable_edge_labels(
            df,
            args.horizon,
            args.stage1_edge_bps,
            args.stage1_spread_weight,
            args.stage1_open_penalty_bps,
            args.stage1_raw_penalty_bps,
        )
        stage1_feature_cols = [
            c
            for c in get_ml_feature_columns(df, stage="stage1")
            if not c.startswith("ret_fwd_") and not c.startswith("label_")
        ]
        stage2_feature_cols = [
            c
            for c in get_ml_feature_columns(df, stage="stage2")
            if not c.startswith("ret_fwd_") and not c.startswith("label_")
        ]
        if (
            args.side_aware_context_features
            and args.side_aware_context_stage == "stage2_only"
        ):
            side_aware_cols = set(get_side_aware_context_columns())
            stage1_feature_cols = [
                c for c in stage1_feature_cols if c not in side_aware_cols
            ]
        feature_cols = list(dict.fromkeys(stage1_feature_cols + stage2_feature_cols))
        feature_summary = {
            "stage1_count": len(stage1_feature_cols),
            "stage2_count": len(stage2_feature_cols),
            "stage1_sample": stage1_feature_cols[:12],
            "stage2_sample": stage2_feature_cols[:12],
            "side_aware_context_stage": (
                args.side_aware_context_stage
                if args.side_aware_context_features
                else "disabled"
            ),
        }
    else:
        label_col = f"label_{args.horizon}s"
        stage1_feature_cols = []
        stage2_feature_cols = []
        feature_cols = get_ml_feature_columns(df)
        feature_summary = None
    label_summary = _label_summary(df, label_col, args.model_family)
    feature_cols = [
        c
        for c in feature_cols
        if not c.startswith("ret_fwd_") and not c.startswith("label_")
    ]
    logger.info("Feature columns: %s", len(feature_cols))

    df[feature_cols] = (
        df[feature_cols]
        .astype("float32")
        .fillna(0)
        .replace([float("inf"), float("-inf")], 0)
    )

    # Step 3: Temporal split
    train_df, val_df, test_df, split_info = temporal_split(df)
    logger.info(f"Train: {len(train_df)}, Val: {len(val_df)}, Test: {len(test_df)}")

    # Step 4: Restrict fitting to the non-holdout symbol universe and build folds on train dates
    training_df = _select_training_universe(df, split_info)
    training_weights = _apply_training_balance_weights(training_df, label_col=label_col)
    logger.info(
        "Training universe: %s rows, %s symbols",
        len(training_df),
        training_df["symbol"].nunique(),
    )
    folds, fold_strategy = resolve_training_folds(
        df=training_df,
        label_col=label_col,
        candidate_folds=walk_forward_folds(split_info.train_dates),
        fallback_folds=_fallback_folds(split_info),
    )
    logger.info("Training fold strategy: %s (%s folds)", fold_strategy, len(folds))

    # Step 5: Train
    trainer_params = {}
    if args.xgb_n_jobs is not None:
        trainer_params["n_jobs"] = args.xgb_n_jobs
    else:
        trainer_params["n_jobs"] = args.cpu_limit

    if args.model_family == "two_stage_logistic":
        best_params = {
            "model_family": "two_stage_logistic",
            "balancing": "source/date/session/symbol_inverse_sqrt",
            "stage1_edge_bps": args.stage1_edge_bps,
            "stage1_spread_weight": args.stage1_spread_weight,
            "stage1_open_penalty_bps": args.stage1_open_penalty_bps,
            "stage1_raw_penalty_bps": args.stage1_raw_penalty_bps,
            "side_aware_context_features": args.side_aware_context_features,
            "side_aware_context_stage": (
                args.side_aware_context_stage
                if args.side_aware_context_features
                else "disabled"
            ),
        }
        grid_results = None
        result = train_two_stage_walk_forward(
            training_df,
            feature_cols,
            stage1_feature_cols,
            stage2_feature_cols,
            label_col,
            folds,
            sample_weights=training_weights,
        )
    elif args.model_family == "two_stage_xgb":
        best_params = {
            "model_family": "two_stage_xgb",
            "balancing": "source/date/session/symbol_inverse_sqrt",
            "stage1_edge_bps": args.stage1_edge_bps,
            "stage1_spread_weight": args.stage1_spread_weight,
            "stage1_open_penalty_bps": args.stage1_open_penalty_bps,
            "stage1_raw_penalty_bps": args.stage1_raw_penalty_bps,
            "side_aware_context_features": args.side_aware_context_features,
            "side_aware_context_stage": (
                args.side_aware_context_stage
                if args.side_aware_context_features
                else "disabled"
            ),
        }
        grid_results = None
        result = train_two_stage_xgb_walk_forward(
            training_df,
            feature_cols,
            stage1_feature_cols,
            stage2_feature_cols,
            label_col,
            folds,
            sample_weights=training_weights,
        )
    elif args.grid_search:
        logger.info("Running grid search...")
        best_params, grid_results = grid_search(
            training_df, feature_cols, label_col, folds
        )
        logger.info(f"Best params: {best_params}")
        result = train_walk_forward(
            training_df,
            feature_cols,
            label_col,
            folds,
            params={**best_params, **trainer_params},
        )
    else:
        best_params = None
        grid_results = None
        result = train_walk_forward(
            training_df, feature_cols, label_col, folds, params=trainer_params
        )

    logger.info(f"Mean val accuracy: {result.mean_val_acc:.3f}")
    logger.info(f"Train-val gap: {result.train_val_gap:.3f}")

    calibration_summary = None
    if args.fit_calibrator:
        thresholds = tuple(
            float(value.strip())
            for value in args.threshold_grid.split(",")
            if value.strip()
        )
        X_val, y_val = _validation_rows(df, split_info, feature_cols, label_col)
        if args.model_family in {"two_stage_logistic", "two_stage_xgb"}:
            result.best_model.fit_calibrator(X_val, y_val)
            calibrator = None
            calibrated_val_probs = result.best_model.predict_proba(X_val)
            calibration_method = "two_stage_isotonic"
        else:
            calibrator = fit_probability_calibrator(result.best_model, X_val, y_val)
            calibrated_val_probs = predict_calibrated_proba(
                result.best_model, X_val, calibrator
            )
            calibration_method = "multiclass_isotonic"
        recommended_threshold, threshold_selection = select_confidence_threshold(
            calibrated_val_probs,
            y_val,
            thresholds=thresholds,
            min_directional_precision=args.threshold_min_directional_precision,
            min_trigger_count=args.threshold_min_trigger_count,
        )
        result.calibrator = calibrator
        result.threshold_selection = threshold_selection
        result.recommended_threshold = recommended_threshold
        calibration_summary = {
            "method": calibration_method,
            "validation_rows": int(len(y_val)),
            "recommended_threshold": recommended_threshold,
            "threshold_selection": threshold_selection,
            "min_directional_precision": args.threshold_min_directional_precision,
            "min_trigger_count": args.threshold_min_trigger_count,
        }
        logger.info(
            "Calibration complete: recommended threshold=%s on %s validation rows",
            (
                f"{recommended_threshold:.2f}"
                if recommended_threshold is not None
                else "unavailable"
            ),
            len(y_val),
        )

    # Step 6: Evaluate on test set
    test_acc = _evaluate_test_accuracy(
        df,
        split_info,
        feature_cols,
        label_col,
        result.best_model,
        calibrator=result.calibrator,
    )
    if test_acc is not None:
        logger.info(f"Test accuracy: {test_acc:.3f}")

    # Step 7: Feature importance
    top_features = sorted(
        result.fold_results[result.best_fold_idx].feature_importance.items(),
        key=lambda x: x[1],
        reverse=True,
    )[:20]
    logger.info("Top 20 features:")
    for name, imp in top_features:
        logger.info(f"  {name}: {imp:.4f}")

    # Step 8: Quality gate and save
    _write_training_reports(
        report_dir=Path(args.report_dir),
        dataset_summary=dataset_summary,
        label_summary=label_summary,
        split_info=split_info,
        fold_strategy=fold_strategy,
        result=result,
        test_accuracy=test_acc,
        best_params=best_params,
        grid_results=grid_results,
        calibration_summary=calibration_summary,
        feature_summary=feature_summary,
    )
    gate = _build_quality_gate(args)
    failures = quality_gate_failures(
        result, fold_strategy, gate, test_accuracy=test_acc
    )
    if failures:
        for failure in failures:
            logger.error("Quality gate failed: %s", failure)
        raise RuntimeError("Model failed quality gate; refusing to save artifact")

    save_model(result, args.save_path)
    logger.info(f"Model saved to {args.save_path}")


if __name__ == "__main__":
    main()
