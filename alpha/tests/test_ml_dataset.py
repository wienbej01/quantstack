"""Tests for Sprint 1: ML Dataset Pipeline."""

import numpy as np
import pandas as pd
import pytest

from src.data.ml_dataset import (
    FEATURE_COLS,
    MLDatasetBuilder,
    RAW_REQUIRED_COLS,
    compute_features_from_raw,
    optimize_memory,
)
from src.data.ml_labels import generate_labels


def _make_raw_df(n: int = 200, symbol: str = "TEST") -> pd.DataFrame:
    """Create synthetic raw L2 data."""
    rng = np.random.RandomState(42)
    ts_start = pd.Timestamp("2025-12-19 14:30:00+00:00").timestamp()
    ts = ts_start + np.arange(n) * 0.5  # 0.5s intervals
    mid = 50.0 + np.cumsum(rng.randn(n) * 0.01)
    spread = 0.02 + rng.rand(n) * 0.02

    df = pd.DataFrame(
        {
            "ts_utc": pd.to_datetime(ts, unit="s", utc=True),
            "ts_epoch": ts,
            "date_et": "2025-12-19",
            "symbol": symbol,
            "exchange": "NYSE",
            "smart_depth": False,
            "has_depth": True,
            "l1_bid": mid - spread / 2,
            "l1_ask": mid + spread / 2,
            "l1_bid_size": rng.randint(100, 1000, n).astype(float),
            "l1_ask_size": rng.randint(100, 1000, n).astype(float),
        }
    )
    for i in range(1, 6):
        df[f"bid_px_{i}"] = mid - spread / 2 - (i - 1) * 0.01
        df[f"bid_sz_{i}"] = rng.randint(50, 500, n).astype(float)
        df[f"ask_px_{i}"] = mid + spread / 2 + (i - 1) * 0.01
        df[f"ask_sz_{i}"] = rng.randint(50, 500, n).astype(float)
    return df


class TestComputeFeaturesFromRaw:
    def test_output_has_canonical_columns(self):
        raw = _make_raw_df()
        result = compute_features_from_raw(raw)
        for col in FEATURE_COLS:
            assert col in result.columns, f"Missing column: {col}"

    def test_no_nan_in_core_features(self):
        raw = _make_raw_df()
        result = compute_features_from_raw(raw)
        for col in ["mid", "spread", "obi_1", "obi_5"]:
            assert not result[col].isna().any(), f"NaN in {col}"

    def test_obi_range(self):
        raw = _make_raw_df()
        result = compute_features_from_raw(raw)
        for lvl in (1, 2, 3, 5):
            vals = result[f"obi_{lvl}"]
            assert vals.min() >= -1.0 and vals.max() <= 1.0

    def test_spread_positive(self):
        raw = _make_raw_df()
        result = compute_features_from_raw(raw)
        assert (result["spread"] >= 0).all()

    def test_temporal_deltas_present(self):
        raw = _make_raw_df()
        result = compute_features_from_raw(raw)
        assert "d_mid_5s" in result.columns
        assert "d_obi_1_60s" in result.columns

    def test_raw_l1_sanitization_prevents_non_finite_features(self):
        raw = _make_raw_df(n=10)
        raw.loc[0, ["bid_px_1", "ask_px_1"]] = [37.06, 10.55]
        raw.loc[1, ["bid_px_1", "ask_px_1"]] = [np.nan, np.nan]
        raw.loc[1, ["l1_bid", "l1_ask"]] = [49.99, 50.01]

        result = compute_features_from_raw(raw)

        for col in [
            "mid",
            "spread",
            "microprice",
            "micro_off",
            "d_mid_15s",
            "d_spread_15s",
            "d_micro_off_15s",
        ]:
            assert np.isfinite(
                result[col]
            ).all(), f"Non-finite values remained in {col}"
        assert (result["spread"] >= 0).all()

    def test_generate_labels_handles_microsecond_datetime_resolution(self):
        ts = pd.Series(
            pd.date_range(
                "2026-03-13 14:30:00+00:00",
                periods=400,
                freq="1s",
                tz="UTC",
            ).astype("datetime64[us, UTC]")
        )
        df = pd.DataFrame(
            {
                "ts_utc": ts,
                "mid": np.linspace(100.0, 101.0, len(ts)),
            }
        )

        labeled = generate_labels(
            df, horizons_seconds=[180], threshold_method="fixed", fixed_bps=1.0
        )

        assert labeled["ret_fwd_180s"].notna().any()
        assert labeled["ret_fwd_180s"].isna().mean() < 0.6


class TestMLDatasetBuilder:
    def test_quality_report_exists_after_build(self):
        builder = MLDatasetBuilder(min_snapshots=999999)
        builder.build(dates=["1999-01-01"])  # no data
        assert isinstance(builder.quality_report, pd.DataFrame)

    def test_empty_build_returns_empty_df(self):
        builder = MLDatasetBuilder(min_snapshots=999999)
        result = builder.build(dates=["1999-01-01"])
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 0

    def test_sanitize_symbol_day_rejects_off_session_null_rows(self):
        raw = _make_raw_df(n=20)
        raw["ts_utc"] = pd.date_range(
            "2025-12-19 00:00:00+00:00", periods=len(raw), freq="500ms", tz="UTC"
        )
        raw["l1_bid"] = np.nan
        raw["l1_ask"] = np.nan
        raw["has_depth"] = False

        assert MLDatasetBuilder._sanitize_symbol_day(raw) is None


class _StubLoader:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.calls = []

    def get_available_dates(self, source_type="any"):
        return ["2025-12-19"]

    def get_available_symbols(self, date, source_type="any"):
        return ["TEST"]

    def load_snapshots(self, symbol, date, source_type=None, columns=None, **kwargs):
        self.calls.append(
            {
                "symbol": symbol,
                "date": date,
                "source_type": source_type,
                "columns": columns,
            }
        )
        if source_type == "features":
            raise FileNotFoundError("features unavailable")
        if columns is not None:
            return self.df[[c for c in columns if c in self.df.columns]].copy()
        return self.df.copy()


class _BalancedStubLoader:
    def __init__(self):
        self.calls = []
        self.data = {
            ("AAA", "2025-12-19"): _make_raw_df(symbol="AAA"),
            ("BBB", "2025-12-19"): _make_raw_df(symbol="BBB"),
            ("AAA", "2025-12-20"): _make_raw_df(symbol="AAA"),
            ("BBB", "2025-12-20"): _make_raw_df(symbol="BBB"),
        }

    def get_available_dates(self, source_type="any"):
        return ["2025-12-19", "2025-12-20"]

    def get_available_symbols(self, date, source_type="any"):
        return ["AAA", "BBB"]

    def load_snapshots(self, symbol, date, source_type=None, columns=None, **kwargs):
        self.calls.append((symbol, date, source_type))
        if source_type == "features":
            raise FileNotFoundError("features unavailable")
        df = self.data[(symbol, date)]
        if columns is not None:
            return df[[c for c in columns if c in df.columns]].copy()
        return df.copy()


class TestMemoryOptimizations:
    def test_optimize_memory_downcasts_numeric_columns(self):
        df = pd.DataFrame(
            {
                "f": np.array([1.0, 2.0], dtype=np.float64),
                "i": np.array([1, 2], dtype=np.int64),
            }
        )
        optimized = optimize_memory(df)
        assert optimized["f"].dtype == np.float32
        assert optimized["i"].dtype != np.int64

    def test_builder_requests_only_required_raw_columns(self):
        raw = _make_raw_df()
        loader = _StubLoader(raw)
        builder = MLDatasetBuilder(loader=loader, min_snapshots=10)
        frames = list(builder.iter_symbol_days())
        assert len(frames) == 1
        raw_call = next(call for call in loader.calls if call["source_type"] == "raw")
        assert raw_call["columns"] == RAW_REQUIRED_COLS

    def test_balanced_iterator_round_robins_dates(self):
        loader = _BalancedStubLoader()
        builder = MLDatasetBuilder(loader=loader, min_snapshots=10)
        frames = list(builder.iter_symbol_days(balanced_by_date=True))
        assert len(frames) == 4
        assert [frame["date"].iloc[0] for frame in frames] == [
            "2025-12-19",
            "2025-12-20",
            "2025-12-19",
            "2025-12-20",
        ]
