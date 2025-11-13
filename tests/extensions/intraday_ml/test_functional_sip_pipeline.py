"""End-to-end functionality test for SIP filtering and LightGBM training."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from pandas.testing import assert_index_equal

from extensions.intraday_ml.sip_membership import (
    get_phase_symbols_with_sip,
    save_sip_membership,
)
from extensions.intraday_ml_models.train_lgbm import LightGBMTrainer


def _build_mock_dataset(symbols: list[str]) -> tuple[pd.DataFrame, pd.Series]:
    rows = []
    start_ts = datetime(2024, 1, 2, 9, 30)
    label_cycle = [-1, 0, 1, 0, 1]
    for symbol in symbols:
        for idx, label in enumerate(label_cycle):
            rows.append(
                {
                    "symbol": symbol,
                    "ts": start_ts + timedelta(minutes=idx),
                    "f__return": float(idx) / (len(label_cycle) + 1),
                    "label": label,
                }
            )

    df = pd.DataFrame(rows).set_index(["symbol", "ts"]).sort_index()
    features = df[["f__return"]]
    labels = df["label"]
    return features, labels


def test_sip_filter_and_lightgbm_pipeline(tmp_path):
    """Verify SIP membership filtering feeds a working LightGBM training flow."""

    # Step 1: build SIP membership in a temporary gold root
    mock_gold_root = tmp_path / "gold"
    membership_records = []
    for date_str in ["2024-01-02", "2024-01-03", "2024-01-04"]:
        membership_records.append({"trade_date": date_str, "symbol": "AAA", "is_sip": True})
        membership_records.append(
            {"trade_date": date_str, "symbol": "BBB", "is_sip": date_str != "2024-01-04"}
        )
        membership_records.append({"trade_date": date_str, "symbol": "CCC", "is_sip": False})
    save_sip_membership(pd.DataFrame(membership_records), mock_gold_root)

    # Step 2: run SIP filter for train/test phases
    splits_config = {
        "train": {"start": "2024-01-02", "end": "2024-01-03"},
        "oos": {"start": "2024-01-04", "end": "2024-01-04"},
    }
    sip_config = {
        "enabled": True,
        "mode": "sip_only",
        "membership_path": str(mock_gold_root),
    }
    candidate_symbols = ["AAA", "BBB", "CCC"]

    train_symbols = get_phase_symbols_with_sip(
        splits_config=splits_config,
        sip_config=sip_config,
        candidate_symbols=candidate_symbols,
        phase="train",
        verbose=False,
    )
    oos_symbols = get_phase_symbols_with_sip(
        splits_config=splits_config,
        sip_config=sip_config,
        candidate_symbols=candidate_symbols,
        phase="oos",
        verbose=False,
    )

    assert train_symbols == ["AAA", "BBB"]
    # Only AAA qualifies on the third day, so OOS should be limited to that symbol
    assert oos_symbols == ["AAA"]

    # Step 3: train a LightGBM model on mock data for the SIP symbols
    features, labels = _build_mock_dataset(train_symbols)
    model_config = {
        "lgbm_params": {
            "objective": "multiclass",
            "num_class": 3,
            "n_estimators": 15,
            "learning_rate": 0.2,
            "random_state": 7,
            "verbose": -1,
        },
        "training": {"validation_split": 0.4, "early_stopping_rounds": 5},
        "calibration": {"enabled": False},
    }
    trainer = LightGBMTrainer(model_config)
    result = trainer.train_model(
        features=features,
        labels=labels,
        features_hash="unit-test-features",
        targets_hash="unit-test-targets",
    )

    assert result.metrics
    assert "accuracy" in result.metrics

    # Step 4: ensure predictions align with the SIP-filtered OOS symbols
    oos_features, _ = _build_mock_dataset(oos_symbols)
    assert_index_equal(
        oos_features.index.get_level_values(0).unique(),
        pd.Index(oos_symbols),
        check_names=False,
    )
    preds = result.model.predict_proba(oos_features)
    assert preds.shape[0] == len(oos_features)
    assert preds.shape[1] == 3
