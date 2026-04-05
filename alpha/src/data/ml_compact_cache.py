"""Compact ML feature cache and smarter sampler for laptop-safe training."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

from ..features.ml_features import compute_ml_features
from .ml_dataset import MLDatasetBuilder, optimize_memory
from .ml_label_artifacts import (
    LabelArtifactConfig,
    align_full_resolution_labels,
    build_label_artifact,
)

logger = logging.getLogger(__name__)

_LAST_VALUE_COLUMNS = {
    "mid",
    "spread",
    "microprice",
    "micro_off",
    "depth_bid_k",
    "depth_ask_k",
    "depth_imb_k",
    "pressure_k",
    "obi_1",
    "obi_2",
    "obi_3",
    "obi_5",
    "obi_10",
    "symbol",
    "date",
}
_MEAN_VALUE_COLUMNS = {
    "mid",
    "spread",
    "microprice",
    "micro_off",
    "depth_bid_k",
    "depth_ask_k",
    "depth_imb_k",
    "pressure_k",
    "obi_1",
    "obi_2",
    "obi_3",
    "obi_5",
    "obi_10",
}


@dataclass(frozen=True)
class CompactCacheConfig:
    """Configuration for compact cache generation and sampling."""

    bucket_seconds: int = 1
    event_threshold: float = 1.0
    session_weights: tuple[float, float, float, float] = (0.35, 0.25, 0.15, 0.25)
    event_share: float = 0.6
    min_rows_per_session: int = 50


def build_compact_feature_frame(
    symbol_day_df: pd.DataFrame,
    label_config: LabelArtifactConfig | None = None,
    compact_config: CompactCacheConfig | None = None,
) -> pd.DataFrame:
    """Compress one symbol-day to compact feature rows with full-resolution labels."""
    if symbol_day_df.empty:
        raise ValueError("symbol_day_df must not be empty")

    label_cfg = label_config or LabelArtifactConfig()
    compact_cfg = compact_config or CompactCacheConfig()
    ordered = symbol_day_df.sort_values("ts_utc").reset_index(drop=True).copy()
    ordered["ts_utc"] = pd.to_datetime(ordered["ts_utc"], utc=True)
    ordered["bucket_ts"] = ordered["ts_utc"].dt.floor(f"{compact_cfg.bucket_seconds}s")

    aggregations = {}
    for column in ordered.columns:
        if column == "bucket_ts":
            continue
        if column in {"ts_utc", "ts_epoch"}:
            aggregations[column] = "last"
        elif column == "source_type":
            aggregations[column] = "last"
        elif column in _LAST_VALUE_COLUMNS:
            aggregations[column] = "last"
        elif pd.api.types.is_numeric_dtype(ordered[column]):
            aggregations[column] = "mean" if column in _MEAN_VALUE_COLUMNS else "last"

    compact = (
        ordered.groupby("bucket_ts", as_index=False)
        .agg(aggregations)
        .rename(columns={"bucket_ts": "ts_bucket"})
    )
    compact["ts_utc"] = pd.to_datetime(compact["ts_utc"], utc=True)
    compact = compact.drop_duplicates(subset=["ts_utc"], keep="last").reset_index(
        drop=True
    )

    compact = compute_ml_features(compact)
    compact["event_score"] = compute_event_score(compact)
    compact["event_flag"] = compact["event_score"] >= compact_cfg.event_threshold

    labels = build_label_artifact(ordered, config=label_cfg)
    aligned = align_full_resolution_labels(labels, compact["ts_utc"])
    compact = pd.concat(
        [compact.reset_index(drop=True), aligned.reset_index(drop=True)], axis=1
    )
    return optimize_memory(compact)


def compute_event_score(df: pd.DataFrame) -> pd.Series:
    """Score rows by magnitude of market-state change."""
    components = []
    for column in ("spread", "micro_off", "obi_1", "pressure_k", "depth_imb_k"):
        if column not in df.columns:
            continue
        series = pd.to_numeric(df[column], errors="coerce")
        deltas = series.diff().abs().fillna(0.0)
        scale = float(deltas.std()) or 1.0
        components.append(deltas / scale)

    if not components:
        return pd.Series(np.zeros(len(df), dtype=np.float32), index=df.index)

    stacked = pd.concat(components, axis=1).fillna(0.0)
    return stacked.mean(axis=1).astype(np.float32)


def stratified_sample_compact_rows(
    compact_df: pd.DataFrame,
    max_rows: Optional[int] = None,
    config: CompactCacheConfig | None = None,
) -> pd.DataFrame:
    """Sample compact rows by session bucket and event intensity."""
    cfg = config or CompactCacheConfig()
    effective_max_rows = max_rows

    if (
        effective_max_rows is None
        or compact_df.empty
        or len(compact_df) <= effective_max_rows
    ):
        return compact_df.reset_index(drop=True)

    weights = list(cfg.session_weights)
    sampled_frames: list[pd.DataFrame] = []
    total_weight = sum(weights)

    for bucket, weight in enumerate(weights):
        session_df = compact_df[compact_df["session_bucket"] == float(bucket)].copy()
        if session_df.empty:
            continue
        quota = max(
            cfg.min_rows_per_session, int(effective_max_rows * weight / total_weight)
        )
        quota = min(quota, len(session_df))
        event_quota = min(int(quota * cfg.event_share), len(session_df))
        base_quota = quota - event_quota

        top_events = session_df.sort_values(
            ["event_score", "ts_utc"], ascending=[False, True]
        ).head(event_quota)
        remaining = session_df.drop(index=top_events.index)

        if base_quota > 0 and not remaining.empty:
            if len(remaining) <= base_quota:
                background = remaining
            else:
                positions = np.linspace(
                    0, len(remaining) - 1, num=base_quota, dtype=int
                )
                background = remaining.iloc[positions]
            sampled_frames.append(background)

        sampled_frames.append(top_events)

    if not sampled_frames:
        return compact_df.head(max_rows).reset_index(drop=True)

    sampled = pd.concat(sampled_frames, ignore_index=False).sort_values("ts_utc")
    sampled = sampled[~sampled.index.duplicated(keep="first")]

    if len(sampled) > effective_max_rows:
        positions = np.linspace(0, len(sampled) - 1, num=effective_max_rows, dtype=int)
        sampled = sampled.iloc[positions]

    return sampled.reset_index(drop=True)


def summarize_compact_rows(compact_df: pd.DataFrame) -> dict[str, object]:
    """Summarize compact rows for manifests and training reports."""
    session_counts = (
        compact_df["session_bucket"].value_counts(dropna=False).sort_index().to_dict()
        if "session_bucket" in compact_df.columns
        else {}
    )
    event_rows = (
        int(compact_df["event_flag"].fillna(False).sum())
        if "event_flag" in compact_df.columns
        else 0
    )
    source_counts = (
        compact_df["source_type"].value_counts(dropna=False).to_dict()
        if "source_type" in compact_df.columns
        else {}
    )
    return {
        "rows": int(len(compact_df)),
        "symbols": (
            int(compact_df["symbol"].nunique()) if "symbol" in compact_df.columns else 0
        ),
        "dates": (
            int(compact_df["date"].nunique()) if "date" in compact_df.columns else 0
        ),
        "event_rows": event_rows,
        "session_counts": {
            str(key): int(value) for key, value in session_counts.items()
        },
        "source_counts": {str(key): int(value) for key, value in source_counts.items()},
    }


def save_compact_cache(
    output_dir: str | Path,
    builder: Optional[MLDatasetBuilder] = None,
    label_config: LabelArtifactConfig | None = None,
    compact_config: CompactCacheConfig | None = None,
    sample_rows_per_symbol_day: Optional[int] = None,
) -> list[Path]:
    """Build and save compact feature cache for all available symbol-days."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset_builder = builder or MLDatasetBuilder()
    label_cfg = label_config or LabelArtifactConfig()
    compact_cfg = compact_config or CompactCacheConfig()
    saved_paths: list[Path] = []
    manifest_rows: list[dict[str, object]] = []

    for chunk in dataset_builder.iter_symbol_days():
        symbol = str(chunk["symbol"].iloc[0])
        date = str(chunk["date"].iloc[0])
        try:
            compact = build_compact_feature_frame(
                chunk, label_config=label_cfg, compact_config=compact_cfg
            )
            compact = stratified_sample_compact_rows(
                compact,
                max_rows=sample_rows_per_symbol_day,
                config=compact_cfg,
            )
            path = out_dir / f"date={date}" / f"symbol={symbol}" / "compact.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            compact.to_parquet(path, index=False)
            saved_paths.append(path)
            summary = summarize_compact_rows(compact)
            manifest_rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "path": str(path),
                    "status": "ok",
                    **summary,
                }
            )
            logger.info("Saved compact cache for %s/%s to %s", symbol, date, path)
        except Exception as exc:
            manifest_rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "status": "error",
                    "error": str(exc),
                }
            )
            logger.warning("Skipping compact cache for %s/%s: %s", symbol, date, exc)

    manifest = {
        "config": {
            "label_config": asdict(label_cfg),
            "compact_config": asdict(compact_cfg),
            "sample_rows_per_symbol_day": sample_rows_per_symbol_day,
        },
        "entries": manifest_rows,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    logger.info("Saved compact cache manifest to %s", manifest_path)

    report_lines = [
        "# Compact Cache Sampling Report",
        "",
        f"- symbol-days cached: {len(manifest_rows)}",
        f"- total rows cached: {sum(int(row['rows']) for row in manifest_rows)}",
        f"- unique dates: {len({row['date'] for row in manifest_rows})}",
        f"- unique symbols: {len({row['symbol'] for row in manifest_rows})}",
    ]
    report_path = out_dir / "sampling_report.md"
    report_path.write_text("\n".join(report_lines) + "\n")
    logger.info("Saved compact cache report to %s", report_path)

    return saved_paths


def load_compact_cache(
    cache_dir: str | Path,
    dates: Optional[Iterable[str]] = None,
    symbols: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """Load compact cached parquet rows from disk."""
    root = Path(cache_dir)
    files = sorted(root.glob("date=*/symbol=*/compact.parquet"))
    if dates is not None:
        allowed_dates = set(dates)
        files = [
            path
            for path in files
            if path.parent.parent.name.split("=", 1)[1] in allowed_dates
        ]
    if symbols is not None:
        allowed_symbols = set(symbols)
        files = [
            path
            for path in files
            if path.parent.name.split("=", 1)[1] in allowed_symbols
        ]
    if not files:
        return pd.DataFrame()
    return optimize_memory(
        pd.concat((pd.read_parquet(path) for path in files), ignore_index=True)
    )
