import pandas as pd
import pytest

from extensions.intraday_ml.labeling.big_move_labels import (
    BigMoveLabelResult,
    compute_big_move_labels,
)


def _base_targets_cfg(**overrides) -> dict:
    cfg = {
        "big_move": {
            "label_name": "y_bigmove",
            "direction_label_name": "y_bigmove_direction",
            "forward_return_column": "fwd_return_bigmove",
            "atr_column": "atr",
            "price_column": "close",
            "bar_minutes": 10,
            "forward_minutes": 20,
            "atr_multiple": 1.0,
            "min_return_floor_pct": 0.004,
            "atr_is_return_pct": True,
        }
    }
    cfg["big_move"].update(overrides)
    return cfg


def test_big_move_labels_flag_large_forward_move():
    timestamps = pd.date_range("2025-01-02 09:30:00", periods=5, freq="10T", tz="UTC")
    data = pd.DataFrame(
        {
            "symbol": ["AAA"] * 5,
            "ts": timestamps,
            "close": [100.0, 100.2, 101.0, 101.4, 101.5],
            "atr": [0.005] * 5,
        }
    )
    result = compute_big_move_labels(data, _base_targets_cfg())

    assert isinstance(result, BigMoveLabelResult)
    assert result.labels.name == "y_bigmove"
    assert result.directions.name == "y_bigmove_direction"

    # First row should flag a big move (1% move vs 0.5% ATR threshold).
    assert result.labels.iloc[0] == 1
    assert result.directions.iloc[0] == 1

    # Final bars lack enough look-ahead data and remain 0.
    assert result.labels.iloc[-1] == 0
    assert result.directions.iloc[-1] == 0


def test_big_move_labels_support_absolute_atr_columns():
    timestamps = pd.date_range("2025-01-02 09:30:00", periods=4, freq="10T", tz="UTC")
    data = pd.DataFrame(
        {
            "symbol": ["BBB"] * 4,
            "ts": timestamps,
            "close": [50.0, 49.0, 48.5, 48.0],
            "atr_abs": [0.4, 0.4, 0.4, 0.4],
        }
    )
    cfg = _base_targets_cfg(
        atr_column="atr_abs",
        atr_is_return_pct=False,
        min_return_floor_pct=0.0,
        atr_multiple=1.0,
    )
    result = compute_big_move_labels(data, cfg)

    # First row: forward return = (48.5 / 50) - 1 = -3%, ATR=0.4/50=0.8% -> qualifies.
    assert result.labels.iloc[0] == 1
    assert result.directions.iloc[0] == -1


def test_big_move_labels_raise_for_missing_columns():
    timestamps = pd.date_range("2025-01-02 09:30:00", periods=3, freq="10T", tz="UTC")
    data = pd.DataFrame({"symbol": ["AAA"] * 3, "ts": timestamps, "close": [1.0, 1.1, 1.2]})
    with pytest.raises(KeyError):
        compute_big_move_labels(data, _base_targets_cfg())
