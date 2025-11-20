import pandas as pd
import pytest

from extensions.intraday_ml.policy.bigmove_policy_adapter import BigMovePolicyAdapter


def test_adapter_generates_unconditional_probabilities():
    adapter = BigMovePolicyAdapter(
        {
            "probability_threshold": 0.5,
            "prob_column": "prob_bigmove",
            "long_prob_column": "prob_bigmove_long",
            "short_prob_column": "prob_bigmove_short",
            "expected_r_column": "expected_r_bigmove",
            "min_expected_r": 1.2,
        }
    )
    df = pd.DataFrame(
        {
            "prob_bigmove": [0.6],
            "prob_bigmove_long": [0.7],
            "prob_bigmove_short": [0.3],
            "expected_r_bigmove": [2.1],
        }
    )

    transformed = adapter.transform(df)

    assert transformed.loc[0, "_bigmove_allowed"]
    assert transformed.loc[0, "prob_long"] == pytest.approx(0.42, rel=1e-9)
    assert transformed.loc[0, "prob_short"] == pytest.approx(0.18, rel=1e-9)
    assert transformed.loc[0, "prob_neutral"] == pytest.approx(0.4, rel=1e-9)
    assert transformed.loc[0, "_bigmove_expected_r"] == pytest.approx(2.1, rel=1e-9)


def test_adapter_requires_probability_columns():
    adapter = BigMovePolicyAdapter()
    df = pd.DataFrame({"prob_bigmove": [0.5]})
    with pytest.raises(KeyError):
        adapter.transform(df)
