from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from extensions.intraday_ml.eval.dataset_instrumentation import DatasetInstrumentor
from extensions.intraday_ml.sip_membership import save_sip_membership


def _build_sample_dataset() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["AAPL", "AAPL", "AAPL"],
            "ts": pd.to_datetime(
                [
                    "2024-01-02 09:35:00",
                    "2024-01-02 10:00:00",
                    "2024-01-03 09:50:00",
                ]
            ),
            "open": [10.0, 10.5, 11.0],
            "high": [10.2, 10.7, 11.5],
            "low": [9.9, 10.4, 10.8],
            "close": [10.1, 10.6, 11.2],
            "volume": [1_000, 1_200, 1_500],
            "label": [1, 0, -1],
        }
    )


def _make_sip_config(tmp_gold_root: Path) -> dict[str, Any]:
    sample_sip = pd.DataFrame(
        {
            "trade_date": ["2024-01-02", "2024-01-03", "2024-01-03"],
            "symbol": ["AAPL", "AAPL", "MSFT"],
            "is_sip": [True, True, False],
        }
    )
    save_sip_membership(sample_sip, tmp_gold_root)
    return {
        "enabled": True,
        "mode": "sip_only",
        "membership_path": str(tmp_gold_root),
    }


def test_instrument_split_emits_label_distributions(tmp_path: Path) -> None:
    splits = {"train": {"start": "2024-01-02", "end": "2024-01-03"}}
    sip_config = _make_sip_config(tmp_path / "gold")
    fake_dataset = _build_sample_dataset()

    calls: list[dict[str, Any]] = []

    def fake_builder(**kwargs: Any) -> pd.DataFrame:
        calls.append(kwargs)
        return fake_dataset.copy()

    instrumentor = DatasetInstrumentor(
        splits_config=splits,
        sip_config=sip_config,
        features_config={"dummy": True},
        targets_config={"dummy": True},
        data_loader_config={"root": "gold"},
        artifact_dir=tmp_path / "artifacts",
        dataset_builder=fake_builder,
    )

    result = instrumentor.instrument_split("train", ["AAPL", "MSFT"])

    assert calls, "dataset builder should be invoked"
    assert calls[0]["symbols"] == ["AAPL"]
    assert result.rows == len(fake_dataset)
    assert result.symbols == ["AAPL"]
    assert result.label_counts == {1: 1, 0: 1, -1: 1}

    assert result.dataset_path is not None and result.dataset_path.exists()
    loaded = pd.read_parquet(result.dataset_path)
    pd.testing.assert_frame_equal(loaded.reset_index(drop=True), fake_dataset)

    assert result.daily_distribution_path is not None
    daily = pd.read_csv(result.daily_distribution_path)
    assert set(daily.columns) == {"trade_date", "label_-1", "label_0", "label_1"}
    assert daily.loc[daily["trade_date"] == "2024-01-02", "label_1"].iloc[0] == 1
    assert daily.loc[daily["trade_date"] == "2024-01-02", "label_0"].iloc[0] == 1

    assert result.symbol_distribution_path is not None
    per_symbol = pd.read_csv(result.symbol_distribution_path)
    assert set(per_symbol["symbol"]) == {"AAPL"}
    assert per_symbol["label_-1"].sum() == 1


def test_instrument_split_handles_missing_symbols(tmp_path: Path) -> None:
    splits = {"train": {"start": "2024-01-02", "end": "2024-01-03"}}
    sip_config = _make_sip_config(tmp_path / "gold")
    fake_dataset = _build_sample_dataset()

    calls: list[dict[str, Any]] = []

    def fake_builder(**kwargs: Any) -> pd.DataFrame:
        calls.append(kwargs)
        return fake_dataset.copy()

    instrumentor = DatasetInstrumentor(
        splits_config=splits,
        sip_config=sip_config,
        features_config={"dummy": True},
        targets_config={"dummy": True},
        data_loader_config={"root": "gold"},
        artifact_dir=tmp_path / "artifacts",
        dataset_builder=fake_builder,
    )

    result = instrumentor.instrument_split("train", ["MSFT"])

    assert not calls, "dataset builder should not be called when SIP filters everything out"
    assert result.rows == 0
    assert result.dataset_path is None
    assert result.daily_distribution_path is None
    assert result.symbol_distribution_path is None
