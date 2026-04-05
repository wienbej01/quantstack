"""Tests for compact ML cache and smarter sampler."""

import numpy as np
import pandas as pd

from src.data.ml_compact_cache import (
    CompactCacheConfig,
    build_compact_feature_frame,
    compute_event_score,
    stratified_sample_compact_rows,
)
from src.data.ml_label_artifacts import LabelArtifactConfig, build_label_artifact


def _make_symbol_day(n: int = 2400, interval_seconds: float = 10.0) -> pd.DataFrame:
    rng = np.random.RandomState(7)
    ts = 1736433000 + np.arange(n) * interval_seconds
    mid = 100 + np.cumsum(rng.randn(n) * 0.01)
    spread = 0.01 + np.abs(rng.randn(n)) * 0.002
    return pd.DataFrame(
        {
            "ts_utc": pd.to_datetime(ts, unit="s", utc=True),
            "ts_epoch": ts.astype(float),
            "symbol": "TEST",
            "date": "2026-01-08",
            "mid": mid,
            "spread": spread,
            "microprice": mid + rng.randn(n) * 0.001,
            "micro_off": rng.randn(n) * 0.001,
            "depth_bid_k": rng.randint(500, 1500, n).astype(float),
            "depth_ask_k": rng.randint(500, 1500, n).astype(float),
            "depth_imb_k": rng.randn(n) * 0.2,
            "pressure_k": rng.randn(n) * 100,
            "obi_1": rng.randn(n) * 0.2,
            "obi_2": rng.randn(n) * 0.2,
            "obi_3": rng.randn(n) * 0.2,
            "obi_5": rng.randn(n) * 0.2,
            "obi_10": rng.randn(n) * 0.2,
            "d_mid_5s": rng.randn(n) * 0.01,
            "d_spread_5s": rng.randn(n) * 0.001,
            "d_obi_1_5s": rng.randn(n) * 0.1,
            "d_micro_off_5s": rng.randn(n) * 0.001,
            "d_mid_15s": rng.randn(n) * 0.01,
            "d_spread_15s": rng.randn(n) * 0.001,
            "d_obi_1_15s": rng.randn(n) * 0.1,
            "d_micro_off_15s": rng.randn(n) * 0.001,
            "d_mid_30s": rng.randn(n) * 0.01,
            "d_spread_30s": rng.randn(n) * 0.001,
            "d_obi_1_30s": rng.randn(n) * 0.1,
            "d_micro_off_30s": rng.randn(n) * 0.001,
            "d_mid_60s": rng.randn(n) * 0.01,
            "d_spread_60s": rng.randn(n) * 0.001,
            "d_obi_1_60s": rng.randn(n) * 0.1,
            "d_micro_off_60s": rng.randn(n) * 0.001,
        }
    )


class TestLabelArtifacts:
    def test_build_label_artifact_adds_artifact_row_id(self):
        df = _make_symbol_day()
        artifact = build_label_artifact(df, LabelArtifactConfig(horizons_seconds=(60,)))
        assert "artifact_row_id" in artifact.columns
        assert "label_60s" in artifact.columns


class TestCompactCache:
    def test_build_compact_feature_frame_preserves_labels(self):
        df = _make_symbol_day()
        df["source_type"] = "features"
        compact = build_compact_feature_frame(
            df,
            label_config=LabelArtifactConfig(horizons_seconds=(60,)),
            compact_config=CompactCacheConfig(bucket_seconds=1),
        )
        assert "label_60s" in compact.columns
        assert "event_score" in compact.columns
        assert "event_flag" in compact.columns
        assert "source_type" in compact.columns
        assert set(compact["source_type"].dropna().unique()) == {"features"}
        assert compact["ts_utc"].is_monotonic_increasing

    def test_stratified_sample_compact_rows_covers_multiple_sessions(self):
        df = _make_symbol_day(n=2400)
        compact = build_compact_feature_frame(
            df,
            label_config=LabelArtifactConfig(horizons_seconds=(60,)),
            compact_config=CompactCacheConfig(
                bucket_seconds=1, min_rows_per_session=10
            ),
        )
        sampled = stratified_sample_compact_rows(
            compact,
            max_rows=80,
            config=CompactCacheConfig(min_rows_per_session=5),
        )
        assert len(sampled) <= 80
        assert sampled["event_score"].notna().all()
        assert sampled["session_bucket"].nunique() >= 2

    def test_compute_event_score_handles_object_columns_with_none(self):
        df = _make_symbol_day(n=240)
        compact = build_compact_feature_frame(
            df,
            label_config=LabelArtifactConfig(horizons_seconds=(60,)),
            compact_config=CompactCacheConfig(bucket_seconds=1),
        )
        compact["spread"] = compact["spread"].astype(object)
        compact.loc[0, "spread"] = None
        compact.loc[1, "spread"] = None

        scores = compute_event_score(compact)

        assert len(scores) == len(compact)
        assert scores.notna().all()
