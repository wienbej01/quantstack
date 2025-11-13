from __future__ import annotations

import pandas as pd
import pytest

from extensions.intraday_ml.eval.prediction_loader import (
    ProbabilityColumnMap,
    infer_probability_columns,
    score_predictions,
)


def test_infer_probability_columns_defaults() -> None:
    df = pd.DataFrame(
        {
            "prob_long": [0.6, 0.2],
            "prob_short": [0.3, 0.7],
            "prob_neutral": [0.1, 0.1],
        }
    )
    mapping = infer_probability_columns(df)
    assert mapping.long == "prob_long"
    assert mapping.short == "prob_short"
    assert mapping.flat == "prob_neutral"


def test_score_predictions_adds_trade_metrics() -> None:
    df = pd.DataFrame(
        {
            "prob_long": [0.7, 0.2],
            "prob_short": [0.2, 0.6],
            "prob_neutral": [0.1, 0.2],
        }
    )
    scored = score_predictions(df)
    assert "trade_prob" in scored.columns
    assert "trade_direction" in scored.columns
    assert "trade_score" in scored.columns

    assert pytest.approx(scored.loc[0, "trade_prob"], rel=1e-6) == 0.7
    assert scored.loc[0, "trade_direction"] == 1
    assert pytest.approx(scored.loc[0, "edge_margin"], rel=1e-6) == 0.6

    assert pytest.approx(scored.loc[1, "trade_prob"], rel=1e-6) == 0.6
    assert scored.loc[1, "trade_direction"] == -1
    assert pytest.approx(scored.loc[1, "trade_score"], rel=1e-6) == 0.24


def test_score_predictions_custom_map() -> None:
    df = pd.DataFrame(
        {
            "prob_c2": [0.4],
            "prob_c0": [0.5],
            "prob_c1": [0.1],
        }
    )
    scored = score_predictions(df)
    assert pytest.approx(scored.loc[0, "trade_prob"], rel=1e-6) == 0.5
    assert scored.loc[0, "trade_direction"] == -1

    custom = score_predictions(df, ProbabilityColumnMap(long="prob_c2", short="prob_c0"))
    assert "trade_prob" in custom.columns
