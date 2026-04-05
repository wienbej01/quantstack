"""Full-resolution ML label artifacts.

Builds label tables from full-resolution symbol-day paths, so later feature
compression does not alter causal label semantics.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Literal, Optional

import pandas as pd

from .ml_dataset import MLDatasetBuilder, optimize_memory
from .ml_labels import generate_barrier_labels, generate_labels

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LabelArtifactConfig:
    """Configuration for full-resolution label artifact generation."""

    horizons_seconds: tuple[int, ...] = (60, 180, 300)
    threshold_method: str = "fixed"
    fixed_bps: float = 10.0
    label_mode: Literal["mid_return", "barrier", "both"] = "mid_return"
    stop_bps: float = 10.0
    take_profit_bps: float = 10.0
    direction: Literal["long", "short"] = "long"
    tie_break_policy: Literal["worst_case", "best_case", "neutral"] = "worst_case"


def build_label_artifact(
    symbol_day_df: pd.DataFrame,
    config: LabelArtifactConfig | None = None,
) -> pd.DataFrame:
    """Generate labels from the full-resolution path for one symbol-day."""
    if symbol_day_df.empty:
        raise ValueError("symbol_day_df must not be empty")

    cfg = config or LabelArtifactConfig()
    ordered = symbol_day_df.sort_values("ts_utc").reset_index(drop=True).copy()
    labeled = ordered
    if cfg.label_mode in {"mid_return", "both"}:
        labeled = generate_labels(
            labeled,
            horizons_seconds=list(cfg.horizons_seconds),
            threshold_method=cfg.threshold_method,
            fixed_bps=cfg.fixed_bps,
        )
    if cfg.label_mode in {"barrier", "both"}:
        labeled = generate_barrier_labels(
            labeled,
            horizons_seconds=list(cfg.horizons_seconds),
            stop_bps=cfg.stop_bps,
            take_profit_bps=cfg.take_profit_bps,
            direction=cfg.direction,
            tie_break_policy=cfg.tie_break_policy,
        )
    labeled["artifact_row_id"] = range(len(labeled))
    for key, value in asdict(cfg).items():
        labeled.attrs[key] = value
    return optimize_memory(labeled)


def align_full_resolution_labels(
    label_artifact: pd.DataFrame,
    target_timestamps: pd.Series,
    label_columns: Optional[Iterable[str]] = None,
) -> pd.DataFrame:
    """Attach full-resolution labels to compact timestamps without recomputing them."""
    if label_artifact.empty:
        raise ValueError("label_artifact must not be empty")
    if target_timestamps.empty:
        return pd.DataFrame(index=target_timestamps.index)

    label_artifact = label_artifact.sort_values("ts_utc").reset_index(drop=True)
    target = pd.DataFrame({"ts_utc": pd.to_datetime(target_timestamps, utc=True)})
    columns = (
        list(label_columns)
        if label_columns is not None
        else [
            column
            for column in label_artifact.columns
            if column.startswith("ret_fwd_") or column.startswith("label_")
        ]
    )
    aligned = pd.merge_asof(
        target.sort_values("ts_utc"),
        label_artifact[["ts_utc", *columns]].sort_values("ts_utc"),
        on="ts_utc",
        direction="backward",
    )
    aligned.index = target.sort_values("ts_utc").index
    aligned = aligned.reindex(target.index)
    return aligned[columns]


def save_label_artifacts(
    output_dir: str | Path,
    config: LabelArtifactConfig | None = None,
    builder: Optional[MLDatasetBuilder] = None,
) -> list[Path]:
    """Build and save full-resolution label artifacts for all available symbol-days."""
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset_builder = builder or MLDatasetBuilder()
    cfg = config or LabelArtifactConfig()
    saved_paths: list[Path] = []
    manifest_rows: list[dict[str, object]] = []

    for chunk in dataset_builder.iter_symbol_days():
        artifact = build_label_artifact(chunk, config=cfg)
        date = str(artifact["date"].iloc[0])
        symbol = str(artifact["symbol"].iloc[0])
        path = out_dir / f"date={date}" / f"symbol={symbol}" / "labels.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        artifact.to_parquet(path, index=False)
        saved_paths.append(path)
        label_columns = [
            column
            for column in artifact.columns
            if column.startswith(("label_", "barrier_label_"))
        ]
        valid_ratio = (
            float(artifact[label_columns].notna().any(axis=1).mean())
            if label_columns
            else 0.0
        )
        manifest_rows.append(
            {
                "date": date,
                "symbol": symbol,
                "rows": int(len(artifact)),
                "label_columns": label_columns,
                "label_valid_ratio": valid_ratio,
                "first_ts_utc": artifact["ts_utc"].min().isoformat(),
                "last_ts_utc": artifact["ts_utc"].max().isoformat(),
                "source_mode": cfg.label_mode,
                "artifact_path": str(path),
            }
        )
        logger.info("Saved label artifact for %s/%s to %s", symbol, date, path)

    manifest_path = out_dir / "manifest.json"
    manifest = {
        "config": asdict(cfg),
        "artifacts": manifest_rows,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2))
    logger.info("Saved label artifact manifest to %s", manifest_path)
    return saved_paths
