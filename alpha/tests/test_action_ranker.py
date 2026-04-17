from __future__ import annotations

import pandas as pd
import pytest

from src.models.action_ranker import (
    ActionEdgeRegressor,
    ActionQualityLogisticModel,
    ActionRankerLogistic,
    ActionRankerXGBoost,
    action_edge_sample_weights,
    build_action_quality_features,
    build_action_specs,
    derive_action_targets,
    get_action_ranker_feature_columns,
)


def test_build_action_specs_orders_long_then_short():
    specs = build_action_specs([3, 5])
    assert [spec.key for spec in specs] == [
        "long_3m",
        "long_5m",
        "short_3m",
        "short_5m",
    ]


def test_derive_action_targets_marks_long_and_short_profitability():
    df = pd.DataFrame(
        {
            "mid": [100.0, 100.0],
            "spread": [0.02, 0.02],
            "session_bucket": [1.0, 1.0],
            "source_type": ["features", "features"],
            "ret_fwd_180s": [0.0020, -0.0020],
        }
    )
    derived, specs = derive_action_targets(
        df,
        hold_minutes=[3],
        base_edge_bps=5.0,
        spread_weight=0.0,
        open_penalty_bps=0.0,
        raw_penalty_bps=0.0,
        positive_edge_buffer_bps=0.0,
    )
    assert [spec.key for spec in specs] == ["long_3m", "short_3m"]
    assert int(derived.loc[0, "target_long_3m"]) == 1
    assert int(derived.loc[1, "target_short_3m"]) == 1


def test_derive_action_targets_positive_buffer_filters_marginal_edges():
    df = pd.DataFrame(
        {
            "mid": [100.0],
            "spread": [0.02],
            "session_bucket": [1.0],
            "source_type": ["features"],
            "ret_fwd_180s": [0.0007],
        }
    )
    derived, _ = derive_action_targets(
        df,
        hold_minutes=[3],
        base_edge_bps=5.0,
        spread_weight=0.0,
        open_penalty_bps=0.0,
        raw_penalty_bps=0.0,
        positive_edge_buffer_bps=3.0,
    )
    assert int(derived.loc[0, "target_long_3m"]) == 0
    assert derived.loc[0, "best_action_edge_bps"] > 0.0


def test_action_edge_sample_weights_increase_for_clearer_edges():
    df = pd.DataFrame({"best_action_edge_bps": [1.0, 10.0, 30.0]})
    weights = action_edge_sample_weights(df, scale_bps=10.0, max_multiplier=3.0)
    assert weights[0] < weights[1] < weights[2]
    assert weights[2] <= 3.0


def test_action_ranker_logistic_scores_all_actions():
    df = pd.DataFrame(
        {
            "f1": [0.0, 1.0, 0.0, 1.0],
            "f2": [1.0, 0.0, 1.0, 0.0],
            "target_long_3m": [1, 0, 1, 0],
            "target_short_3m": [0, 1, 0, 1],
        }
    )
    model = ActionRankerLogistic(
        feature_columns=["f1", "f2"],
        action_specs=build_action_specs([3]),
    )
    model.fit(df)
    scores = model.predict_action_scores(df[["f1", "f2"]].to_numpy())
    assert scores.shape == (4, 2)


def test_action_ranker_xgboost_scores_all_actions():
    df = pd.DataFrame(
        {
            "f1": [0.0, 1.0, 0.0, 1.0],
            "f2": [1.0, 0.0, 1.0, 0.0],
            "target_long_3m": [1, 0, 1, 0],
            "target_short_3m": [0, 1, 0, 1],
        }
    )
    model = ActionRankerXGBoost(
        feature_columns=["f1", "f2"],
        action_specs=build_action_specs([3]),
        max_depth=2,
        n_estimators=8,
        learning_rate=0.3,
        min_child_weight=0.0,
    )
    model.fit(df)
    scores = model.predict_action_scores(df[["f1", "f2"]].to_numpy())
    assert scores.shape == (4, 2)
    assert scores[0, 0] > scores[0, 1]
    assert scores[1, 1] > scores[1, 0]


def test_action_ranker_xgboost_handles_single_class_action_with_constant_fallback():
    df = pd.DataFrame(
        {
            "f1": [0.0, 1.0, 0.0, 1.0],
            "f2": [1.0, 0.0, 1.0, 0.0],
            "target_long_3m": [1, 1, 1, 1],
            "target_short_3m": [0, 1, 0, 1],
        }
    )
    model = ActionRankerXGBoost(
        feature_columns=["f1", "f2"],
        action_specs=build_action_specs([3]),
        max_depth=2,
        n_estimators=8,
        learning_rate=0.3,
        min_child_weight=0.0,
    )

    model.fit(df)
    scores = model.predict_action_scores(df[["f1", "f2"]].to_numpy())

    assert scores.shape == (4, 2)
    assert (scores[:, 0] > 0.99).all()


def test_action_quality_features_build_side_session_and_hold_columns():
    df = pd.DataFrame(
        {
            "rank_score": [0.9, 0.2],
            "side": ["long", "short"],
            "hold_minutes": [3, 5],
            "pressure_k": [1.0, -1.0],
            "spread": [0.02, 0.03],
            "depth_imb_k": [0.1, -0.2],
            "session_bucket": [0.0, 2.0],
            "dist_vwap_bps": [12.0, -8.0],
            "volume_rel_20": [1.4, 0.8],
            "rsi": [62.0, 38.0],
            "ret_3": [0.0015, -0.0010],
            "ret_10": [0.0030, -0.0020],
        }
    )

    features, cols = build_action_quality_features(df, hold_minutes=[3, 5])

    assert "rank_score" in cols
    assert "side_is_long" in cols
    assert "session_is_0" in cols
    assert "hold_is_5m" in cols
    assert "dist_vwap_bps" in cols
    assert "volume_rel_20" in cols
    assert "rsi" in cols
    assert "ret_10" in cols
    assert float(features.loc[0, "side_is_long"]) == 1.0
    assert float(features.loc[1, "side_is_short"]) == 1.0
    assert float(features.loc[0, "session_is_0"]) == 1.0
    assert float(features.loc[1, "hold_is_5m"]) == 1.0
    assert float(features.loc[0, "dist_vwap_bps"]) == 12.0
    assert float(features.loc[1, "ret_3"]) == pytest.approx(-0.001)


def test_action_quality_logistic_scores_acceptance_probability():
    df = pd.DataFrame(
        {
            "rank_score": [0.9, 0.8, 0.2, 0.1],
            "side": ["long", "long", "short", "short"],
            "hold_minutes": [3, 3, 5, 5],
            "pressure_k": [1.2, 0.9, -0.8, -1.0],
            "spread": [0.02, 0.02, 0.05, 0.06],
            "depth_imb_k": [0.2, 0.1, -0.3, -0.4],
            "session_bucket": [1.0, 1.0, 2.0, 2.0],
            "quality_target": [1, 1, 0, 0],
        }
    )
    features, cols = build_action_quality_features(df, hold_minutes=[3, 5])

    model = ActionQualityLogisticModel(feature_columns=cols)
    model.fit(features, target_column="quality_target")
    probs = model.predict_acceptance_proba(features[cols].to_numpy())

    assert probs.shape == (4,)
    assert probs[0] > probs[2]
    assert probs[1] > probs[3]


def test_action_edge_regressor_scores_all_actions():
    df = pd.DataFrame(
        {
            "f1": [0.0, 1.0, 0.0, 1.0],
            "f2": [1.0, 0.0, 1.0, 0.0],
            "edge_long_3m_bps": [10.0, -5.0, 11.0, -4.0],
            "edge_short_3m_bps": [-8.0, 7.0, -7.5, 8.0],
        }
    )
    model = ActionEdgeRegressor(
        feature_columns=["f1", "f2"],
        action_specs=build_action_specs([3]),
    )
    model.fit(df)
    scores = model.predict_action_scores(df[["f1", "f2"]].to_numpy())
    assert scores.shape == (4, 2)
    assert scores[0, 0] > scores[0, 1]
    assert scores[1, 1] > scores[1, 0]


def test_action_ranker_feature_columns_exclude_derived_targets():
    df = pd.DataFrame(
        {
            "mid": [100.0],
            "spread": [0.02],
            "ret_fwd_180s": [0.001],
            "target_long_3m": [1.0],
            "edge_long_3m_bps": [5.0],
            "best_action_edge_bps": [5.0],
            "best_action_positive": [1.0],
            "micro_off": [0.01],
        }
    )
    cols = get_action_ranker_feature_columns(df)
    assert "mid" in cols
    assert "micro_off" in cols
    assert "ret_fwd_180s" not in cols
    assert "target_long_3m" not in cols
    assert "edge_long_3m_bps" not in cols
    assert "best_action_edge_bps" not in cols
    assert "best_action_positive" not in cols


def test_action_ranker_feature_profiles_reduce_metadata_and_allow_causal_subset():
    df = pd.DataFrame(
        {
            "mid": [100.0],
            "spread": [0.02],
            "pressure_k": [0.1],
            "session_progress": [0.5],
            "source_is_raw": [0.0],
            "dist_vwap_bps": [12.0],
            "ret_3": [0.001],
            "ts_epoch": [1_700_000_000.0],
            "smart_depth": [0.0],
            "has_depth": [1.0],
            "best_action_edge_bps": [5.0],
        }
    )

    stable = get_action_ranker_feature_columns(df, profile="stable")
    stable_causal = get_action_ranker_feature_columns(df, profile="stable_causal")

    assert "mid" in stable
    assert "pressure_k" in stable
    assert "session_progress" in stable
    assert "dist_vwap_bps" not in stable
    assert "ret_3" not in stable
    assert "ts_epoch" not in stable
    assert "smart_depth" not in stable
    assert "has_depth" not in stable

    assert "dist_vwap_bps" in stable_causal
    assert "ret_3" in stable_causal
