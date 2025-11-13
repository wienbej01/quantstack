"""Dataset instrumentation utilities for intraday ML Sprint 1.

This module rebuilds per-split datasets (train/test/oos) using the
leak-free sliding window data prep and emits daily label distributions.
It ensures the cohorts respect SIP filtering so we can quantify
class sparsity before running expensive training/backtesting jobs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Sequence

import pandas as pd

from extensions.intraday_ml.data_prep import create_training_dataset
from extensions.intraday_ml.sip_membership import get_phase_symbols_with_sip


DatasetBuilder = Callable[..., pd.DataFrame]


@dataclass(slots=True)
class DatasetInstrumentationResult:
    """Summary of a single split instrumentation run."""

    split: str
    symbols: list[str]
    rows: int
    label_counts: dict[int, int]
    dataset_path: Path | None
    daily_distribution_path: Path | None
    symbol_distribution_path: Path | None


class DatasetInstrumentor:
    """Builds SIP-aware datasets and emits label distribution artefacts."""

    def __init__(
        self,
        *,
        splits_config: dict[str, Any],
        sip_config: dict[str, Any] | None,
        features_config: dict[str, Any],
        targets_config: dict[str, Any],
        data_loader_config: dict[str, Any] | None,
        artifact_dir: str | Path,
        dataset_builder: DatasetBuilder | None = None,
        label_buffer_days: int | dict[str, int] = 5,
    ) -> None:
        self.splits_config = splits_config
        self.sip_config = sip_config or {"enabled": False}
        self.features_config = features_config
        self.targets_config = targets_config
        self.data_loader_config = data_loader_config
        self.artifact_dir = Path(artifact_dir)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        self.dataset_builder = dataset_builder or create_training_dataset
        self.label_buffer_days = label_buffer_days

    def instrument_split(
        self,
        split: str,
        candidate_symbols: Sequence[str],
    ) -> DatasetInstrumentationResult:
        """Instrument a single split and emit artefacts."""
        if split not in self.splits_config:
            raise ValueError(f"Split '{split}' not found in splits configuration.")

        split_cfg = self.splits_config[split]
        start_date = str(split_cfg.get("start"))
        end_date = str(split_cfg.get("end"))
        if not start_date or not end_date:
            raise ValueError(f"Split '{split}' must define 'start' and 'end' dates.")

        resolved_symbols = get_phase_symbols_with_sip(
            splits_config=self.splits_config,
            sip_config=self.sip_config,
            candidate_symbols=list(candidate_symbols),
            phase=split,
            verbose=False,
        )

        if not resolved_symbols:
            return DatasetInstrumentationResult(
                split=split,
                symbols=[],
                rows=0,
                label_counts={},
                dataset_path=None,
                daily_distribution_path=None,
                symbol_distribution_path=None,
            )

        buffer_days = self._get_buffer_days(split)
        end_with_buffer = (
            datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=buffer_days)
        ).strftime("%Y-%m-%d")

        dataset = self.dataset_builder(
            symbols=resolved_symbols,
            start_date=start_date,
            end_date=end_with_buffer,
            features_config=self.features_config,
            targets_config=self.targets_config,
            data_loader_config=self.data_loader_config,
            include_ohlcv=True,
        )

        if dataset.empty:
            return DatasetInstrumentationResult(
                split=split,
                symbols=resolved_symbols,
                rows=0,
                label_counts={},
                dataset_path=None,
                daily_distribution_path=None,
                symbol_distribution_path=None,
            )

        dataset = self._trim_to_window(dataset, start_date, end_date)
        if dataset.empty:
            return DatasetInstrumentationResult(
                split=split,
                symbols=resolved_symbols,
                rows=0,
                label_counts={},
                dataset_path=None,
                daily_distribution_path=None,
                symbol_distribution_path=None,
            )

        dataset_path = self.artifact_dir / f"{split}_dataset.parquet"
        dataset.to_parquet(dataset_path)

        label_counts = dataset["label"].value_counts().to_dict()
        daily_df = _compute_daily_distribution(dataset)
        daily_path = self.artifact_dir / f"{split}_label_distribution.csv"
        daily_df.to_csv(daily_path, index=False)

        symbol_df = _compute_symbol_distribution(dataset)
        symbol_path = self.artifact_dir / f"{split}_symbol_label_distribution.csv"
        symbol_df.to_csv(symbol_path, index=False)

        return DatasetInstrumentationResult(
            split=split,
            symbols=sorted(dataset["symbol"].unique().tolist()),
            rows=int(len(dataset)),
            label_counts={int(k): int(v) for k, v in label_counts.items()},
            dataset_path=dataset_path,
            daily_distribution_path=daily_path,
            symbol_distribution_path=symbol_path,
        )

    def _get_buffer_days(self, split: str) -> int:
        if isinstance(self.label_buffer_days, dict):
            return int(self.label_buffer_days.get(split, 0))
        return int(self.label_buffer_days)

    @staticmethod
    def _trim_to_window(
        dataset: pd.DataFrame,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        if "ts" not in dataset.columns:
            raise ValueError("Instrumented dataset is missing 'ts' column.")

        timestamps = pd.to_datetime(dataset["ts"], errors="coerce", utc=False)
        if timestamps.isna().any():
            raise ValueError("Instrumented dataset contains malformed timestamps.")

        start_ts = pd.to_datetime(f"{start_date} 00:00:00")
        end_ts = pd.to_datetime(f"{end_date} 23:59:59")
        mask = (timestamps >= start_ts) & (timestamps <= end_ts)
        trimmed = dataset.loc[mask].copy()
        trimmed["ts"] = timestamps.loc[mask]
        return trimmed.reset_index(drop=True)


def _normalize_label_columns(df: pd.DataFrame) -> pd.DataFrame:
    label_columns = [-1, 0, 1]
    for label in label_columns:
        col = f"label_{label}"
        if col not in df.columns:
            df[col] = 0
    return df[["trade_date", "label_-1", "label_0", "label_1"]]


def _compute_daily_distribution(dataset: pd.DataFrame) -> pd.DataFrame:
    if dataset.empty:
        return pd.DataFrame(columns=["trade_date", "label_-1", "label_0", "label_1"])

    frame = dataset.copy()
    frame["trade_date"] = pd.to_datetime(frame["ts"]).dt.date.astype(str)
    grouped = (
        frame.groupby(["trade_date", "label"], dropna=False)
        .size()
        .unstack(fill_value=0)
        .rename(columns=lambda col: f"label_{int(col)}")
        .reset_index()
    )
    return _normalize_label_columns(grouped)


def _compute_symbol_distribution(dataset: pd.DataFrame) -> pd.DataFrame:
    if dataset.empty:
        return pd.DataFrame(columns=["symbol", "trade_date", "label_-1", "label_0", "label_1"])

    frame = dataset.copy()
    frame["trade_date"] = pd.to_datetime(frame["ts"]).dt.date.astype(str)
    grouped = (
        frame.groupby(["symbol", "trade_date", "label"], dropna=False)
        .size()
        .unstack(fill_value=0)
        .rename(columns=lambda col: f"label_{int(col)}")
        .reset_index()
    )

    for label in (-1, 0, 1):
        col = f"label_{label}"
        if col not in grouped.columns:
            grouped[col] = 0

    ordered_cols = ["symbol", "trade_date", "label_-1", "label_0", "label_1"]
    return grouped[ordered_cols]
