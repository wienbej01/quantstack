#!/usr/bin/env python3
"""Run exact top-K budget backtests on a learned action-ranker artifact."""

from __future__ import annotations

import argparse
import copy
import csv
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.run_hypothesis_test import DEFAULT_CONFIG, load_polygon_bars
from src.backtest import AlphaBacktestEngine
from src.backtest.engine import BacktestResult
from src.data import GoldLoader, L2Loader
from src.data.ml_compact_cache import compute_event_score
from src.features.ml_features import compute_ml_features
from src.metrics import compute_all_metrics
from src.models.action_ranker import (
    ACTION_QUALITY_BASE_COLUMNS,
    ACTION_QUALITY_PRICE_COLUMNS,
    ActionSpec,
    build_action_quality_features,
)
from src.signals.base import ExitEvent, Position, Signal, SignalEvent, SignalSide

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


_CAUSAL_BAR_FEATURE_COLUMNS = {
    "vwap",
    "dist_vwap_bps",
    "hl_range_pct",
    "oc_change_pct",
    "volume_rel_20",
    "atr_pct",
    "position_in_range",
    "rsi",
    "bb_width",
    "bb_position",
    "session_range",
    "ret_1",
    "ret_3",
    "ret_5",
    "ret_10",
    "log_log_ret_1",
    "log_log_ret_3",
    "log_log_ret_5",
    "log_log_ret_10",
}


@dataclass(frozen=True)
class WindowSpec:
    label: str
    start: str
    end: str


@dataclass(frozen=True)
class RankedAction:
    date: str
    symbol: str
    timestamp: pd.Timestamp
    side: SignalSide
    hold_minutes: int
    score: float
    context: dict[str, float | None] | None = None
    quality_score: float | None = None


@dataclass(frozen=True)
class WeakContextGate:
    max_pressure_k: float
    max_spread: float
    max_depth_imb_k: float


class ScheduledActionSignal(Signal):
    """Replay selected ranked actions with time-only exits."""

    requires_features = False

    def __init__(self, config: dict, scheduled_entries: list[SignalEvent]) -> None:
        super().__init__(config)
        self.signal_name = "MLSignal"
        self._entries = {
            (event.symbol, pd.Timestamp(event.timestamp)): event
            for event in scheduled_entries
        }

    def check_entry(
        self,
        features: dict,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> SignalEvent | None:
        del features
        return self._entries.get((str(bar["symbol"]), pd.Timestamp(timestamp)))

    def check_exit(
        self,
        position: Position,
        features: dict,
        bar: pd.Series,
        timestamp: pd.Timestamp,
    ) -> ExitEvent | None:
        del features, bar
        if position.age_minutes(timestamp) >= position.time_limit_minutes:
            return ExitEvent(
                symbol=position.symbol, timestamp=timestamp, reason="time_limit"
            )
        return None

    def create_position(
        self,
        signal: SignalEvent,
        entry_price: float,
        entry_time: pd.Timestamp,
        quantity: int,
    ) -> Position:
        hold_minutes = int(signal.features.get("hold_minutes", 5))
        return Position(
            symbol=signal.symbol,
            side=signal.side,
            entry_price=entry_price,
            entry_time=entry_time,
            quantity=quantity,
            target_price=entry_price * 10.0,
            stop_price=0.0,
            time_limit_minutes=hold_minutes,
            signal_name=self.signal_name,
        )


def _config_key(top_k: int, max_longs_per_day: int) -> tuple[int, int]:
    """Stable identifier for one matrix configuration."""
    return int(top_k), int(max_longs_per_day)


def _parse_windows(value: str) -> list[WindowSpec]:
    windows: list[WindowSpec] = []
    for chunk in value.split(","):
        label, start, end = [part.strip() for part in chunk.split(":")]
        windows.append(WindowSpec(label=label, start=start, end=end))
    return windows


def _parse_int_list(value: str) -> list[int]:
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _base_config(bar_source: str) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_CONFIG)
    config["data"]["bar_source"] = bar_source
    config["signals"]["ml"]["exit_mode"] = "time_only"
    config["signals"]["ml"]["target_pct"] = 0.0
    config["signals"]["ml"]["stop_pct"] = 0.0
    config["ml"]["max_symbols"] = 0
    return config


def _load_daily_payloads(
    start_date: str, end_date: str, config: dict[str, Any]
) -> list[dict[str, Any]]:
    l2_loader = L2Loader()
    gold_loader = GoldLoader()
    bar_source = config.get("data", {}).get("bar_source", "polygon")
    available_dates = [
        date
        for date in l2_loader.get_available_dates(source_type="any")
        if start_date <= date <= end_date
    ]
    payloads: list[dict[str, Any]] = []
    for date in available_dates:
        symbols = sorted(l2_loader.get_available_symbols(date, source_type="any"))
        bar_frames: list[pd.DataFrame] = []
        l2_frames: list[pd.DataFrame] = []
        for symbol in symbols:
            try:
                bars = (
                    load_polygon_bars(symbol, date, date, config)
                    if bar_source == "polygon"
                    else gold_loader.load_bars(symbol, date, date)
                )
                if not bars.empty:
                    bars["symbol"] = symbol
                    bar_frames.append(bars)
            except Exception as exc:
                logger.debug("Skipping bars for %s %s: %s", symbol, date, exc)
            try:
                l2_frames.append(
                    l2_loader.load_snapshots(symbol, date, source_type="any")
                )
            except FileNotFoundError:
                continue
        if bar_frames:
            payloads.append(
                {
                    "date": date,
                    "bars": pd.concat(bar_frames, ignore_index=True),
                    "l2": (
                        pd.concat(l2_frames, ignore_index=True) if l2_frames else None
                    ),
                }
            )
    return payloads


def _score_symbol(
    *,
    date: str,
    symbol: str,
    bars_df: pd.DataFrame,
    l2_df: pd.DataFrame | None,
    config: dict[str, Any],
    artifact: dict[str, Any],
) -> list[RankedAction]:
    """Score one symbol-day so progress can be cached incrementally."""
    feature_cols = list(artifact["feature_columns"])
    if l2_df is not None and not l2_df.empty and not (
        set(feature_cols) & _CAUSAL_BAR_FEATURE_COLUMNS
    ):
        return _score_symbol_l2_only_fast(
            date=date,
            symbol=symbol,
            bars_df=bars_df,
            l2_df=l2_df,
            config=config,
            artifact=artifact,
        )

    bars_df = bars_df.sort_values("ts").reset_index(drop=True)
    action_specs = [ActionSpec(**spec) for spec in artifact["action_specs"]]
    model = artifact["model"]
    engine = AlphaBacktestEngine(config)
    if l2_df is not None and not l2_df.empty:
        engine._build_l2_index(l2_df)
    executable_last_ts = pd.Timestamp(bars_df["ts"].max())
    needs_bar_history = bool(set(feature_cols) & _CAUSAL_BAR_FEATURE_COLUMNS)

    feature_rows: list[np.ndarray] = []
    candidates: list[
        tuple[pd.Timestamp, dict[str, float | None]]
    ] = []
    for row_idx, (_, bar) in enumerate(bars_df.iterrows()):
        ts = pd.Timestamp(bar["ts"])
        if ts >= executable_last_ts:
            continue
        bar_history = bars_df.iloc[: row_idx + 1].copy() if needs_bar_history else None
        bar_data = engine._prepare_bar_data(bar, l2_df, ts, bar_history=bar_history)
        if bar_data.features.get("_ml_features_ready") is False:
            continue
        if any(column not in bar_data.features for column in feature_cols):
            continue
        row = np.array(
            [bar_data.features[column] for column in feature_cols], dtype=np.float32
        )
        if not np.isfinite(row).all():
            continue
        quality_context_keys = (
            *(
                column
                for column in ACTION_QUALITY_BASE_COLUMNS
                if column != "rank_score"
            ),
            *ACTION_QUALITY_PRICE_COLUMNS,
            "session_bucket",
        )
        context = {
            column: _maybe_float(bar_data.features.get(column))
            for column in quality_context_keys
        }
        feature_rows.append(row)
        candidates.append((ts, context))

    if not feature_rows:
        return []

    score_matrix = model.predict_action_scores(np.vstack(feature_rows))
    ranked: list[RankedAction] = []
    for (ts, context), scores in zip(candidates, score_matrix):
        best_idx = int(np.argmax(scores))
        best_spec = action_specs[best_idx]
        ranked.append(
            RankedAction(
                date=date,
                symbol=str(symbol),
                timestamp=ts,
                side=SignalSide.LONG if best_spec.side == "long" else SignalSide.SHORT,
                hold_minutes=best_spec.hold_minutes,
                score=float(scores[best_idx]),
                context=context,
            )
        )
    return ranked


def _score_symbol_l2_only_fast(
    *,
    date: str,
    symbol: str,
    bars_df: pd.DataFrame,
    l2_df: pd.DataFrame,
    config: dict[str, Any],
    artifact: dict[str, Any],
) -> list[RankedAction]:
    """Score an L2-only symbol-day by computing the feature frame once.

    The slower fallback recomputes rolling ML features for every minute bar. For
    artifacts that do not depend on causal bar-history features, a full-day L2
    feature frame plus causal searchsorted lookup matches the training cache shape
    and avoids repeatedly processing the same 300-second L2 windows.
    """
    bars_df = bars_df.sort_values("ts").reset_index(drop=True)
    if bars_df.empty:
        return []

    feature_cols = list(artifact["feature_columns"])
    action_specs = [ActionSpec(**spec) for spec in artifact["action_specs"]]
    model = artifact["model"]
    engine = AlphaBacktestEngine(config)
    engine._build_l2_index(l2_df)

    normalized = engine._normalize_ml_window(
        l2_df,
        symbol=str(symbol),
        date=str(date),
    )
    if normalized.empty:
        return []
    featured = compute_ml_features(normalized)
    featured["event_score"] = compute_event_score(featured)
    featured["ts_utc"] = pd.to_datetime(featured["ts_utc"], utc=True)
    featured = featured.sort_values("ts_utc").reset_index(drop=True)
    feature_ts_ns = featured["ts_utc"].dt.as_unit("ns").astype("int64").to_numpy()

    if any(column not in featured.columns for column in feature_cols):
        return []

    quality_context_keys = (
        *(column for column in ACTION_QUALITY_BASE_COLUMNS if column != "rank_score"),
        *ACTION_QUALITY_PRICE_COLUMNS,
        "session_bucket",
    )
    executable_last_ts = pd.Timestamp(bars_df["ts"].max())
    feature_rows: list[np.ndarray] = []
    candidates: list[tuple[pd.Timestamp, dict[str, float | None]]] = []

    for _, bar in bars_df.iterrows():
        ts = pd.Timestamp(bar["ts"])
        if ts >= executable_last_ts:
            continue
        cutoff = engine._decision_cutoff_utc(ts)
        cutoff_ns = int(cutoff.value)
        feature_idx = int(np.searchsorted(feature_ts_ns, cutoff_ns, side="right") - 1)
        if feature_idx < 0:
            continue
        latest_ts_ns = int(feature_ts_ns[feature_idx])
        if cutoff_ns - latest_ts_ns > engine._l2_staleness_seconds * 1_000_000_000:
            continue

        feature_view = featured.iloc[feature_idx]
        row = feature_view[feature_cols].to_numpy(dtype=np.float32, copy=True)
        if not np.isfinite(row).all():
            continue
        context = {
            column: _maybe_float(feature_view.get(column))
            for column in quality_context_keys
        }
        feature_rows.append(row)
        candidates.append((ts, context))

    if not feature_rows:
        return []

    score_matrix = model.predict_action_scores(np.vstack(feature_rows))
    ranked: list[RankedAction] = []
    for (ts, context), scores in zip(candidates, score_matrix):
        best_idx = int(np.argmax(scores))
        best_spec = action_specs[best_idx]
        ranked.append(
            RankedAction(
                date=date,
                symbol=str(symbol),
                timestamp=ts,
                side=SignalSide.LONG if best_spec.side == "long" else SignalSide.SHORT,
                hold_minutes=best_spec.hold_minutes,
                score=float(scores[best_idx]),
                context=context,
            )
        )
    return ranked


def _with_quality_score(action: RankedAction, score: float) -> RankedAction:
    return RankedAction(
        date=action.date,
        symbol=action.symbol,
        timestamp=action.timestamp,
        side=action.side,
        hold_minutes=action.hold_minutes,
        score=action.score,
        context=getattr(action, "context", None),
        quality_score=float(score),
    )


def _quality_feature_frame(
    ranked_actions: list[RankedAction],
    *,
    hold_minutes: list[int],
) -> tuple[pd.DataFrame, list[str]]:
    if not ranked_actions:
        return pd.DataFrame(), []
    rows: list[dict[str, Any]] = []
    for action in ranked_actions:
        context = getattr(action, "context", None) or {}
        rows.append(
            {
                "rank_score": float(action.score),
                "side": action.side.value,
                "hold_minutes": int(action.hold_minutes),
                **context,
            }
        )
    frame = pd.DataFrame(rows)
    return build_action_quality_features(frame, hold_minutes=hold_minutes)


def _annotate_quality_scores(
    ranked_actions: list[RankedAction],
    *,
    quality_artifact: dict[str, Any] | None,
) -> list[RankedAction]:
    if quality_artifact is None or not ranked_actions:
        return ranked_actions
    hold_minutes = quality_artifact.get("hold_minutes") or sorted(
        {int(action.hold_minutes) for action in ranked_actions}
    )
    feature_frame, _ = _quality_feature_frame(
        ranked_actions, hold_minutes=list(hold_minutes)
    )
    feature_columns = list(quality_artifact["feature_columns"])
    X = feature_frame.reindex(columns=feature_columns, fill_value=0.0).to_numpy(
        dtype=np.float32, copy=True
    )
    probabilities = quality_artifact["model"].predict_acceptance_proba(X)
    return [
        _with_quality_score(action, score)
        for action, score in zip(ranked_actions, probabilities)
    ]


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(numeric):
        return None
    return numeric


def _is_rejected_by_weak_context_gate(
    action: RankedAction,
    gate: WeakContextGate | None,
) -> bool:
    if gate is None:
        return False
    context = getattr(action, "context", None) or {}
    pressure_k = _maybe_float(context.get("pressure_k"))
    spread = _maybe_float(context.get("spread"))
    depth_imb_k = _maybe_float(context.get("depth_imb_k"))
    if pressure_k is None or spread is None or depth_imb_k is None:
        return False
    return (
        pressure_k <= gate.max_pressure_k
        and spread <= gate.max_spread
        and depth_imb_k <= gate.max_depth_imb_k
    )


def _score_day(
    payload: dict[str, Any],
    config: dict[str, Any],
    artifact: dict[str, Any],
) -> list[RankedAction]:
    bars_df = payload["bars"].sort_values(["ts", "symbol"]).reset_index(drop=True)
    l2_df = payload["l2"]
    ranked: list[RankedAction] = []
    l2_by_symbol = {}
    if l2_df is not None and not l2_df.empty:
        l2_by_symbol = {
            str(symbol): group.reset_index(drop=True)
            for symbol, group in l2_df.groupby("symbol", sort=False)
        }
    for symbol, symbol_bars in bars_df.groupby("symbol", sort=True):
        ranked.extend(
            _score_symbol(
                date=payload["date"],
                symbol=str(symbol),
                bars_df=symbol_bars,
                l2_df=l2_by_symbol.get(str(symbol)),
                config=config,
                artifact=artifact,
            )
        )
    return ranked


def _select_topk(
    ranked_actions: list[RankedAction],
    *,
    top_k: int,
    max_longs_per_day: int,
    min_score: float,
    weak_context_gate: WeakContextGate | None = None,
    quality_min_score: float | None = None,
) -> list[RankedAction]:
    ordered = sorted(
        ranked_actions, key=lambda row: (-row.score, row.timestamp, row.symbol)
    )
    selected: list[RankedAction] = []
    long_count = 0
    for row in ordered:
        if row.score < min_score:
            continue
        if _is_rejected_by_weak_context_gate(row, weak_context_gate):
            continue
        if quality_min_score is not None:
            quality_score = getattr(row, "quality_score", None)
            if quality_score is None or quality_score < quality_min_score:
                continue
        if len(selected) >= top_k:
            break
        if row.side == SignalSide.LONG and long_count >= max_longs_per_day:
            continue
        selected.append(row)
        if row.side == SignalSide.LONG:
            long_count += 1
    return sorted(selected, key=lambda row: (row.timestamp, row.symbol))


def _to_signal_event(action: RankedAction) -> SignalEvent:
    bounded_confidence = (
        float(np.clip(action.score, 0.0, 1.0)) if np.isfinite(action.score) else 0.5
    )
    return SignalEvent(
        symbol=action.symbol,
        timestamp=action.timestamp,
        side=action.side,
        confidence=bounded_confidence,
        features={"hold_minutes": action.hold_minutes, "rank_score": action.score},
        signal_name="MLSignal",
    )


def _sort_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        results,
        key=lambda current: (
            current["combined_total_pnl"],
            current["combined_profit_factor"],
            current["combined_trades_per_day"],
        ),
        reverse=True,
    )


def _write_outputs(
    *,
    results: list[dict[str, Any]],
    artifact_path: str,
    min_score: float,
    daily_top_ks: list[int],
    max_longs_per_day_values: list[int],
    output_dir: Path,
    weak_context_gate: WeakContextGate | None = None,
    quality_artifact_path: str | None = None,
    quality_min_score: float | None = None,
) -> dict[str, Any]:
    if not results:
        raise ValueError("results must not be empty")

    sorted_results = _sort_results(results)
    pd.DataFrame(sorted_results).to_csv(output_dir / "matrix_results.csv", index=False)
    summary = {
        "artifact_path": artifact_path,
        "min_score": min_score,
        "weak_context_gate": (
            {
                "max_pressure_k": weak_context_gate.max_pressure_k,
                "max_spread": weak_context_gate.max_spread,
                "max_depth_imb_k": weak_context_gate.max_depth_imb_k,
            }
            if weak_context_gate is not None
            else None
        ),
        "quality_artifact_path": quality_artifact_path,
        "quality_min_score": quality_min_score,
        "grid": {
            "daily_top_ks": daily_top_ks,
            "max_longs_per_day_values": max_longs_per_day_values,
        },
        "best_config": sorted_results[0],
        "configs_tested": len(sorted_results),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    lines = [
        "# Action Ranker Budget Matrix",
        "",
        f"- artifact: `{artifact_path}`",
        f"- weak context gate: `{summary['weak_context_gate']}`",
        f"- quality artifact: `{quality_artifact_path}`",
        f"- quality min score: `{quality_min_score}`",
        f"- configs tested: `{len(sorted_results)}`",
        f"- best config: `{sorted_results[0]}`",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")
    return summary


def _load_existing_results(output_dir: Path) -> list[dict[str, Any]]:
    matrix_path = output_dir / "matrix_results.csv"
    if not matrix_path.exists():
        return []
    frame = pd.read_csv(matrix_path)
    return frame.to_dict(orient="records")


def _ranked_cache_path(output_dir: Path, window_label: str, date: str) -> Path:
    safe_window = "".join(
        char if char.isalnum() or char in ("-", "_") else "_" for char in window_label
    )
    safe_date = "".join(
        char if char.isalnum() or char in ("-", "_") else "_" for char in date
    )
    return output_dir / "scored_action_cache" / f"{safe_window}_{safe_date}.joblib"


def _symbol_ranked_cache_path(
    output_dir: Path, window_label: str, date: str, symbol: str
) -> Path:
    safe_window = "".join(
        char if char.isalnum() or char in ("-", "_") else "_" for char in window_label
    )
    safe_date = "".join(
        char if char.isalnum() or char in ("-", "_") else "_" for char in date
    )
    safe_symbol = "".join(
        char if char.isalnum() or char in ("-", "_") else "_" for char in symbol
    )
    return (
        output_dir
        / "scored_action_cache"
        / safe_window
        / safe_date
        / f"{safe_symbol}.joblib"
    )


def _load_or_build_ranked_actions(
    *,
    payload: dict[str, Any],
    window_label: str,
    config: dict[str, Any],
    artifact: dict[str, Any],
    output_dir: Path,
    score_cache: bool,
    cache_dir: Path | None = None,
) -> list[RankedAction]:
    cache_root = cache_dir if cache_dir is not None else output_dir
    cache_path = _ranked_cache_path(cache_root, window_label, payload["date"])
    if score_cache and cache_path.exists():
        logger.info(
            "Loading scored-action cache for %s %s", window_label, payload["date"]
        )
        return joblib.load(cache_path)

    bars_df = payload["bars"].sort_values(["symbol", "ts"]).reset_index(drop=True)
    l2_df = payload["l2"]
    l2_by_symbol = {}
    if l2_df is not None and not l2_df.empty:
        l2_by_symbol = {
            str(symbol): group.reset_index(drop=True)
            for symbol, group in l2_df.groupby("symbol", sort=False)
        }

    ranked: list[RankedAction] = []
    for symbol, symbol_bars in bars_df.groupby("symbol", sort=True):
        symbol_key = str(symbol)
        symbol_cache_path = _symbol_ranked_cache_path(
            cache_root,
            window_label,
            payload["date"],
            symbol_key,
        )
        if score_cache and symbol_cache_path.exists():
            logger.info(
                "Loading scored-action cache for %s %s %s",
                window_label,
                payload["date"],
                symbol_key,
            )
            symbol_ranked = joblib.load(symbol_cache_path)
        else:
            symbol_ranked = _score_symbol(
                date=payload["date"],
                symbol=symbol_key,
                bars_df=symbol_bars,
                l2_df=l2_by_symbol.get(symbol_key),
                config=config,
                artifact=artifact,
            )
            if score_cache:
                symbol_cache_path.parent.mkdir(parents=True, exist_ok=True)
                tmp_path = symbol_cache_path.with_suffix(".tmp")
                joblib.dump(symbol_ranked, tmp_path)
                tmp_path.replace(symbol_cache_path)
        ranked.extend(symbol_ranked)

    ranked = sorted(ranked, key=lambda row: (row.timestamp, row.symbol))
    if score_cache and ranked:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_suffix(".tmp")
        joblib.dump(ranked, tmp_path)
        tmp_path.replace(cache_path)
    return ranked


def run_matrix(
    *,
    artifact_path: str,
    windows: list[WindowSpec],
    daily_top_ks: list[int],
    max_longs_per_day_values: list[int],
    min_score: float,
    output_dir: Path,
    bar_source: str = "polygon",
    resume: bool = True,
    score_cache: bool = True,
    weak_context_gate: WeakContextGate | None = None,
    cache_dir: Path | None = None,
    quality_artifact_path: str | None = None,
    quality_min_score: float | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
    config = _base_config(bar_source)
    artifact = joblib.load(artifact_path)
    quality_artifact = (
        joblib.load(quality_artifact_path) if quality_artifact_path else None
    )
    if min_score is None:
        objective = str(artifact.get("objective", "logistic"))
        min_score = 0.0 if objective == "edge_regression" else 0.50
    if quality_artifact is not None and quality_min_score is None:
        quality_min_score = float(quality_artifact.get("acceptance_threshold", 0.50))
    payloads_by_window = {
        window.label: _load_daily_payloads(window.start, window.end, config)
        for window in windows
    }
    ranked_actions_by_window: dict[str, dict[str, list[RankedAction]]] = {}
    for window in windows:
        ranked_actions_by_window[window.label] = {}
        for payload in payloads_by_window[window.label]:
            ranked = _load_or_build_ranked_actions(
                payload=payload,
                window_label=window.label,
                config=config,
                artifact=artifact,
                output_dir=output_dir,
                score_cache=score_cache,
                cache_dir=cache_dir,
            )
            ranked_actions_by_window[window.label][payload["date"]] = (
                _annotate_quality_scores(
                    ranked,
                    quality_artifact=quality_artifact,
                )
            )

    active_days = sum(len(payloads) for payloads in payloads_by_window.values())
    results = _load_existing_results(output_dir) if resume else []
    completed_configs = {
        _config_key(int(row["top_k"]), int(row["max_longs_per_day"])) for row in results
    }

    for top_k in daily_top_ks:
        for max_longs in max_longs_per_day_values:
            config_key = _config_key(top_k, max_longs)
            if config_key in completed_configs:
                logger.info(
                    "Skipping completed action-ranker config top_k=%s max_longs=%s",
                    top_k,
                    max_longs,
                )
                continue
            logger.info(
                "Running action-ranker config top_k=%s max_longs=%s", top_k, max_longs
            )
            row = {
                "top_k": top_k,
                "max_longs_per_day": max_longs,
                "min_score": min_score,
                "combined_trades": 0,
                "combined_total_pnl": 0.0,
                "combined_gross_profit": 0.0,
                "combined_gross_loss": 0.0,
                "active_days": active_days,
            }
            for window in windows:
                window_trades = 0
                window_pnl = 0.0
                window_gp = 0.0
                window_gl = 0.0
                for payload in payloads_by_window[window.label]:
                    ranked = ranked_actions_by_window[window.label][payload["date"]]
                    selected = _select_topk(
                        ranked,
                        top_k=top_k,
                        max_longs_per_day=max_longs,
                        min_score=min_score,
                        weak_context_gate=weak_context_gate,
                        quality_min_score=quality_min_score,
                    )
                    if not selected:
                        continue
                    engine = AlphaBacktestEngine(config)
                    signal = ScheduledActionSignal(
                        config, [_to_signal_event(item) for item in selected]
                    )
                    result = engine.run(
                        payload["bars"], l2_df=payload["l2"], signals=[signal]
                    )
                    metrics = compute_all_metrics(
                        result, initial_capital=config["initial_capital"]
                    )
                    window_trades += int(metrics["num_trades"])
                    window_pnl += float(metrics["total_pnl"])
                    for trade in result.trades:
                        pnl = float(trade.pnl)
                        if pnl > 0:
                            window_gp += pnl
                        elif pnl < 0:
                            window_gl += abs(pnl)

                row[f"{window.label}_trades"] = window_trades
                row[f"{window.label}_pnl"] = window_pnl
                row[f"{window.label}_profit_factor"] = (
                    window_gp / window_gl
                    if window_gl > 0
                    else (999.0 if window_gp > 0 else 0.0)
                )
                row["combined_trades"] += window_trades
                row["combined_total_pnl"] += window_pnl
                row["combined_gross_profit"] += window_gp
                row["combined_gross_loss"] += window_gl

            row["combined_total_return_pct"] = (
                row["combined_total_pnl"] / 100000.0 * 100.0
            )
            row["combined_profit_factor"] = (
                row["combined_gross_profit"] / row["combined_gross_loss"]
                if row["combined_gross_loss"] > 0
                else (999.0 if row["combined_gross_profit"] > 0 else 0.0)
            )
            row["combined_trades_per_day"] = (
                row["combined_trades"] / active_days if active_days else 0.0
            )
            row["trade_budget_pass"] = 3.0 <= row["combined_trades_per_day"] <= 5.0
            results.append(row)
            completed_configs.add(config_key)
            _write_outputs(
                results=results,
                artifact_path=artifact_path,
                min_score=min_score,
                daily_top_ks=daily_top_ks,
                max_longs_per_day_values=max_longs_per_day_values,
                output_dir=output_dir,
                weak_context_gate=weak_context_gate,
                quality_artifact_path=quality_artifact_path,
                quality_min_score=quality_min_score,
            )

    return _write_outputs(
        results=results,
        artifact_path=artifact_path,
        min_score=min_score,
        daily_top_ks=daily_top_ks,
        max_longs_per_day_values=max_longs_per_day_values,
        output_dir=output_dir,
        weak_context_gate=weak_context_gate,
        quality_artifact_path=quality_artifact_path,
        quality_min_score=quality_min_score,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run action-ranker budget matrix")
    parser.add_argument(
        "--artifact-path",
        default="models/action_ranker_logistic_2026-03-17.pkl",
    )
    parser.add_argument(
        "--windows",
        default="w1:2026-03-06:2026-03-11,w2:2026-03-12:2026-03-13",
    )
    parser.add_argument("--daily-top-ks", default="3,4,5")
    parser.add_argument("--max-longs-per-day-values", default="1,2,3")
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument("--bar-source", choices=["gold", "polygon"], default="polygon")
    parser.add_argument(
        "--output-dir",
        default="output/ml_action_ranker_budget_matrix_2026-03-17",
    )
    parser.add_argument(
        "--no-score-cache",
        action="store_true",
        help="Disable on-disk scored-action cache under the output directory.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore any existing matrix_results.csv in the output directory.",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Optional shared cache directory for scored actions.",
    )
    parser.add_argument(
        "--quality-artifact-path",
        default=None,
        help="Optional accept/reject quality-model artifact applied before top-K selection.",
    )
    parser.add_argument(
        "--quality-min-score",
        type=float,
        default=None,
        help="Minimum quality-model acceptance probability required for selection.",
    )
    parser.add_argument(
        "--weak-context-max-pressure-k",
        type=float,
        default=None,
        help="Reject actions only when pressure_k, spread, and depth_imb_k are all in a weak regime.",
    )
    parser.add_argument(
        "--weak-context-max-spread",
        type=float,
        default=None,
        help="Maximum spread for the weak-context rejection rule.",
    )
    parser.add_argument(
        "--weak-context-max-depth-imb-k",
        type=float,
        default=None,
        help="Maximum depth_imb_k for the weak-context rejection rule.",
    )
    args = parser.parse_args()
    weak_context_gate = None
    weak_context_values = (
        args.weak_context_max_pressure_k,
        args.weak_context_max_spread,
        args.weak_context_max_depth_imb_k,
    )
    if any(value is not None for value in weak_context_values):
        if not all(value is not None for value in weak_context_values):
            raise ValueError(
                "weak-context gate requires all of --weak-context-max-pressure-k, "
                "--weak-context-max-spread, and --weak-context-max-depth-imb-k"
            )
        weak_context_gate = WeakContextGate(
            max_pressure_k=float(args.weak_context_max_pressure_k),
            max_spread=float(args.weak_context_max_spread),
            max_depth_imb_k=float(args.weak_context_max_depth_imb_k),
        )
    summary = run_matrix(
        artifact_path=args.artifact_path,
        windows=_parse_windows(args.windows),
        daily_top_ks=_parse_int_list(args.daily_top_ks),
        max_longs_per_day_values=_parse_int_list(args.max_longs_per_day_values),
        min_score=args.min_score,
        output_dir=Path(args.output_dir),
        bar_source=args.bar_source,
        resume=not args.no_resume,
        score_cache=not args.no_score_cache,
        weak_context_gate=weak_context_gate,
        cache_dir=Path(args.cache_dir) if args.cache_dir else None,
        quality_artifact_path=args.quality_artifact_path,
        quality_min_score=args.quality_min_score,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
