"""Tests for causal label artifacts and compact-cache manifests."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.data.ml_compact_cache import CompactCacheConfig, save_compact_cache
from src.data.ml_label_artifacts import (
    LabelArtifactConfig,
    build_label_artifact,
    save_label_artifacts,
)
from src.data.ml_labels import classify_barrier_outcome, generate_barrier_labels


def _make_symbol_day(
    mid_path: list[float], symbol: str = "TEST", date: str = "2026-03-10"
) -> pd.DataFrame:
    ts_utc = pd.date_range(
        "2026-03-10 14:30:00+00:00", periods=len(mid_path), freq="1s", tz="UTC"
    )
    base_depth = np.linspace(100.0, 150.0, num=len(mid_path))
    return pd.DataFrame(
        {
            "ts_utc": ts_utc,
            "ts_epoch": ts_utc.astype("int64") / 1e9,
            "symbol": symbol,
            "date": date,
            "mid": np.array(mid_path, dtype=float),
            "spread": np.full(len(mid_path), 0.02, dtype=float),
            "microprice": np.array(mid_path, dtype=float) + 0.001,
            "micro_off": np.full(len(mid_path), 0.001, dtype=float),
            "depth_bid_k": base_depth,
            "depth_ask_k": base_depth[::-1],
            "depth_imb_k": np.linspace(-0.2, 0.2, num=len(mid_path)),
            "pressure_k": np.linspace(-10.0, 10.0, num=len(mid_path)),
            "obi_1": np.linspace(-0.3, 0.3, num=len(mid_path)),
            "obi_2": np.linspace(-0.2, 0.2, num=len(mid_path)),
            "obi_3": np.linspace(-0.1, 0.1, num=len(mid_path)),
            "obi_5": np.linspace(-0.05, 0.05, num=len(mid_path)),
            "obi_10": np.linspace(-0.02, 0.02, num=len(mid_path)),
        }
    )


class _FakeBuilder:
    def __init__(self, frames: list[pd.DataFrame]):
        self._frames = frames

    def iter_symbol_days(self):
        yield from self._frames


def test_classify_barrier_outcome_respects_causal_order() -> None:
    tp_first = classify_barrier_outcome(
        future_mid=np.array([100.05, 100.12, 99.80]),
        entry_mid=100.0,
        stop_bps=10.0,
        take_profit_bps=10.0,
    )
    sl_first = classify_barrier_outcome(
        future_mid=np.array([99.85, 100.20, 100.30]),
        entry_mid=100.0,
        stop_bps=10.0,
        take_profit_bps=10.0,
    )
    simultaneous = classify_barrier_outcome(
        future_mid=np.array([100.0, 100.1]),
        entry_mid=100.0,
        stop_bps=0.0,
        take_profit_bps=0.0,
        tie_break_policy="neutral",
    )

    assert tp_first == "tp_first"
    assert sl_first == "sl_first"
    assert simultaneous == "simultaneous"


def test_generate_barrier_labels_creates_numeric_and_string_columns() -> None:
    df = _make_symbol_day([100.0, 100.02, 100.12, 99.85, 99.80])
    labeled = generate_barrier_labels(
        df, horizons_seconds=[3], stop_bps=10.0, take_profit_bps=10.0
    )

    assert "barrier_outcome_3s" in labeled.columns
    assert "barrier_label_3s" in labeled.columns
    assert labeled["barrier_outcome_3s"].iloc[0] == "tp_first"
    assert labeled["barrier_label_3s"].iloc[0] == 2


def test_build_label_artifact_supports_both_modes() -> None:
    df = _make_symbol_day([100.0, 100.01, 100.02, 100.03, 100.04, 100.05])
    artifact = build_label_artifact(
        df,
        config=LabelArtifactConfig(horizons_seconds=(2,), label_mode="both"),
    )

    assert "label_2s" in artifact.columns
    assert "barrier_label_2s" in artifact.columns
    assert "artifact_row_id" in artifact.columns


def test_save_label_artifacts_writes_manifest(tmp_path) -> None:
    frames = [
        _make_symbol_day(
            [100.0, 100.02, 100.01, 100.03], symbol="AAA", date="2026-03-10"
        )
    ]
    save_label_artifacts(
        tmp_path / "labels",
        config=LabelArtifactConfig(horizons_seconds=(2,), label_mode="both"),
        builder=_FakeBuilder(frames),
    )

    manifest = json.loads((tmp_path / "labels" / "manifest.json").read_text())
    assert manifest["config"]["label_mode"] == "both"
    assert len(manifest["artifacts"]) == 1
    assert manifest["artifacts"][0]["symbol"] == "AAA"


def test_save_compact_cache_writes_manifest_and_report(tmp_path) -> None:
    frames = [
        _make_symbol_day(
            list(np.linspace(100.0, 100.5, num=2400)), symbol="AAA", date="2026-03-10"
        )
    ]
    save_compact_cache(
        output_dir=tmp_path / "cache",
        builder=_FakeBuilder(frames),
        label_config=LabelArtifactConfig(horizons_seconds=(60,)),
        compact_config=CompactCacheConfig(bucket_seconds=1),
        sample_rows_per_symbol_day=500,
    )

    manifest = json.loads((tmp_path / "cache" / "manifest.json").read_text())
    assert len(manifest["entries"]) == 1
    assert manifest["entries"][0]["rows"] <= 500
    assert (tmp_path / "cache" / "sampling_report.md").exists()
