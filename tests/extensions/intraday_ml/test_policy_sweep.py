import pandas as pd

from extensions.intraday_ml.experiments.policy_sweep import (
    expand_parameter_grid,
    sweep_policy_configs,
)
from extensions.intraday_ml.policy.rejection_reasons import (
    REJECT_REASON_PROB_LONG,
    REJECT_REASON_RISK_BUDGET,
    REJECTION_REASON_TO_COLUMN,
)


def _ts(idx: int) -> pd.Timestamp:
    return (
        pd.Timestamp(f"2025-01-02 09:{30 + idx:02d}:00", tz="America/New_York")
        .tz_convert("UTC")
    )


def _sample_policy_config() -> dict:
    return {
        "prob_threshold_long": 0.55,
        "prob_threshold_short": 0.55,
        "cooldown_minutes": 0,
        "min_time": "09:30:00",
        "max_time": "16:00:00",
        "order_qty": 1,
        "session_timezone": "America/New_York",
        "risk": {
            "atr_feature": "atr",
            "support_feature_long": "low",
            "resistance_feature_short": "high",
            "max_atr_multiple": 1.0,
            "support_buffer_atr": 0.0,
            "target_r_multiple": 1.5,
            "min_stop_pct": 0.001,
            "max_stop_pct": 0.05,
            "min_expected_r": 1.0,
        },
    }


def _sample_signals() -> pd.DataFrame:
    base = {"close": 100.0, "low": 99.5, "high": 100.5, "atr": 0.5}
    rows = []
    for idx, symbol in enumerate(["AAA", "BBB", "CCC"]):
        row = {
            "symbol": symbol,
            "ts": _ts(idx),
            "prob_long": 0.9,
            "prob_short": 0.05,
            "prob_neutral": 0.05,
        }
        row.update(base)
        rows.append(row)
    return pd.DataFrame(rows)


def _sample_bars() -> pd.DataFrame:
    rows = []
    for symbol in ["AAA", "BBB", "CCC"]:
        for idx in range(4):
            rows.append(
                {
                    "symbol": symbol,
                    "ts": _ts(idx),
                    "open": 100.0 + idx * 0.1,
                    "high": 101.0,
                    "low": 99.0,
                    "close": 100.5,
                    "volume": 1000 + idx * 10,
                }
            )
    return pd.DataFrame(rows)


def test_expand_parameter_grid_cartesian_product():
    grid = {"prob_threshold_long": [0.6, 0.65], "max_trades": [1, 2]}
    combos = expand_parameter_grid(grid)
    assert len(combos) == 4
    assert combos[0]["prob_threshold_long"] == 0.6
    assert combos[-1]["max_trades"] == 2


def test_policy_sweep_returns_metrics():
    signals = _sample_signals()
    bars = _sample_bars()
    config = _sample_policy_config()
    grid = {"prob_threshold_long": [0.5, 0.65]}
    results = sweep_policy_configs(
        signals,
        bars,
        base_policy_config=config,
        grid=grid,
        backtest_config={"intraday_constraints": {"session_timezone": "America/New_York"}},
    )
    assert len(results) == 2
    assert set(results["entries"]) == {3}
    assert "param_prob_threshold_long" in results.columns
    assert "rejection_counts" in results.columns
    for column in REJECTION_REASON_TO_COLUMN.values():
        assert column in results.columns
        assert (results[column] >= 0).all()


def test_policy_sweep_records_rejection_counts(monkeypatch):
    class StubPolicy:
        def __init__(self, config):
            self.config = config

        def process_signals(self, signals):
            orders = pd.DataFrame([{"reason": "trade"}])
            rejections = pd.DataFrame([{"reason": "prob"}] * 3)
            return orders, rejections

        def get_rejection_reason_counts(self):
            return {
                REJECT_REASON_PROB_LONG: 2,
                REJECT_REASON_RISK_BUDGET: 1,
            }

    def fake_backtest(bars, orders, cfg=None):
        trades = pd.DataFrame([{"r_multiple": 1.0}])
        return {"trades": trades, "metrics": {"pnl": 1.0}}

    monkeypatch.setattr(
        "extensions.intraday_ml.experiments.policy_sweep.IntradayMLDecisionPolicy",
        StubPolicy,
    )
    monkeypatch.setattr(
        "extensions.intraday_ml.experiments.policy_sweep.intraday_ml_run_backtest",
        fake_backtest,
    )

    signals = _sample_signals()
    bars = _sample_bars()
    config = _sample_policy_config()
    results = sweep_policy_configs(
        signals,
        bars,
        base_policy_config=config,
        grid={"prob_threshold_long": [0.5]},
        backtest_config={},
    )
    assert len(results) == 1
    row = results.iloc[0]
    assert row["rejection_counts"][REJECT_REASON_PROB_LONG] == 2
    assert row["rejection_counts"][REJECT_REASON_RISK_BUDGET] == 1
    assert row["reject_probability"] == 2
    assert row["reject_risk_budget"] == 1
    for column in REJECTION_REASON_TO_COLUMN.values():
        assert column in results.columns
        assert row[column] >= 0
