#!/usr/bin/env python3
"""Train a learned post-cost action scorer for trade-budget allocation."""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_hypothesis_test import DEFAULT_CONFIG, load_polygon_bars
from scripts.train_ml_model import (
    _align_training_rows_to_live_scoring,
    _apply_training_balance_weights,
    _augment_training_context_features,
    _build_training_dataframe_from_compact_cache,
    _configure_runtime,
    _coverage_summary,
    _select_training_universe,
)
from src.data.ml_compact_cache import CompactCacheConfig, save_compact_cache
from src.data.ml_label_artifacts import LabelArtifactConfig
from src.features.ml_features import add_causal_price_features
from src.models.action_ranker import (
    ActionEdgeRegressor,
    ActionRankerLogistic,
    ActionRankerXGBoost,
    action_edge_sample_weights,
    derive_action_targets,
    get_action_ranker_feature_columns,
)
from src.data.ml_labels import temporal_split

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def _parse_hold_minutes(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _maybe_build_cache(
    cache_dir: Path, hold_minutes: list[int], rows_per_symbol_day: int
) -> None:
    manifest_path = cache_dir / "manifest.json"
    desired_horizons = tuple(sorted({minute * 60 for minute in hold_minutes}))
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        actual = tuple(
            manifest.get("config", {})
            .get("label_config", {})
            .get("horizons_seconds", [])
        )
        if set(desired_horizons).issubset(set(int(value) for value in actual)):
            return

    logger.info("Building action-ranker compact cache in %s", cache_dir)
    save_compact_cache(
        output_dir=cache_dir,
        label_config=LabelArtifactConfig(
            horizons_seconds=desired_horizons,
            threshold_method="fixed",
            fixed_bps=10.0,
        ),
        compact_config=CompactCacheConfig(bucket_seconds=1),
        sample_rows_per_symbol_day=rows_per_symbol_day,
    )


def _evaluate_rank_quality(
    df: pd.DataFrame,
    model: ActionRankerLogistic | ActionEdgeRegressor | ActionRankerXGBoost,
    *,
    feature_cols: list[str],
    top_k: int,
) -> dict[str, float]:
    if df.empty:
        return {"days": 0, "selected": 0, "precision": 0.0, "mean_edge_bps": 0.0}

    rows: list[dict[str, float]] = []
    X = np.nan_to_num(df[feature_cols].to_numpy(dtype=np.float32, copy=True))
    scores = model.predict_action_scores(X)
    score_df = df[["date"]].reset_index(drop=True).copy()
    score_df["best_score"] = scores.max(axis=1)
    score_df["best_idx"] = scores.argmax(axis=1)

    for date, group in score_df.groupby("date", sort=True):
        ranked = group.sort_values("best_score", ascending=False).head(top_k)
        for idx in ranked.index:
            best_idx = int(score_df.loc[idx, "best_idx"])
            action_key = model.action_specs[best_idx].key
            rows.append(
                {
                    "date": date,
                    "target": float(df.iloc[idx][f"target_{action_key}"]),
                    "edge_bps": float(df.iloc[idx][f"edge_{action_key}_bps"]),
                }
            )

    if not rows:
        return {
            "days": int(df["date"].nunique()),
            "selected": 0,
            "precision": 0.0,
            "mean_edge_bps": 0.0,
        }
    ranked_df = pd.DataFrame(rows)
    return {
        "days": int(df["date"].nunique()),
        "selected": int(len(ranked_df)),
        "precision": float(ranked_df["target"].mean()),
        "mean_edge_bps": float(ranked_df["edge_bps"].mean()),
    }


def _base_bar_config() -> dict:
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["data"]["bar_source"] = "polygon"
    return config


def _to_utc_timestamp(series: pd.Series) -> pd.Series:
    ts = pd.to_datetime(series)
    if getattr(ts.dt, "tz", None) is None:
        return ts.dt.tz_localize("America/New_York").dt.tz_convert("UTC")
    return ts.dt.tz_convert("UTC")


def _attach_causal_bar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Merge prior completed minute-bar context onto live-aligned training rows."""
    if df.empty:
        return df

    config = _base_bar_config()
    bar_frames: list[pd.DataFrame] = []
    pairs = (
        df[["symbol", "date"]]
        .dropna()
        .drop_duplicates()
        .sort_values(["date", "symbol"])
        .itertuples(index=False)
    )
    for symbol, date in pairs:
        try:
            bars = load_polygon_bars(str(symbol), str(date), str(date), config)
        except (FileNotFoundError, RuntimeError) as exc:
            logger.debug(
                "Skipping causal bar features for %s %s: %s", symbol, date, exc
            )
            continue
        if bars.empty:
            continue
        enriched = bars.sort_values("ts").reset_index(drop=True).copy()
        enriched["ts_utc_bucket"] = _to_utc_timestamp(enriched["ts"]).dt.floor("60s")
        price_cols = ["open", "high", "low", "close", "volume"]
        enriched[price_cols] = enriched[price_cols].shift(1)
        enriched["date"] = str(date)
        enriched["symbol"] = str(symbol)
        bar_frames.append(
            enriched[
                [
                    "symbol",
                    "date",
                    "ts_utc_bucket",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                ]
            ]
        )

    if not bar_frames:
        logger.warning(
            "No causal minute bars were attached to the action-ranker training frame"
        )
        return df

    bar_df = pd.concat(bar_frames, ignore_index=True)
    merged = df.copy()
    merged["ts_utc"] = pd.to_datetime(merged["ts_utc"], utc=True)
    merged["ts_utc_bucket"] = merged["ts_utc"].dt.floor("60s")
    merged = merged.merge(bar_df, on=["symbol", "date", "ts_utc_bucket"], how="left")
    merged = add_causal_price_features(merged)
    return merged.drop(columns=["ts_utc_bucket"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Train learned action ranker")
    parser.add_argument(
        "--compact-cache-dir",
        default="output/ml_compact_cache_action_2026-03-17",
        help="Compact cache path for action-ranker training",
    )
    parser.add_argument(
        "--hold-minutes",
        default="2,3,4,5,6,8,10,12",
        help="Comma-separated hold buckets in minutes",
    )
    parser.add_argument("--rows-per-symbol-day", type=int, default=4000)
    parser.add_argument("--max-total-rows", type=int, default=800000)
    parser.add_argument("--max-rows-per-date", type=int, default=22000)
    parser.add_argument("--alignment-bucket-seconds", type=int, default=60)
    parser.add_argument("--cpu-limit", type=int, default=4)
    parser.add_argument("--memory-limit-gb", type=float, default=12.0)
    parser.add_argument("--base-edge-bps", type=float, default=8.0)
    parser.add_argument("--spread-weight", type=float, default=0.35)
    parser.add_argument("--open-penalty-bps", type=float, default=1.0)
    parser.add_argument("--raw-penalty-bps", type=float, default=1.0)
    parser.add_argument(
        "--positive-edge-buffer-bps",
        type=float,
        default=2.0,
        help="Require positive actions to exceed the net edge floor by this many bps",
    )
    parser.add_argument(
        "--edge-weight-scale-bps",
        type=float,
        default=12.0,
        help="Scale for row weights based on absolute best-action edge",
    )
    parser.add_argument(
        "--edge-weight-max-multiplier",
        type=float,
        default=3.0,
        help="Cap on edge-strength weighting multiplier",
    )
    parser.add_argument("--top-k-validation", type=int, default=4)
    parser.add_argument(
        "--objective",
        choices=["logistic", "edge_regression", "xgb_logistic"],
        default="logistic",
        help="Training objective for per-action scoring",
    )
    parser.add_argument(
        "--ridge-alpha",
        type=float,
        default=2.0,
        help="L2 strength for edge-regression action ranker",
    )
    parser.add_argument("--xgb-max-depth", type=int, default=4)
    parser.add_argument("--xgb-n-estimators", type=int, default=200)
    parser.add_argument("--xgb-learning-rate", type=float, default=0.05)
    parser.add_argument("--xgb-subsample", type=float, default=0.8)
    parser.add_argument("--xgb-colsample-bytree", type=float, default=0.7)
    parser.add_argument("--xgb-min-child-weight", type=float, default=25.0)
    parser.add_argument("--xgb-reg-alpha", type=float, default=0.1)
    parser.add_argument("--xgb-reg-lambda", type=float, default=1.0)
    parser.add_argument("--xgb-n-jobs", type=int, default=1)
    parser.add_argument(
        "--save-path",
        default="models/action_ranker_logistic_2026-03-17.pkl",
        help="Artifact path",
    )
    parser.add_argument(
        "--report-dir",
        default="output/ml_training_reports/action_ranker_logistic_2026-03-17",
        help="Report directory",
    )
    parser.add_argument(
        "--side-aware-context-features",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Add side-aware context features before action-label derivation",
    )
    parser.add_argument(
        "--causal-price-features",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Attach causal OHLCV/VWAP/trend features from minute bars after live-bucket alignment.",
    )
    args = parser.parse_args()

    _configure_runtime(args.cpu_limit, args.memory_limit_gb)
    hold_minutes = _parse_hold_minutes(args.hold_minutes)
    cache_dir = Path(args.compact_cache_dir)
    _maybe_build_cache(cache_dir, hold_minutes, args.rows_per_symbol_day)

    df = _build_training_dataframe_from_compact_cache(
        cache_dir=cache_dir,
        max_total_rows=args.max_total_rows,
        max_rows_per_date=args.max_rows_per_date,
        sampling_strategy="balanced_by_date",
    )
    if df.empty:
        raise RuntimeError("No rows available for action-ranker training")

    df = _align_training_rows_to_live_scoring(
        df, bucket_seconds=args.alignment_bucket_seconds
    )
    if args.causal_price_features:
        df = _attach_causal_bar_features(df)
    df = _augment_training_context_features(df, args.side_aware_context_features)
    df, specs = derive_action_targets(
        df,
        hold_minutes=hold_minutes,
        base_edge_bps=args.base_edge_bps,
        spread_weight=args.spread_weight,
        open_penalty_bps=args.open_penalty_bps,
        raw_penalty_bps=args.raw_penalty_bps,
        positive_edge_buffer_bps=args.positive_edge_buffer_bps,
    )

    feature_cols = get_action_ranker_feature_columns(df)
    df[feature_cols] = (
        df[feature_cols]
        .astype("float32")
        .fillna(0.0)
        .replace([float("inf"), float("-inf")], 0.0)
    )

    _, _, _, split_info = temporal_split(df)
    training_df = _select_training_universe(df, split_info)
    train_df = training_df[training_df["date"].isin(split_info.train_dates)].copy()
    val_df = df[df["date"].isin(split_info.val_dates)].copy()
    test_df = df[df["date"].isin(split_info.test_dates)].copy()
    weights = _apply_training_balance_weights(train_df)
    edge_weights = action_edge_sample_weights(
        train_df,
        scale_bps=args.edge_weight_scale_bps,
        max_multiplier=args.edge_weight_max_multiplier,
    )
    weights = weights * edge_weights
    mean_weight = float(weights.mean()) if len(weights) else 1.0
    if mean_weight > 0:
        weights = weights / mean_weight

    if args.objective == "edge_regression":
        model = ActionEdgeRegressor(
            feature_columns=feature_cols,
            action_specs=specs,
            alpha=args.ridge_alpha,
        )
    elif args.objective == "xgb_logistic":
        model = ActionRankerXGBoost(
            feature_columns=feature_cols,
            action_specs=specs,
            max_depth=args.xgb_max_depth,
            n_estimators=args.xgb_n_estimators,
            learning_rate=args.xgb_learning_rate,
            subsample=args.xgb_subsample,
            colsample_bytree=args.xgb_colsample_bytree,
            min_child_weight=args.xgb_min_child_weight,
            reg_alpha=args.xgb_reg_alpha,
            reg_lambda=args.xgb_reg_lambda,
            n_jobs=args.xgb_n_jobs,
        )
    else:
        model = ActionRankerLogistic(feature_columns=feature_cols, action_specs=specs)
    model.fit(train_df, sample_weight=weights)

    val_summary = _evaluate_rank_quality(
        val_df,
        model,
        feature_cols=feature_cols,
        top_k=args.top_k_validation,
    )
    test_summary = _evaluate_rank_quality(
        test_df,
        model,
        feature_cols=feature_cols,
        top_k=args.top_k_validation,
    )

    artifact = {
        "model_family": f"action_ranker_{args.objective}",
        "model": model,
        "feature_columns": feature_cols,
        "action_specs": [
            {"side": spec.side, "hold_minutes": spec.hold_minutes} for spec in specs
        ],
        "hold_minutes": hold_minutes,
        "base_edge_bps": args.base_edge_bps,
        "spread_weight": args.spread_weight,
        "open_penalty_bps": args.open_penalty_bps,
        "raw_penalty_bps": args.raw_penalty_bps,
        "positive_edge_buffer_bps": args.positive_edge_buffer_bps,
        "edge_weight_scale_bps": args.edge_weight_scale_bps,
        "edge_weight_max_multiplier": args.edge_weight_max_multiplier,
        "objective": args.objective,
        "ridge_alpha": args.ridge_alpha,
        "xgb_params": {
            "max_depth": args.xgb_max_depth,
            "n_estimators": args.xgb_n_estimators,
            "learning_rate": args.xgb_learning_rate,
            "subsample": args.xgb_subsample,
            "colsample_bytree": args.xgb_colsample_bytree,
            "min_child_weight": args.xgb_min_child_weight,
            "reg_alpha": args.xgb_reg_alpha,
            "reg_lambda": args.xgb_reg_lambda,
            "n_jobs": args.xgb_n_jobs,
        },
        "side_aware_context_features": args.side_aware_context_features,
        "causal_price_features": args.causal_price_features,
        "validation_top_k": args.top_k_validation,
        "validation_summary": val_summary,
        "test_summary": test_summary,
        "coverage_summary": _coverage_summary(df),
    }
    save_path = Path(args.save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, save_path)

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "training_metrics.json").write_text(
        json.dumps(artifact, indent=2, default=str)
    )

    importance = sorted(
        model.feature_importance().items(), key=lambda item: item[1], reverse=True
    )[:20]
    lines = [
        "# Action Ranker Training Report",
        "",
        f"- artifact: `{save_path}`",
        f"- hold buckets: `{hold_minutes}`",
        f"- base edge bps: `{args.base_edge_bps}`",
        f"- spread weight: `{args.spread_weight}`",
        f"- positive edge buffer bps: `{args.positive_edge_buffer_bps}`",
        f"- edge weight scale bps: `{args.edge_weight_scale_bps}`",
        f"- objective: `{args.objective}`",
        f"- causal price features: `{args.causal_price_features}`",
        f"- validation top-k: `{args.top_k_validation}`",
        f"- validation selected: `{val_summary['selected']}`",
        f"- validation precision: `{val_summary['precision']:.3f}`",
        f"- validation mean edge bps: `{val_summary['mean_edge_bps']:.2f}`",
        f"- test selected: `{test_summary['selected']}`",
        f"- test precision: `{test_summary['precision']:.3f}`",
        f"- test mean edge bps: `{test_summary['mean_edge_bps']:.2f}`",
        "",
        "## Top Features",
        "",
    ]
    lines.extend(f"- {name}: {score:.4f}" for name, score in importance)
    (report_dir / "training_report.md").write_text("\n".join(lines) + "\n")
    logger.info("Saved action-ranker artifact to %s", save_path)


if __name__ == "__main__":
    main()
