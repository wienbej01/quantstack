#!/usr/bin/env python3
"""Train a lightweight accept/reject model on top of a frozen action-ranker policy."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_ml_action_ranker_budget_backtest import (
    RankedAction,
    ScheduledActionSignal,
    _base_config,
    _load_daily_payloads,
    _load_or_build_ranked_actions,
    _select_topk,
    _to_signal_event,
)
from src.backtest import AlphaBacktestEngine
from src.data.ml_labels import SplitInfo, temporal_split
from src.models.action_ranker import (
    ACTION_QUALITY_BASE_COLUMNS,
    ACTION_QUALITY_PRICE_COLUMNS,
    ActionQualityLogisticModel,
    build_action_quality_features,
)

# RankedAction caches were written by a script entry point, so joblib may look for the class on __main__.
setattr(sys.modules["__main__"], "RankedAction", RankedAction)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

_QUALITY_CONTEXT_COLUMNS = tuple(
    column
    for column in (
        *ACTION_QUALITY_BASE_COLUMNS,
        *ACTION_QUALITY_PRICE_COLUMNS,
        "session_bucket",
    )
    if column != "rank_score"
)


def _candidate_row(
    action: RankedAction, trade: Any, date: str, label_min_pnl: float
) -> dict[str, Any]:
    context = getattr(action, "context", None) or {}
    pnl = float(trade.pnl)
    row = {
        "date": date,
        "symbol": str(action.symbol),
        "timestamp": pd.Timestamp(action.timestamp),
        "side": action.side.value,
        "hold_minutes": int(action.hold_minutes),
        "rank_score": float(action.score),
        "quality_target": int(pnl > float(label_min_pnl)),
        "pnl": pnl,
        "pnl_pct": float(trade.pnl_pct),
    }
    for column in _QUALITY_CONTEXT_COLUMNS:
        row[column] = context.get(column)
    return row


def _build_quality_training_rows_from_forensic(
    *,
    context_path: Path,
    selected_actions_path: Path,
    label_min_pnl: float,
) -> tuple[pd.DataFrame, dict[str, int]]:
    context_df = pd.read_csv(context_path)
    selected_df = pd.read_csv(selected_actions_path)
    if context_df.empty:
        raise RuntimeError(f"Forensic context export is empty: {context_path}")
    if selected_df.empty:
        raise RuntimeError(
            f"Forensic selected-actions export is empty: {selected_actions_path}"
        )

    context_df = context_df.drop(
        columns=[
            column
            for column in ("rank_score", "scheduled_hold_minutes")
            if column in context_df.columns
        ],
        errors="ignore",
    )
    context_df["entry_time"] = pd.to_datetime(context_df["entry_time"])
    selected_df["timestamp"] = pd.to_datetime(selected_df["timestamp"])
    selected_df["entry_time_match"] = selected_df["timestamp"] + pd.Timedelta(minutes=1)
    selected_df = selected_df.rename(
        columns={
            "hold_minutes": "scheduled_hold_minutes",
            "score": "rank_score",
        }
    )

    merged = context_df.merge(
        selected_df[
            [
                "date",
                "symbol",
                "side",
                "entry_time_match",
                "scheduled_hold_minutes",
                "rank_score",
            ]
        ],
        left_on=["date", "symbol", "side", "entry_time"],
        right_on=["date", "symbol", "side", "entry_time_match"],
        how="left",
    )
    matched = merged[merged["rank_score"].notna()].copy()
    matched["hold_minutes"] = pd.to_numeric(
        matched["scheduled_hold_minutes"], errors="coerce"
    ).fillna(pd.to_numeric(matched["hold_minutes"], errors="coerce"))
    matched["quality_target"] = (
        pd.to_numeric(matched["pnl"], errors="coerce").fillna(0.0)
        > float(label_min_pnl)
    ).astype(int)
    keep_cols = [
        "date",
        "symbol",
        "entry_time",
        "side",
        "hold_minutes",
        "rank_score",
        "quality_target",
        "pnl",
        "pnl_pct",
        *_QUALITY_CONTEXT_COLUMNS,
        "spread_std_30s",
        "spread_std_60s",
        "micro_off_std_30s",
        "micro_off_std_60s",
    ]
    rows = matched.reindex(columns=keep_cols).rename(
        columns={"entry_time": "timestamp"}
    )
    stats = {
        "dates": int(context_df["date"].nunique()),
        "selected_actions": int(len(selected_df)),
        "completed_trades": int(len(context_df)),
        "matched_rows": int(len(rows)),
        "unmatched_actions": int(len(selected_df) - len(rows)),
    }
    return rows, stats


def _profit_factor(pnl: pd.Series) -> float:
    gross_profit = float(pnl[pnl > 0].sum())
    gross_loss = float((-pnl[pnl < 0]).sum())
    if gross_loss > 0:
        return gross_profit / gross_loss
    return 999.0 if gross_profit > 0 else 0.0


def _evaluate_quality_filter(
    df: pd.DataFrame,
    model: ActionQualityLogisticModel,
    *,
    feature_columns: list[str],
    acceptance_threshold: float,
) -> dict[str, float]:
    if df.empty:
        return {
            "days": 0,
            "candidates": 0,
            "accepted": 0,
            "acceptance_rate": 0.0,
            "precision": 0.0,
            "total_pnl": 0.0,
            "mean_pnl": 0.0,
            "profit_factor": 0.0,
            "trades_per_day": 0.0,
        }

    probabilities = model.predict_acceptance_proba(
        df[feature_columns].to_numpy(dtype=np.float32, copy=True)
    )
    accepted = df.loc[probabilities >= acceptance_threshold].copy()
    days = int(df["date"].nunique())
    accepted_count = int(len(accepted))
    total_pnl = float(accepted["pnl"].sum()) if accepted_count else 0.0
    mean_pnl = float(accepted["pnl"].mean()) if accepted_count else 0.0
    precision = float(accepted["quality_target"].mean()) if accepted_count else 0.0
    return {
        "days": days,
        "candidates": int(len(df)),
        "accepted": accepted_count,
        "acceptance_rate": float(accepted_count / len(df)) if len(df) else 0.0,
        "precision": precision,
        "total_pnl": total_pnl,
        "mean_pnl": mean_pnl,
        "profit_factor": _profit_factor(accepted["pnl"]) if accepted_count else 0.0,
        "trades_per_day": float(accepted_count / days) if days else 0.0,
    }


def _build_quality_training_rows(
    *,
    action_artifact_path: str,
    start_date: str,
    end_date: str,
    daily_top_k: int,
    max_longs_per_day: int,
    min_score: float,
    output_dir: Path,
    bar_source: str,
    score_cache: bool,
    cache_dir: Path | None,
    label_min_pnl: float,
) -> tuple[pd.DataFrame, dict[str, int]]:
    action_artifact = joblib.load(action_artifact_path)
    config = _base_config(bar_source)
    payloads = _load_daily_payloads(start_date, end_date, config)

    rows: list[dict[str, Any]] = []
    unmatched_actions = 0
    selected_actions = 0
    completed_trades = 0

    for payload in payloads:
        ranked = _load_or_build_ranked_actions(
            payload=payload,
            window_label="quality_train",
            config=config,
            artifact=action_artifact,
            output_dir=output_dir,
            score_cache=score_cache,
            cache_dir=cache_dir,
        )
        selected = _select_topk(
            ranked,
            top_k=daily_top_k,
            max_longs_per_day=max_longs_per_day,
            min_score=min_score,
        )
        selected_actions += len(selected)
        if not selected:
            continue

        engine = AlphaBacktestEngine(config)
        signal = ScheduledActionSignal(
            config, [_to_signal_event(item) for item in selected]
        )
        result = engine.run(payload["bars"], l2_df=payload["l2"], signals=[signal])
        trade_lookup = {
            (str(trade.symbol), pd.Timestamp(trade.entry_time)): trade
            for trade in result.trades
        }
        completed_trades += len(result.trades)
        for action in selected:
            trade = trade_lookup.get(
                (str(action.symbol), pd.Timestamp(action.timestamp))
            )
            if trade is None:
                unmatched_actions += 1
                continue
            rows.append(_candidate_row(action, trade, payload["date"], label_min_pnl))

    dataset = pd.DataFrame(rows)
    stats = {
        "dates": int(len(payloads)),
        "selected_actions": int(selected_actions),
        "completed_trades": int(completed_trades),
        "matched_rows": int(len(dataset)),
        "unmatched_actions": int(unmatched_actions),
    }
    return dataset, stats


def _date_only_quality_split(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, SplitInfo]:
    dates = sorted(str(value) for value in df["date"].unique())
    n_dates = len(dates)
    if n_dates < 3:
        return (
            pd.DataFrame(columns=df.columns),
            pd.DataFrame(columns=df.columns),
            pd.DataFrame(columns=df.columns),
            SplitInfo([], [], [], [], []),
        )

    train_end = max(1, min(n_dates - 2, int(n_dates * 0.65)))
    val_end = max(train_end + 1, min(n_dates - 1, int(n_dates * 0.85)))
    train_dates = dates[:train_end]
    val_dates = dates[train_end:val_end]
    test_dates = dates[val_end:]

    train_df = df[df["date"].isin(train_dates)].copy()
    val_df = df[df["date"].isin(val_dates)].copy()
    test_df = df[df["date"].isin(test_dates)].copy()
    return (
        train_df,
        val_df,
        test_df,
        SplitInfo(
            train_dates=train_dates,
            val_dates=val_dates,
            test_dates=test_dates,
            train_symbols=sorted(str(value) for value in train_df["symbol"].unique()),
            holdout_symbols=[],
        ),
    )


def _row_temporal_quality_split(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, SplitInfo]:
    ordered = df.copy()
    if "timestamp" in ordered.columns:
        ordered["timestamp"] = pd.to_datetime(ordered["timestamp"], errors="coerce")
    sort_cols = [
        column
        for column in ("timestamp", "date", "symbol")
        if column in ordered.columns
    ]
    if sort_cols:
        ordered = ordered.sort_values(sort_cols).reset_index(drop=True)
    n_rows = len(ordered)
    if n_rows < 3:
        return (
            pd.DataFrame(columns=df.columns),
            pd.DataFrame(columns=df.columns),
            pd.DataFrame(columns=df.columns),
            SplitInfo([], [], [], [], []),
        )

    train_end = max(1, min(n_rows - 2, int(n_rows * 0.60)))
    val_end = max(train_end + 1, min(n_rows - 1, int(n_rows * 0.80)))
    train_df = ordered.iloc[:train_end].copy()
    val_df = ordered.iloc[train_end:val_end].copy()
    test_df = ordered.iloc[val_end:].copy()
    return (
        train_df,
        val_df,
        test_df,
        SplitInfo(
            train_dates=sorted(str(value) for value in train_df["date"].unique()),
            val_dates=sorted(str(value) for value in val_df["date"].unique()),
            test_dates=sorted(str(value) for value in test_df["date"].unique()),
            train_symbols=sorted(str(value) for value in train_df["symbol"].unique()),
            holdout_symbols=[],
        ),
    )


def _quality_temporal_split(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, SplitInfo, str]:
    train_df, val_df, test_df, split_info = temporal_split(df)
    if not train_df.empty and not val_df.empty and not test_df.empty:
        return train_df, val_df, test_df, split_info, "date_symbol_holdout"

    logger.warning(
        "Quality split fell back from date+symbol holdout because one partition was empty "
        "(train=%s val=%s test=%s)",
        len(train_df),
        len(val_df),
        len(test_df),
    )
    train_df, val_df, test_df, split_info = _date_only_quality_split(df)
    if not train_df.empty and not val_df.empty and not test_df.empty:
        return train_df, val_df, test_df, split_info, "date_only"

    logger.warning(
        "Quality split fell back from date-only split because one partition was empty "
        "(train=%s val=%s test=%s)",
        len(train_df),
        len(val_df),
        len(test_df),
    )
    train_df, val_df, test_df, split_info = _row_temporal_quality_split(df)
    if not train_df.empty and not val_df.empty and not test_df.empty:
        return train_df, val_df, test_df, split_info, "row_temporal"

    raise RuntimeError("Quality model split produced an empty train/val/test partition")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train action quality accept/reject model"
    )
    parser.add_argument(
        "--action-artifact-path", default="models/action_ranker_xgb_2026-03-19.pkl"
    )
    parser.add_argument("--start-date", default="2026-01-01")
    parser.add_argument("--end-date", default="2026-03-13")
    parser.add_argument("--daily-top-k", type=int, default=4)
    parser.add_argument("--max-longs-per-day", type=int, default=2)
    parser.add_argument("--min-score", type=float, default=0.5)
    parser.add_argument("--label-min-pnl", type=float, default=0.0)
    parser.add_argument("--acceptance-threshold", type=float, default=0.5)
    parser.add_argument("--logistic-c", type=float, default=1.0)
    parser.add_argument("--logistic-max-iter", type=int, default=1000)
    parser.add_argument("--bar-source", choices=["gold", "polygon"], default="polygon")
    parser.add_argument("--no-score-cache", action="store_true")
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument(
        "--forensic-context-path",
        default=None,
        help="Optional forensic entry_contexts.csv path for fast training without replay.",
    )
    parser.add_argument(
        "--forensic-selected-actions-path",
        default=None,
        help="Optional forensic selected_actions.csv path matched to --forensic-context-path.",
    )
    parser.add_argument(
        "--save-path",
        default="models/action_quality_logistic_2026-03-21.pkl",
        help="Artifact path",
    )
    parser.add_argument(
        "--report-dir",
        default="output/ml_training_reports/action_quality_logistic_2026-03-21",
        help="Report directory",
    )
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(args.cache_dir) if args.cache_dir else None
    if args.forensic_context_path or args.forensic_selected_actions_path:
        if not args.forensic_context_path or not args.forensic_selected_actions_path:
            raise ValueError(
                "--forensic-context-path and --forensic-selected-actions-path must be provided together"
            )
        dataset, dataset_stats = _build_quality_training_rows_from_forensic(
            context_path=Path(args.forensic_context_path),
            selected_actions_path=Path(args.forensic_selected_actions_path),
            label_min_pnl=args.label_min_pnl,
        )
    else:
        dataset, dataset_stats = _build_quality_training_rows(
            action_artifact_path=args.action_artifact_path,
            start_date=args.start_date,
            end_date=args.end_date,
            daily_top_k=args.daily_top_k,
            max_longs_per_day=args.max_longs_per_day,
            min_score=args.min_score,
            output_dir=report_dir,
            bar_source=args.bar_source,
            score_cache=not args.no_score_cache,
            cache_dir=cache_dir,
            label_min_pnl=args.label_min_pnl,
        )
    if dataset.empty:
        raise RuntimeError("No matched action-quality training rows were generated")
    effective_start_date = (
        str(dataset["date"].min()) if "date" in dataset.columns else args.start_date
    )
    effective_end_date = (
        str(dataset["date"].max()) if "date" in dataset.columns else args.end_date
    )

    action_artifact = joblib.load(args.action_artifact_path)
    dataset, feature_columns = build_action_quality_features(
        dataset,
        hold_minutes=action_artifact.get("hold_minutes", [3, 5, 8, 12]),
    )
    train_df, val_df, test_df, split_info, split_mode = _quality_temporal_split(dataset)

    model = ActionQualityLogisticModel(
        feature_columns=feature_columns,
        c=args.logistic_c,
        max_iter=args.logistic_max_iter,
    )
    model.fit(train_df, target_column="quality_target")

    val_summary = _evaluate_quality_filter(
        val_df,
        model,
        feature_columns=feature_columns,
        acceptance_threshold=args.acceptance_threshold,
    )
    test_summary = _evaluate_quality_filter(
        test_df,
        model,
        feature_columns=feature_columns,
        acceptance_threshold=args.acceptance_threshold,
    )

    artifact = {
        "model_family": "action_quality_logistic",
        "model": model,
        "feature_columns": feature_columns,
        "action_artifact_path": args.action_artifact_path,
        "training_window": {
            "start_date": effective_start_date,
            "end_date": effective_end_date,
        },
        "daily_top_k": args.daily_top_k,
        "max_longs_per_day": args.max_longs_per_day,
        "min_score": args.min_score,
        "label_min_pnl": args.label_min_pnl,
        "acceptance_threshold": args.acceptance_threshold,
        "hold_minutes": action_artifact.get("hold_minutes", [3, 5, 8, 12]),
        "split_mode": split_mode,
        "dataset_stats": dataset_stats,
        "split_info": {
            "train_dates": split_info.train_dates,
            "val_dates": split_info.val_dates,
            "test_dates": split_info.test_dates,
        },
        "validation_summary": val_summary,
        "test_summary": test_summary,
    }

    save_path = Path(args.save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, save_path)

    dataset.to_csv(report_dir / "quality_training_rows.csv", index=False)
    (report_dir / "training_metrics.json").write_text(
        json.dumps(artifact, indent=2, default=str)
    )

    importance = sorted(
        model.feature_importance().items(), key=lambda item: item[1], reverse=True
    )[:20]
    lines = [
        "# Action Quality Model Training Report",
        "",
        f"- artifact: `{save_path}`",
        f"- action artifact: `{args.action_artifact_path}`",
        f"- training window: `{effective_start_date}` to `{effective_end_date}`",
        f"- policy: `top_k={args.daily_top_k}, max_longs_per_day={args.max_longs_per_day}`",
        f"- min score: `{args.min_score}`",
        f"- label min pnl: `{args.label_min_pnl}`",
        f"- acceptance threshold: `{args.acceptance_threshold}`",
        f"- split mode: `{split_mode}`",
        f"- dataset stats: `{dataset_stats}`",
        f"- validation summary: `{val_summary}`",
        f"- test summary: `{test_summary}`",
        "",
        "## Top Features",
        "",
    ]
    lines.extend(f"- {name}: {score:.4f}" for name, score in importance)
    (report_dir / "training_report.md").write_text("\n".join(lines) + "\n")
    logger.info("Saved action-quality artifact to %s", save_path)


if __name__ == "__main__":
    main()
