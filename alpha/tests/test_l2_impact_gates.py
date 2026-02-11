from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml
from research.l2_impact import pipeline
from research.l2_impact.pipeline import (
    EventDefinition,
    L2Group,
    compute_effect_table,
    compute_events,
    fetch_polygon_ohlcv,
    generate_placebo_indicator,
    infer_l2_columns,
    load_l2_seconds,
    run_experiment,
)


def _base_config(
    session_start: str = "09:30:00", session_end: str = "09:30:05"
) -> dict:
    return {
        "seed": 7,
        "baseline_window_minutes": 1,
        "baseline_min_periods": 2,
        "cooldown_seconds": 0,
        "forward_minutes": 1,
        "pre_minutes": 1,
        "session_start": session_start,
        "session_end": session_end,
        "exclude_first_minutes": 0,
        "exclude_last_minutes": 0,
        "deep_level_min": 1,
        "deep_level_max": 2,
        "near_level_max": 1,
        "min_events_target": 1,
        "bootstrap_reps": 10,
        "thresholds": [0.9],
        "fallback_threshold": 0.8,
        "use_robust_z": False,
        "robust_z_threshold": 3.0,
        "polygon": {"adjusted": True, "limit": 50000},
        "definitions": {
            "def_a": {
                "name": "Definition A",
                "percentile": 0.9,
                "persistence_seconds": 1,
            },
            "def_b": {
                "name": "Definition B",
                "percentile_ratio": 0.9,
                "percentile_deep": 0.9,
                "persistence_seconds": 1,
            },
        },
        "controls": {"use_volume_30m": False, "use_hl_range": False},
    }


def _write_config(path: Path, config: dict) -> None:
    path.write_text(yaml.safe_dump(config), encoding="utf-8")


def _write_l2_parquet(root: Path, date: str, symbol: str, tz: str) -> Path:
    data_dir = root / f"date={date}" / f"symbol={symbol}"
    data_dir.mkdir(parents=True, exist_ok=True)
    session_times = pd.date_range(f"{date} 09:30:00", periods=5, freq="1s", tz=tz)
    ts_utc = session_times.tz_convert("UTC")
    df = pd.DataFrame(
        {
            "ts_utc": ts_utc,
            "bid_sz_1": [10.0] * len(ts_utc),
            "bid_sz_2": [8.0] * len(ts_utc),
            "ask_sz_1": [9.0] * len(ts_utc),
            "ask_sz_2": [7.0] * len(ts_utc),
        }
    )
    file_path = data_dir / "part-000.parquet"
    df.to_parquet(file_path, index=False)
    return file_path


def _make_panel(seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for symbol in ("AAA", "BBB"):
        for date in ("2026-01-02", "2026-01-03"):
            for minute in range(20):
                rows.append(
                    {
                        "symbol": symbol,
                        "date": date,
                        "time_bucket": minute // 5,
                        "event_def_a": int(rng.random() < 0.2),
                        "ret_300s": rng.normal(0, 0.01),
                        "vol_30m": rng.uniform(0.1, 0.2),
                        "volume_30m": rng.uniform(100, 200),
                        "hl_range": rng.uniform(0.1, 0.2),
                    }
                )
    return pd.DataFrame(rows)


def test_infer_l2_columns_requires_timestamp() -> None:
    with pytest.raises(RuntimeError, match="timestamp column"):
        infer_l2_columns(["bid_sz_1", "ask_sz_1"])


def test_infer_l2_columns_requires_bid_ask() -> None:
    with pytest.raises(RuntimeError, match="bid/ask size columns"):
        infer_l2_columns(["ts_utc", "bid_sz_1"])


def test_fetch_polygon_cached_schema_validation(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    date = "2026-01-02"
    symbol = "AAPL"
    cache_path = cache_dir / f"{symbol}_{date}.parquet"
    df = pd.DataFrame(
        {
            "ts_minute": [pd.Timestamp("2026-01-02 09:30:00")],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
        }
    )
    df.to_parquet(cache_path, index=False)

    config = _base_config()
    with pytest.raises(RuntimeError, match="Cached OHLCV missing columns"):
        fetch_polygon_ohlcv(symbol, date, "America/New_York", config, cache_dir)


def test_fetch_polygon_cached_localizes_timezone(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    date = "2026-01-02"
    symbol = "AAPL"
    cache_path = cache_dir / f"{symbol}_{date}.parquet"
    df = pd.DataFrame(
        {
            "ts_minute": [pd.Timestamp("2026-01-02 09:30:00")],
            "open": [1.0],
            "high": [1.0],
            "low": [1.0],
            "close": [1.0],
            "volume": [100.0],
        }
    )
    df.to_parquet(cache_path, index=False)

    config = _base_config()
    ohlcv = fetch_polygon_ohlcv(symbol, date, "America/New_York", config, cache_dir)
    assert str(ohlcv["ts_minute"].dt.tz) == "America/New_York"


def test_load_l2_seconds_timezone_consistency(tmp_path: Path) -> None:
    tz = "America/New_York"
    l2_root = tmp_path / "l2"
    file_path = _write_l2_parquet(l2_root, "2026-01-02", "TEST", tz)
    group = L2Group(date="2026-01-02", symbol="TEST", files=(file_path,))
    config = _base_config(session_end="09:30:04")

    seconds_df, _ = load_l2_seconds(group, config, tz)
    assert str(seconds_df.index.tz) == tz
    assert seconds_df.index[0] == pd.Timestamp("2026-01-02 09:30:00", tz=tz)
    assert seconds_df.index[-1] == pd.Timestamp("2026-01-02 09:30:04", tz=tz)


def test_no_lookahead_baseline_window() -> None:
    tz = "America/New_York"
    index = pd.date_range("2026-01-02 09:30:00", periods=10, freq="1s", tz=tz)
    seconds_df = pd.DataFrame({"deep_total": 1.0, "ratio": 1.0}, index=index)
    config = {
        "baseline_window_minutes": 1,
        "baseline_min_periods": 2,
        "cooldown_seconds": 0,
        "session_start": "09:30:00",
        "session_end": "09:30:09",
        "exclude_first_minutes": 0,
        "exclude_last_minutes": 0,
        "use_robust_z": False,
        "robust_z_threshold": 3.0,
    }
    definition = EventDefinition(
        key="def_a",
        name="Definition A",
        percentile=0.99,
        persistence_seconds=1,
    )
    group = L2Group(date="2026-01-02", symbol="AAA", files=tuple())

    base_events = compute_events(
        seconds_df, group, config, [definition], threshold=0.99
    )
    cutoff = index[4]
    base_before = [event.event_ts for event in base_events if event.event_ts <= cutoff]
    assert base_before

    mutated = seconds_df.copy()
    mutated.loc[index[5] :, "deep_total"] = 100.0
    mutated_events = compute_events(
        mutated, group, config, [definition], threshold=0.99
    )
    mutated_before = [
        event.event_ts for event in mutated_events if event.event_ts <= cutoff
    ]
    assert base_before == mutated_before


def test_placebo_indicator_near_zero_effect() -> None:
    panel = _make_panel(seed=1)
    rng = np.random.default_rng(123)
    panel["placebo_def_a"] = generate_placebo_indicator(panel, "event_def_a", rng)
    panel["ret_300s"] = 0.0

    result = compute_effect_table(
        panel=panel,
        definition="def_a",
        event_col="placebo_def_a",
        outcome_col="ret_300s",
        rng=np.random.default_rng(321),
        bootstrap_reps=20,
        include_symbol_fe=True,
        include_bucket_fe=True,
        controls=["vol_30m"],
    )
    coef = float(result.loc[0, "coef_event"])
    assert abs(coef) < 1e-9


def test_determinism_same_seed_same_result() -> None:
    panel = _make_panel(seed=2)

    result_a = compute_effect_table(
        panel=panel,
        definition="def_a",
        event_col="event_def_a",
        outcome_col="ret_300s",
        rng=np.random.default_rng(999),
        bootstrap_reps=50,
        include_symbol_fe=True,
        include_bucket_fe=True,
        controls=["vol_30m"],
    )
    result_b = compute_effect_table(
        panel=panel,
        definition="def_a",
        event_col="event_def_a",
        outcome_col="ret_300s",
        rng=np.random.default_rng(999),
        bootstrap_reps=50,
        include_symbol_fe=True,
        include_bucket_fe=True,
        controls=["vol_30m"],
    )

    pd.testing.assert_frame_equal(result_a, result_b, atol=0.0, rtol=0.0)


def test_run_experiment_emits_required_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tz = "America/New_York"
    l2_root = tmp_path / "l2"
    _write_l2_parquet(l2_root, "2026-01-02", "TEST", tz)

    config = _base_config(session_end="09:30:02")
    config_path = tmp_path / "config.yaml"
    _write_config(config_path, config)

    def fake_fetch(
        symbol: str,
        date: str,
        tz: str,
        config: dict,
        cache_dir: Path,
    ) -> pd.DataFrame:
        session_start = pd.Timestamp(f"{date} {config['session_start']}", tz=tz)
        minutes = pd.date_range(session_start, periods=3, freq="1min", tz=tz)
        return pd.DataFrame(
            {
                "ts_minute": minutes,
                "open": [100.0, 100.5, 101.0],
                "high": [101.0, 101.5, 102.0],
                "low": [99.0, 100.0, 100.5],
                "close": [100.2, 100.7, 101.2],
                "volume": [1000.0, 1100.0, 1200.0],
            }
        )

    monkeypatch.setattr(pipeline, "fetch_polygon_ohlcv", fake_fetch)

    output_root = tmp_path / "reports"
    output_dir = output_root / "test_run"

    run_experiment(
        l2_root=l2_root,
        ohlcv_source="polygon",
        tz=tz,
        run_id="test_run",
        output_dir=output_dir,
        placebo=False,
        falsification=None,
        start_date=None,
        end_date=None,
        symbols=None,
        config_path=config_path,
    )

    required = [
        output_root / "l2_deep_liquidity_300s_summary.md",
        output_root / "l2_deep_liquidity_300s_results.csv",
        output_root / "l2_deep_liquidity_300s_placebo.csv",
        output_root / "l2_deep_liquidity_300s_falsification.csv",
        output_root / "l2_deep_liquidity_300s_metadata.json",
    ]

    for path in required:
        assert path.exists(), f"Missing artifact: {path}"
