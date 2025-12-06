"""Short-window policy sweep helper for big-move integration."""

from __future__ import annotations

import argparse
import copy
import itertools
import json
import logging
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from extensions.intraday_ml.backtest import intraday_ml_run_backtest
from extensions.intraday_ml.policy.rejection_reasons import REJECTION_REASON_TO_COLUMN
from extensions.intraday_ml.utils.heartbeat import HeartbeatLogger
from extensions.intraday_ml_policies.intraday_ml_decision_policy import IntradayMLDecisionPolicy

DEFAULT_SIGNALS_PATH = (
    "artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet"
)
DEFAULT_BARS_PATH = "artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet"

LOGGER = logging.getLogger(__name__)


def sweep_policy_configs(
    signals: pd.DataFrame,
    bars: pd.DataFrame,
    base_policy_config: dict[str, Any],
    grid: dict[str, Any] | None,
    *,
    backtest_config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Run a lightweight policy sweep and return a metrics DataFrame."""
    param_sets = expand_parameter_grid(grid or {})
    results = []
    total = len(param_sets)
    for sweep_id, overrides in enumerate(param_sets):
        LOGGER.info("Running sweep %d/%d with overrides=%s", sweep_id + 1, total, overrides)
        policy_cfg = copy.deepcopy(base_policy_config)
        apply_overrides(policy_cfg, overrides)
        policy = IntradayMLDecisionPolicy(policy_cfg)
        sweep_signals = _prepare_signals_for_policy_mode(signals, policy_cfg.get("policy_mode"))
        sweep_signals = sweep_signals.copy()
        required_columns = (
            policy.get_required_feature_columns()
            if hasattr(policy, "get_required_feature_columns")
            else set()
        )
        sweep_signals = _ensure_required_columns(
            sweep_signals,
            bars,
            required_columns=required_columns,
        )
        orders, rejections = policy.process_signals(sweep_signals)
        rejection_counts = policy.get_rejection_reason_counts()
        backtest_cfg = copy.deepcopy(backtest_config or {})
        artifacts = intraday_ml_run_backtest(bars, orders, cfg=backtest_cfg)

        entry_orders = orders[orders["reason"] == "trade"] if not orders.empty else orders
        trade_count = len(entry_orders)
        trading_days = max(1, _count_trading_days(bars))
        trades_per_day = trade_count / trading_days

        trades_df = artifacts.get("trades")
        hit_rate = float("nan")
        avg_r = float("nan")
        if isinstance(trades_df, pd.DataFrame) and not trades_df.empty:
            r_values = trades_df["r_multiple"]
            avg_r = float(r_values.mean())
            hit_rate = float((r_values > 0).mean())

        metrics = artifacts.get("metrics", {})
        metrics_prefixed = {f"metric_{key}": value for key, value in metrics.items()}
        row = {
            "sweep_id": sweep_id,
            "entries": trade_count,
            "rejections": len(rejections),
            "trades_per_day": trades_per_day,
            "avg_r_multiple": avg_r,
            "hit_rate": hit_rate,
            "rejection_counts": dict(rejection_counts),
        }
        for reason_key, column_name in REJECTION_REASON_TO_COLUMN.items():
            row[column_name] = int(rejection_counts.get(reason_key, 0))
        row.update(metrics_prefixed)
        for key, value in overrides.items():
            row[f"param_{key}"] = value
        results.append(row)

    return pd.DataFrame(results)


def expand_parameter_grid(grid: dict[str, Any]) -> list[dict[str, Any]]:
    """Create cartesian product of grid values."""
    if not grid:
        return [{}]
    items: list[tuple[str, list[Any]]] = []
    for key, value in grid.items():
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            values = list(value)
        else:
            values = [value]
        items.append((key, values))

    combinations = []
    for combo in itertools.product(*(values for _, values in items)):
        overrides = {key: value for (key, _), value in zip(items, combo, strict=False)}
        combinations.append(overrides)
    return combinations


def apply_overrides(config: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Apply dotted-key overrides to a configuration dictionary."""
    for dotted_key, value in overrides.items():
        parts = dotted_key.split(".")
        target = config
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    return config


def load_frame(path: str) -> pd.DataFrame:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if file_path.suffix == ".parquet":
        return pd.read_parquet(file_path)
    if file_path.suffix in {".csv", ".txt"}:
        return pd.read_csv(file_path)
    raise ValueError(f"Unsupported file format for {file_path}")


def load_structured_config(path: str) -> dict[str, Any]:
    file_path = Path(path)
    with open(file_path) as f:
        if file_path.suffix in {".yaml", ".yml"}:
            return yaml.safe_load(f) or {}
        return json.load(f)


def _count_trading_days(bars: pd.DataFrame) -> int:
    if bars.empty or "ts" not in bars.columns:
        return 0
    days = pd.to_datetime(bars["ts"], utc=True).dt.floor("D").unique()
    return len(days)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run short-window policy sweeps.")
    parser.add_argument(
        "--signals",
        default=DEFAULT_SIGNALS_PATH,
        help=(
            "Path to policy signal parquet/csv (defaults to the big-move signals "
            "generated via score_bigmove_oos)."
        ),
    )
    parser.add_argument(
        "--bars",
        default=DEFAULT_BARS_PATH,
        help="Path to bars parquet/csv matching the signals (defaults to the Phase A SIP OOS bars).",
    )
    parser.add_argument("--policy-config", required=True, help="Policy config JSON path")
    parser.add_argument("--grid", required=True, help="Grid config (JSON/YAML) path")
    parser.add_argument("--backtest-config", help="Optional backtest config YAML/JSON")
    parser.add_argument("--output", help="Optional CSV output path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    with HeartbeatLogger("policy_sweep", interval_seconds=60):
        LOGGER.info("Loading signals from %s", args.signals)
        signals = load_frame(args.signals)
        LOGGER.info("Loading bars from %s", args.bars)
        bars = load_frame(args.bars)
        with open(args.policy_config) as f:
            policy_config = json.load(f)
        grid_config = load_structured_config(args.grid)
        backtest_cfg = load_structured_config(args.backtest_config) if args.backtest_config else {}

        results = sweep_policy_configs(
            signals,
            bars,
            base_policy_config=policy_config,
            grid=grid_config,
            backtest_config=backtest_cfg,
        )

        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            results.to_csv(output_path, index=False)
            LOGGER.info("✅ Policy sweep results saved to %s", output_path)
        else:
            print(results)


def _prepare_signals_for_policy_mode(signals: pd.DataFrame, policy_mode: str | None) -> pd.DataFrame:
    """Ensure required columns exist for special policy modes."""
    mode = (policy_mode or "baseline").lower()
    if mode != "bigmove":
        return signals
    required = {"prob_bigmove", "prob_bigmove_long"}
    if required.issubset(signals.columns):
        return signals
    fallback = signals.copy()
    prob_long = pd.to_numeric(fallback.get("prob_long"), errors="coerce").fillna(0.0)
    prob_short = pd.to_numeric(fallback.get("prob_short"), errors="coerce").fillna(0.0)
    total = prob_long + prob_short
    total = total.replace(0, 1.0)
    fallback["prob_bigmove"] = (prob_long + prob_short).clip(0.0, 1.0)
    fallback["prob_bigmove_long"] = (prob_long / total).clip(0.0, 1.0)
    fallback["prob_bigmove_short"] = (prob_short / total).clip(0.0, 1.0)
    fallback["expected_r_bigmove"] = 2.0
    return fallback


def _ensure_required_columns(
    signals: pd.DataFrame,
    bars: pd.DataFrame,
    *,
    required_columns: set[str] | Iterable[str] | None,
) -> pd.DataFrame:
    """Augment signals with any required feature columns from the bars frame."""
    requirements = set(required_columns or [])
    requirements.discard("ts")
    requirements.discard("timestamp")
    requirements.discard("symbol")
    missing = [col for col in sorted(requirements) if col not in signals.columns]
    if not missing:
        return signals
    if not {"ts", "symbol"}.issubset(bars.columns):
        raise KeyError("Bars frame must contain 'ts' and 'symbol' columns for augmentation.")
    missing_in_bars = [col for col in missing if col not in bars.columns]
    if missing_in_bars:
        raise KeyError(f"Bars frame missing required feature columns: {missing_in_bars}")
    subset = bars[["ts", "symbol"] + missing].copy()
    merged = pd.merge(
        signals,
        subset,
        on=["ts", "symbol"],
        how="left",
        validate="many_to_one",
    )
    return merged


if __name__ == "__main__":
    main()
