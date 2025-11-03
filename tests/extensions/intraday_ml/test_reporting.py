"""Unit tests for intraday ML reporting helpers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from extensions.intraday_ml.reporting import build_run_summary, write_run_summary


def test_build_and_write_run_summary(tmp_path: Path):
    metrics = {"total_trades": 2, "win_rate": 0.5}
    orders = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-08-01", periods=3, freq="h", tz="UTC"),
            "reason": ["trade", "conviction_decay", "trade"],
            "side": ["long", "long", "short"],
        }
    )
    rejections = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-08-01", periods=2, freq="h", tz="UTC"),
            "reason": ["cooldown", "gap_insufficient"],
        }
    )

    summary = build_run_summary(
        metrics=metrics,
        orders_df=orders,
        rejections_df=rejections,
        policy_config={"order_qty": 100, "prob_threshold_long": 0.6, "prob_threshold_short": 0.6},
        artifacts_dir=tmp_path,
        feature_coverage_path=None,
        timestamp=pd.Timestamp("2024-08-02T00:00:00Z").to_pydatetime(),
    )

    assert summary["orders"]["total"] == 3
    assert summary["orders"]["entry_side_counts"]["long"] == 1
    assert summary["rejections"]["total"] == 2

    output_path = tmp_path / "summary.json"
    write_run_summary(summary, output_path)
    assert output_path.exists()
    written = output_path.read_text()
    assert "total_trades" in written
