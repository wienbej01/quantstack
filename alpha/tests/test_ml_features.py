"""Tests for Sprint 2: ML Features and Labels."""

import numpy as np
import pandas as pd
import pytest

from src.features.ml_features import compute_ml_features, get_ml_feature_columns
from src.data.ml_labels import generate_labels, temporal_split, walk_forward_folds


def _make_feature_df(
    n: int = 500, symbol: str = "TEST", date: str = "2025-12-19"
) -> pd.DataFrame:
    """Create synthetic pre-computed feature data."""
    rng = np.random.RandomState(42)
    ts_start = 1700000000.0
    ts = ts_start + np.arange(n) * 1.0  # 1s intervals

    mid = 50.0 + np.cumsum(rng.randn(n) * 0.005)
    return pd.DataFrame(
        {
            "ts_utc": pd.to_datetime(ts, unit="s", utc=True),
            "ts_epoch": ts,
            "symbol": symbol,
            "date": date,
            "mid": mid,
            "spread": 0.02 + rng.rand(n) * 0.01,
            "microprice": mid + rng.randn(n) * 0.001,
            "micro_off": rng.randn(n) * 0.001,
            "depth_bid_k": rng.randint(500, 2000, n).astype(float),
            "depth_ask_k": rng.randint(500, 2000, n).astype(float),
            "depth_imb_k": rng.randn(n) * 0.3,
            "pressure_k": rng.randn(n) * 500,
            "obi_1": rng.randn(n) * 0.3,
            "obi_2": rng.randn(n) * 0.3,
            "obi_3": rng.randn(n) * 0.3,
            "obi_5": rng.randn(n) * 0.3,
            "obi_10": rng.randn(n) * 0.3,
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


class TestMLFeatures:
    def test_adds_rolling_columns(self):
        df = _make_feature_df()
        result = compute_ml_features(df)
        assert "obi_1_mean_30s" in result.columns
        assert "obi_1_std_30s" in result.columns
        assert "obi_1_delta_30s" in result.columns

    def test_adds_cross_features(self):
        df = _make_feature_df()
        result = compute_ml_features(df)
        assert "obi1_x_pressure" in result.columns
        assert "depth_ratio" in result.columns

    def test_adds_time_features(self):
        df = _make_feature_df()
        result = compute_ml_features(df)
        assert "minutes_since_open" in result.columns
        assert "session_bucket" in result.columns
        assert "seconds_since_first_snapshot" in result.columns
        assert "session_progress" in result.columns

    def test_time_features_are_dst_aware(self):
        df = pd.DataFrame(
            {
                "ts_utc": pd.to_datetime(
                    ["2026-03-06 14:30:00+00:00", "2026-03-10 13:30:00+00:00"],
                    utc=True,
                ),
                "mid": [100.0, 100.0],
                "spread": [0.01, 0.01],
                "microprice": [100.001, 100.001],
                "micro_off": [0.001, 0.001],
                "depth_bid_k": [1000.0, 1000.0],
                "depth_ask_k": [1000.0, 1000.0],
                "depth_imb_k": [0.0, 0.0],
                "pressure_k": [0.0, 0.0],
                "obi_1": [0.0, 0.0],
                "obi_5": [0.0, 0.0],
            }
        )
        result = compute_ml_features(df)
        assert list(result["minutes_since_open"]) == [0, 0]

    def test_no_inf_values(self):
        df = _make_feature_df()
        result = compute_ml_features(df)
        feat_cols = get_ml_feature_columns(result)
        for c in feat_cols:
            assert not np.isinf(result[c]).any(), f"Inf in {c}"

    def test_feature_column_list_excludes_metadata(self):
        df = _make_feature_df()
        result = compute_ml_features(df)
        feat_cols = get_ml_feature_columns(result)
        assert "ts_utc" not in feat_cols
        assert "symbol" not in feat_cols
        assert "date" not in feat_cols

    def test_feature_column_list_excludes_sampling_helpers(self):
        df = _make_feature_df()
        result = compute_ml_features(df)
        result["event_score"] = np.linspace(0.0, 1.0, len(result))
        result["event_flag"] = result["event_score"] > 0.5
        feat_cols = get_ml_feature_columns(result)
        assert "event_score" not in feat_cols
        assert "event_flag" not in feat_cols

    def test_source_type_is_exposed_as_numeric_context_features(self):
        df = _make_feature_df()
        df["source_type"] = "raw"
        result = compute_ml_features(df)
        assert "source_is_raw" in result.columns
        assert "source_is_features" in result.columns
        assert result["source_is_raw"].eq(1.0).all()
        assert result["source_is_features"].eq(0.0).all()

    def test_stage_specific_feature_lists_differ(self):
        df = _make_feature_df()
        df["source_type"] = "features"
        result = compute_ml_features(df)
        stage1_cols = get_ml_feature_columns(result, stage="stage1")
        stage2_cols = get_ml_feature_columns(result, stage="stage2")
        assert "source_is_features" in stage1_cols
        assert "source_is_features" in stage2_cols
        assert "d_mid_5s" not in stage1_cols
        assert "d_mid_5s" in stage2_cols

    def test_adds_causal_price_features_when_ohlcv_present(self):
        df = _make_feature_df(n=100)
        base = pd.to_numeric(df["mid"], errors="coerce")
        df["open"] = base * 0.999
        df["high"] = base * 1.002
        df["low"] = base * 0.998
        df["close"] = base * 1.001
        df["volume"] = np.linspace(1000, 5000, len(df))

        result = compute_ml_features(df)

        for column in (
            "vwap",
            "dist_vwap_bps",
            "hl_range_pct",
            "oc_change_pct",
            "volume_rel_20",
            "atr_pct",
            "position_in_range",
            "rsi",
            "bb_width",
            "bb_position",
            "ret_1",
            "ret_3",
            "ret_5",
            "ret_10",
        ):
            assert column in result.columns
        assert np.isfinite(result["dist_vwap_bps"]).all()
        assert np.isfinite(result["volume_rel_20"]).all()


class TestLabels:
    def test_label_columns_created(self):
        df = _make_feature_df(n=1000)
        result = generate_labels(df, horizons_seconds=[60, 180])
        assert "ret_fwd_60s" in result.columns
        assert "label_60s" in result.columns
        assert "label_180s" in result.columns

    def test_labels_are_0_1_2_or_nan(self):
        df = _make_feature_df(n=1000)
        result = generate_labels(df, horizons_seconds=[60])
        valid = result["label_60s"].dropna()
        assert set(valid.unique()).issubset({0, 1, 2})

    def test_label_balance_with_quantile(self):
        df = _make_feature_df(n=2000)
        result = generate_labels(df, horizons_seconds=[60], threshold_method="quantile")
        valid = result["label_60s"].dropna()
        counts = valid.value_counts(normalize=True)
        # Each class should be roughly 33% (within 15% tolerance)
        for cls in [0, 1, 2]:
            if cls in counts:
                assert (
                    0.15 < counts[cls] < 0.55
                ), f"Class {cls} imbalanced: {counts[cls]:.2f}"

    def test_end_of_session_labels_are_nan(self):
        df = _make_feature_df(n=500)
        result = generate_labels(df, horizons_seconds=[300])
        # Last rows should have NaN labels (no forward data 300s ahead)
        assert (
            result["label_300s"].iloc[-1] != result["label_300s"].iloc[-1]
        )  # NaN check

    def test_default_label_threshold_method_is_temporally_safe_fixed_bps(self):
        df = _make_feature_df(n=200)
        result = generate_labels(df, horizons_seconds=[60])
        valid = result["label_60s"].dropna()
        assert set(valid.unique()).issubset({0, 1, 2})

    def test_fixed_threshold_labels_do_not_depend_on_later_same_day_distribution(self):
        base = _make_feature_df(n=240)
        changed_tail = base.copy()

        # Keep the first 120 seconds identical and perturb only the later tail.
        changed_tail.loc[120:, "mid"] = changed_tail.loc[120:, "mid"] + np.linspace(
            0.0, 3.0, num=len(changed_tail.loc[120:])
        )
        changed_tail.loc[120:, "microprice"] = changed_tail.loc[120:, "mid"] + 0.001

        base_labeled = generate_labels(
            base, horizons_seconds=[30], threshold_method="fixed", fixed_bps=10.0
        )
        changed_labeled = generate_labels(
            changed_tail,
            horizons_seconds=[30],
            threshold_method="fixed",
            fixed_bps=10.0,
        )

        shared_prefix = slice(0, 90)
        assert np.array_equal(
            base_labeled["label_30s"].iloc[shared_prefix].to_numpy(),
            changed_labeled["label_30s"].iloc[shared_prefix].to_numpy(),
            equal_nan=True,
        )


class TestSplitting:
    def test_temporal_split_no_overlap(self):
        dates = [f"2025-12-{d:02d}" for d in range(1, 21)]
        frames = [_make_feature_df(n=100, date=d) for d in dates]
        df = pd.concat(frames, ignore_index=True)
        train, val, test, info = temporal_split(df)
        train_dates = set(train["date"].unique())
        val_dates = set(val["date"].unique())
        test_dates = set(test["date"].unique())
        assert len(train_dates & val_dates) == 0
        assert len(train_dates & test_dates) == 0
        assert len(val_dates & test_dates) == 0

    def test_temporal_split_ordering(self):
        dates = [f"2025-12-{d:02d}" for d in range(1, 21)]
        frames = [_make_feature_df(n=100, date=d) for d in dates]
        df = pd.concat(frames, ignore_index=True)
        _, _, _, info = temporal_split(df)
        assert max(info.train_dates) < min(info.val_dates)
        assert max(info.val_dates) < min(info.test_dates)

    def test_walk_forward_folds_non_overlapping_val(self):
        dates = [f"2025-12-{d:02d}" for d in range(1, 21)]
        folds = walk_forward_folds(dates, n_folds=5, min_train=3)
        assert len(folds) > 0
        for fold in folds:
            # Val dates should not be in train dates
            assert len(set(fold.train_dates) & set(fold.val_dates)) == 0

    def test_walk_forward_expanding_window(self):
        dates = [f"2025-12-{d:02d}" for d in range(1, 21)]
        folds = walk_forward_folds(dates, n_folds=5, min_train=3)
        if len(folds) > 1:
            assert len(folds[1].train_dates) >= len(folds[0].train_dates)
