#!/usr/bin/env python3
"""Run Phase 2 feature-path validation for the ML backtest regime."""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest import AlphaBacktestEngine
from src.data import GoldLoader, L2Loader
from src.data.ml_compact_cache import compute_event_score
from src.features.ml_features import compute_ml_features
from src.signals import MLSignal

from scripts.run_hypothesis_test import DEFAULT_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


FEATURES_TO_COMPARE = [
    "mid_std_300s",
    "obi_1_std_300s",
    "mid_std_60s",
    "mid_std_30s",
    "obi_1_std_60s",
    "event_score",
]
AUXILIARY_FEATURES = {"event_score"}


def _ks_statistic(a: pd.Series, b: pd.Series) -> float:
    """Compute a simple two-sample KS statistic without SciPy."""
    a_vals = np.sort(pd.to_numeric(a, errors="coerce").dropna().to_numpy(dtype=float))
    b_vals = np.sort(pd.to_numeric(b, errors="coerce").dropna().to_numpy(dtype=float))
    if len(a_vals) == 0 or len(b_vals) == 0:
        return float("nan")

    grid = np.unique(np.concatenate([a_vals, b_vals]))
    a_cdf = np.searchsorted(a_vals, grid, side="right") / len(a_vals)
    b_cdf = np.searchsorted(b_vals, grid, side="right") / len(b_vals)
    return float(np.max(np.abs(a_cdf - b_cdf)))


def _load_overlap_keys(path: Path) -> pd.DataFrame:
    overlap_df = pd.read_csv(path)
    required = {"date", "symbol"}
    missing = required - set(overlap_df.columns)
    if missing:
        raise ValueError(f"Overlap file missing columns: {sorted(missing)}")
    return (
        overlap_df[["date", "symbol"]].drop_duplicates().sort_values(["date", "symbol"])
    )


def _load_compact_training_rows(
    manifest_path: Path, overlap_keys: pd.DataFrame
) -> pd.DataFrame:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = pd.DataFrame(manifest["entries"])
    merged = overlap_keys.merge(entries, on=["date", "symbol"], how="left")
    missing_paths = merged[merged["path"].isna()]
    if not missing_paths.empty:
        raise RuntimeError(
            f"Missing compact-cache paths for overlap keys: {missing_paths.to_dict('records')}"
        )

    frames: list[pd.DataFrame] = []
    for _, row in merged.iterrows():
        frame = pd.read_parquet(row["path"]).copy()
        frame["date"] = row["date"]
        frame["symbol"] = row["symbol"]
        frames.append(frame)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _build_backtest_feature_rows(
    overlap_keys: pd.DataFrame, config: dict[str, Any]
) -> pd.DataFrame:
    gold_loader = GoldLoader()
    l2_loader = L2Loader()
    engine = AlphaBacktestEngine(config)
    rows: list[dict[str, Any]] = []

    for _, key in overlap_keys.iterrows():
        date = str(key["date"])
        symbol = str(key["symbol"])
        logger.info("Building backtest feature rows for %s %s", date, symbol)

        bars = gold_loader.load_bars(symbol, date, date).copy()
        l2_df = l2_loader.load_snapshots(symbol, date, source_type="any")
        engine._build_l2_index(l2_df)
        normalized = engine._normalize_ml_window(l2_df, symbol=symbol, date=date)
        featured = compute_ml_features(normalized)
        featured["event_score"] = compute_event_score(featured)
        featured = featured.sort_values("ts_utc").reset_index(drop=True)
        featured_ts = featured["ts_utc"].astype("int64").to_numpy()

        if not pd.api.types.is_datetime64_any_dtype(bars["ts"]):
            bars["ts"] = pd.to_datetime(bars["ts"])
        bars = bars.sort_values("ts").reset_index(drop=True)

        numeric_cols = featured.select_dtypes(
            include=[np.number, bool]
        ).columns.tolist()
        for _, bar in bars.iterrows():
            ts = pd.Timestamp(bar["ts"])
            ts_utc = (
                ts.tz_localize("America/New_York").tz_convert("UTC")
                if ts.tz is None
                else ts.tz_convert("UTC")
            )
            ts_ns = int(ts_utc.value)
            latest_idx = int(np.searchsorted(featured_ts, ts_ns, side="right")) - 1
            if latest_idx < 0:
                continue
            latest_ts_ns = int(featured_ts[latest_idx])
            if ts_ns - latest_ts_ns > engine._l2_staleness_seconds * 1_000_000_000:
                continue
            latest_row = featured.iloc[latest_idx]
            feature_row = {column: latest_row[column] for column in numeric_cols}
            feature_row["ts_bar"] = ts
            feature_row["ts_feature_utc"] = latest_row["ts_utc"]
            feature_row["date"] = date
            feature_row["symbol"] = symbol
            rows.append(feature_row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _distribution_row(
    feature: str, train_df: pd.DataFrame, backtest_df: pd.DataFrame
) -> dict[str, Any]:
    train = pd.to_numeric(train_df[feature], errors="coerce")
    backtest = pd.to_numeric(backtest_df[feature], errors="coerce")
    return {
        "feature": feature,
        "train_count": int(train.notna().sum()),
        "backtest_count": int(backtest.notna().sum()),
        "train_mean": float(train.mean()),
        "backtest_mean": float(backtest.mean()),
        "train_p50": float(train.quantile(0.50)),
        "backtest_p50": float(backtest.quantile(0.50)),
        "train_p90": float(train.quantile(0.90)),
        "backtest_p90": float(backtest.quantile(0.90)),
        "train_zero_rate": float((train.fillna(0.0) == 0).mean()),
        "backtest_zero_rate": float((backtest.fillna(0.0) == 0).mean()),
        "p50_ratio_backtest_to_train": (
            float(backtest.quantile(0.50) / train.quantile(0.50))
            if float(train.quantile(0.50)) not in (0.0, -0.0)
            else float("nan")
        ),
        "p90_ratio_backtest_to_train": (
            float(backtest.quantile(0.90) / train.quantile(0.90))
            if float(train.quantile(0.90)) not in (0.0, -0.0)
            else float("nan")
        ),
        "mean_ratio_backtest_to_train": (
            float(backtest.mean() / train.mean())
            if float(train.mean()) not in (0.0, -0.0)
            else float("nan")
        ),
        "ks_stat": _ks_statistic(train, backtest),
    }


def _zero_fill_flags(
    signal: MLSignal, train_df: pd.DataFrame, backtest_df: pd.DataFrame
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    shared_features = [
        feature for feature in signal._feature_cols if feature in train_df.columns
    ]

    for feature in shared_features:
        train = pd.to_numeric(train_df[feature], errors="coerce").fillna(0.0)
        backtest = pd.to_numeric(backtest_df.get(feature, 0.0), errors="coerce").fillna(
            0.0
        )
        train_zero = float((train == 0).mean())
        backtest_zero = float((backtest == 0).mean())
        if backtest_zero >= 0.95 and train_zero <= 0.80:
            rows.append(
                {
                    "feature": feature,
                    "train_zero_rate": train_zero,
                    "backtest_zero_rate": backtest_zero,
                    "train_abs_mean": float(train.abs().mean()),
                    "backtest_abs_mean": float(backtest.abs().mean()),
                }
            )

    if not rows:
        return pd.DataFrame(
            columns=["feature", "train_zero_rate", "backtest_zero_rate"]
        )
    return pd.DataFrame(rows).sort_values(
        ["backtest_zero_rate", "train_zero_rate", "feature"],
        ascending=[False, True, True],
    )


def _write_report(
    output_dir: Path,
    distribution_df: pd.DataFrame,
    zero_fill_df: pd.DataFrame,
    summary: dict[str, Any],
) -> Path:
    report_path = output_dir / "report.md"
    lines = [
        "# Phase 2 ML Feature-Path Validation",
        "",
        "## Scope",
        "",
        f"- Overlap symbol-days: `{summary['symbol_days']}`",
        f"- Training rows compared: `{summary['train_rows']}`",
        f"- Backtest feature rows compared: `{summary['backtest_rows']}`",
        f"- Compared features: `{', '.join(FEATURES_TO_COMPARE)}`",
        "",
        "## Verdict",
        "",
        f"- Acceptance status: `{summary['acceptance_status']}`",
        f"- Model-input distribution breaks: `{summary['major_break_count']}`",
        f"- Auxiliary-only breaks: `{summary['auxiliary_break_count']}`",
        f"- Systematic zero-fill flags: `{summary['zero_fill_flag_count']}`",
        f"- Worst KS feature: `{summary['worst_ks_feature']}` (`{summary['worst_ks_value']:.3f}`)",
        "",
        "## Feature Comparison",
        "",
    ]

    for _, row in distribution_df.iterrows():
        lines.append(
            f"- `{row['feature']}`: train mean `{row['train_mean']:.6f}`, "
            f"backtest mean `{row['backtest_mean']:.6f}`, "
            f"train p90 `{row['train_p90']:.6f}`, backtest p90 `{row['backtest_p90']:.6f}`, "
            f"KS `{row['ks_stat']:.3f}`, zero-rate train/backtest "
            f"`{row['train_zero_rate']:.1%}` / `{row['backtest_zero_rate']:.1%}`"
        )

    lines.extend(["", "## Zero-Fill Flags", ""])
    if zero_fill_df.empty:
        lines.append("- none")
    else:
        for _, row in zero_fill_df.head(20).iterrows():
            lines.append(
                f"- `{row['feature']}`: zero-rate train/backtest "
                f"`{row['train_zero_rate']:.1%}` / `{row['backtest_zero_rate']:.1%}`, "
                f"abs-mean train/backtest `{row['train_abs_mean']:.6f}` / `{row['backtest_abs_mean']:.6f}`"
            )

    lines.extend(["", "## Next Step", "", summary["next_step"], ""])
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def run_phase2_feature_validation(
    overlap_path: Path,
    compact_manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    signal = MLSignal(config)

    overlap_keys = _load_overlap_keys(overlap_path)
    train_df = _load_compact_training_rows(compact_manifest_path, overlap_keys)
    backtest_df = _build_backtest_feature_rows(overlap_keys, config)

    distribution_rows = [
        _distribution_row(feature, train_df, backtest_df)
        for feature in FEATURES_TO_COMPARE
    ]
    distribution_df = pd.DataFrame(distribution_rows)
    zero_fill_df = _zero_fill_flags(signal, train_df, backtest_df)

    major_breaks = distribution_df[
        (distribution_df["ks_stat"] >= 0.35)
        | (
            distribution_df["p90_ratio_backtest_to_train"].replace(0, np.nan).abs()
            >= 3.0
        )
        & (
            distribution_df["p50_ratio_backtest_to_train"].replace(0, np.nan).abs()
            >= 1.5
        )
    ].copy()
    critical_breaks = major_breaks[
        ~major_breaks["feature"].isin(AUXILIARY_FEATURES)
    ].copy()
    auxiliary_breaks = major_breaks[
        major_breaks["feature"].isin(AUXILIARY_FEATURES)
    ].copy()

    worst_row = distribution_df.sort_values("ks_stat", ascending=False).iloc[0]
    acceptance_status = (
        "pass" if critical_breaks.empty and zero_fill_df.empty else "review_required"
    )
    summary = {
        "symbol_days": int(len(overlap_keys)),
        "train_rows": int(len(train_df)),
        "backtest_rows": int(len(backtest_df)),
        "major_break_count": int(len(critical_breaks)),
        "auxiliary_break_count": int(len(auxiliary_breaks)),
        "zero_fill_flag_count": int(len(zero_fill_df)),
        "acceptance_status": acceptance_status,
        "worst_ks_feature": str(worst_row["feature"]),
        "worst_ks_value": float(worst_row["ks_stat"]),
        "next_step": (
            "Proceed to Phase 3 threshold calibration on verified overlap windows."
            if acceptance_status == "pass"
            else "Investigate the flagged model-input features before trusting live-threshold calibration."
        ),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    distribution_df.to_csv(
        output_dir / "feature_distribution_comparison.csv", index=False
    )
    zero_fill_df.to_csv(output_dir / "zero_fill_flags.csv", index=False)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    report_path = _write_report(output_dir, distribution_df, zero_fill_df, summary)
    logger.info("Phase 2 report written to %s", report_path)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run ML Phase 2 feature-path validation"
    )
    parser.add_argument(
        "--overlap-path",
        type=Path,
        default=Path("output/ml_phase1_diagnostics_2026-03-12/overlap_symbol_days.csv"),
        help="Phase 1 overlap symbol-day CSV",
    )
    parser.add_argument(
        "--compact-manifest",
        type=Path,
        default=Path("output/ml_compact_cache/manifest.json"),
        help="Compact-cache manifest path",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/ml_phase2_feature_validation_2026-03-12"),
        help="Directory for Phase 2 artifacts",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = run_phase2_feature_validation(
        overlap_path=args.overlap_path,
        compact_manifest_path=args.compact_manifest,
        output_dir=args.output_dir,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
