"""Reporting helpers for intraday ML experiments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from extensions.intraday_ml_monitoring.metrics import (
    MetricsCalculator as MonitoringMetricsCalculator,
)


class ArtifactReader:
    """Read backtest artifacts stored in experiment folders."""

    def __init__(self, experiment_dir: str | Path):
        self.experiment_dir = Path(experiment_dir)
        if not self.experiment_dir.exists():
            raise ValueError("Experiment directory not found")

    def _variant_path(self, variant: str) -> Path:
        return self.experiment_dir / f"variant_{variant}"

    def read_variant_artifacts(self, variant: str) -> dict[str, Any]:
        """Load parquet artifacts and metrics for a single variant."""
        variant_path = self._variant_path(variant)
        if not variant_path.exists():
            raise ValueError("Variant directory not found")

        artifacts: dict[str, Any] = {}
        parquet_artifacts = [
            "signals",
            "orders",
            "fills",
            "positions",
            "equity",
            "trades",
            "risk_rejects",
            "allocation_log",
        ]
        for name in parquet_artifacts:
            file_path = variant_path / f"{name}.parquet"
            if file_path.exists():
                artifacts[name] = pd.read_parquet(file_path)
            else:
                artifacts[name] = pd.DataFrame()

        metrics_path = variant_path / "metrics.json"
        if metrics_path.exists():
            with open(metrics_path) as handle:
                artifacts["metrics"] = json.load(handle)
        else:
            artifacts["metrics"] = MetricsCalculator.calculate_basic_metrics(artifacts)

        return artifacts

    def read_manifest(self) -> dict[str, Any]:
        """Return experiment manifest."""
        path = self.experiment_dir / "manifest.json"
        if not path.exists():
            raise ValueError("Manifest not found")
        with open(path) as handle:
            return json.load(handle)

    def read_inputs_checksum(self) -> dict[str, Any]:
        """Return inputs checksum document."""
        path = self.experiment_dir / "inputs_checksum.json"
        if not path.exists():
            raise ValueError("Inputs checksum not found")
        with open(path) as handle:
            return json.load(handle)


class ReportingMetricsCalculator(MonitoringMetricsCalculator):
    """Concrete calculator that exposes static convenience wrappers."""

    @staticmethod
    def calculate_basic_metrics(artifacts: dict[str, Any]) -> dict[str, float]:
        return MonitoringMetricsCalculator.calculate_basic_metrics(artifacts)

    @staticmethod
    def calculate_risk_metrics(artifacts: dict[str, Any]) -> dict[str, float]:
        return MonitoringMetricsCalculator.calculate_risk_metrics(artifacts)

    @staticmethod
    def calculate_execution_metrics(artifacts: dict[str, Any]) -> dict[str, float]:
        return MonitoringMetricsCalculator.calculate_execution_metrics(artifacts)


MetricsCalculator = ReportingMetricsCalculator


@dataclass
class SummaryTable:
    """Lightweight structure holding table rows."""

    rows: list[dict[str, Any]]


class ABComparator:
    """Compare experiment variants."""

    def __init__(self, experiment_dir: str | Path):
        self.reader = ArtifactReader(experiment_dir)

    def compare_variants(self, variants: list[str]) -> pd.DataFrame:
        """Return DataFrame with basic metrics per variant."""
        records = []
        index = []
        for variant in variants:
            try:
                artifacts = self.reader.read_variant_artifacts(variant)
            except ValueError:
                continue

            metrics = MetricsCalculator.calculate_basic_metrics(artifacts)
            records.append(metrics)
            index.append(variant)

        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records, index=index)
        return df

    def calculate_differences(self, comparison_df: pd.DataFrame, baseline: str) -> pd.DataFrame:
        """Compute absolute and percentage differences relative to baseline."""
        if baseline not in comparison_df.index:
            raise ValueError(f"Baseline variant '{baseline}' not found")

        baseline_row = comparison_df.loc[baseline]
        diff_df = comparison_df.copy()
        for column in comparison_df.columns:
            diff_df[f"{column}_diff"] = comparison_df[column] - baseline_row[column]
            baseline_value = baseline_row[column]
            if baseline_value == 0:
                diff_df[f"{column}_pct_change"] = 0.0
            else:
                diff_df[f"{column}_pct_change"] = diff_df[f"{column}_diff"] / baseline_value * 100.0
        return diff_df

    def generate_summary_table(self, comparison_df: pd.DataFrame) -> SummaryTable:
        """Create simple summary table from comparison DataFrame."""
        rows = []
        for variant, row in comparison_df.iterrows():
            rows.append({"variant": variant, **row.to_dict()})
        return SummaryTable(rows=rows)


def _json_safe(value: Any) -> Any:
    """Convert nested objects to JSON-serialisable structures."""

    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return value.total_seconds()
    if isinstance(value, (pd.Series, pd.Index)):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, pd.DataFrame):
        return {_json_safe(k): _json_safe(v) for k, v in value.to_dict(orient="series").items()}
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return value.item()
        except Exception:  # pragma: no cover - best effort fallback
            return str(value)
    return value


def build_run_summary(
    *,
    metrics: dict[str, Any],
    orders_df: pd.DataFrame,
    rejections_df: pd.DataFrame,
    policy_config: dict[str, Any],
    artifacts_dir: Path,
    feature_coverage_path: Path | None,
    timestamp: datetime,
) -> dict[str, Any]:
    """Create a concise run summary for downstream reporting."""

    entry_counts = (
        orders_df[orders_df["reason"] == "trade"]["side"].value_counts().to_dict()
        if not orders_df.empty
        else {}
    )
    order_reason_counts = (
        orders_df["reason"].value_counts().to_dict() if not orders_df.empty else {}
    )
    rejection_counts = (
        rejections_df["reason"].value_counts().head(10).to_dict() if not rejections_df.empty else {}
    )

    summary = {
        "status": "success",
        "timestamp": timestamp.isoformat(),
        "artifacts_dir": str(artifacts_dir),
        "policy": {
            "order_qty": policy_config.get("order_qty"),
            "prob_threshold_long": policy_config.get("prob_threshold_long"),
            "prob_threshold_short": policy_config.get("prob_threshold_short"),
            "score_margin": policy_config.get("score_margin"),
            "min_directional_gap": policy_config.get("min_directional_gap"),
            "cooldown_minutes": policy_config.get("cooldown_minutes"),
            "max_hold_minutes": policy_config.get("max_hold_minutes"),
            "target_trades_min": policy_config.get("target_trades_min"),
            "target_trades_max": policy_config.get("target_trades_max"),
        },
        "orders": {
            "total": int(len(orders_df)),
            "entry_side_counts": entry_counts,
            "reason_counts": order_reason_counts,
        },
        "rejections": {
            "total": int(len(rejections_df)),
            "top_reasons": rejection_counts,
        },
        "performance": _json_safe(metrics),
    }

    entry_orders = (
        orders_df[orders_df["reason"] == "trade"].copy() if not orders_df.empty else pd.DataFrame()
    )
    entries_by_symbol: dict[str, int] = {}
    daily_frequency: dict[str, Any] = {}
    if not entry_orders.empty:
        entries_by_symbol = (
            entry_orders["symbol"].value_counts().sort_values(ascending=False).to_dict()
        )
        session_tz = policy_config.get("session_timezone", "America/New_York")
        timestamps = pd.to_datetime(entry_orders["timestamp"], utc=True, errors="coerce")
        session_dates = timestamps.dt.tz_convert(session_tz).dt.date
        session_dates = pd.Series(session_dates).dropna()
        if not session_dates.empty:
            per_day = session_dates.value_counts().sort_index()
            target_min = policy_config.get("target_trades_min", 3)
            target_max = policy_config.get("target_trades_max", 5)
            within_target = int(per_day.between(target_min, target_max).sum())
            daily_frequency = {
                "avg_per_day": float(per_day.mean()),
                "min_per_day": int(per_day.min()),
                "max_per_day": int(per_day.max()),
                "days_observed": int(len(per_day)),
                "within_target_days": within_target,
                "target_range": [target_min, target_max],
                "per_day_counts": {str(day): int(count) for day, count in per_day.items()},
            }
    summary["orders"]["entries_by_symbol"] = entries_by_symbol
    summary["orders"]["daily_frequency"] = daily_frequency

    if feature_coverage_path is not None:
        summary["feature_coverage"] = str(feature_coverage_path)

    return summary


def write_run_summary(summary: dict[str, Any], output_path: Path | str) -> None:
    output_path = Path(output_path)
    output_path.write_text(json.dumps(_json_safe(summary), indent=2))


def _list_variants(experiment_dir: Path) -> list[str]:
    return sorted(
        {
            path.name.replace("variant_", "")
            for path in experiment_dir.glob("variant_*")
            if path.is_dir()
        }
    )


def generate_experiment_report(
    experiment_dir: str | Path, output_format: str = "console"
) -> dict[str, Any] | None:
    """Generate experiment report in the requested format."""
    exp_dir = Path(experiment_dir)
    if not exp_dir.exists():
        raise ValueError("Experiment directory not found")

    reader = ArtifactReader(exp_dir)
    manifest = reader.read_manifest()
    variants = _list_variants(exp_dir)
    if not variants:
        raise ValueError("No variants found")

    comparator = ABComparator(exp_dir)
    comparison_df = comparator.compare_variants(variants)
    diff_df = comparator.calculate_differences(comparison_df, variants[0])
    summary_table = comparator.generate_summary_table(comparison_df)

    report = {
        "experiment_info": manifest,
        "checksum_validation": manifest.get("checksum_validation"),
        "inputs_checksum": None,
        "variant_comparison": comparison_df.to_dict(),
        "differences": diff_df.to_dict(),
        "summary_metrics": summary_table.rows,
    }

    try:
        report["inputs_checksum"] = reader.read_inputs_checksum()
    except ValueError:
        report["inputs_checksum"] = None

    if output_format == "console":
        print(f"Experiment: {manifest.get('experiment_name', 'unknown')}")
        for row in summary_table.rows:
            print(f"Variant {row['variant']}: trades={row.get('trades', 0)}")
        return None
    if output_format == "json":
        return report
    if output_format == "dict":
        return report

    raise ValueError(f"Unsupported output format: {output_format}")


def summarize_round_trip_trades(
    fills_df: pd.DataFrame | None, orders_df: pd.DataFrame | None
) -> pd.DataFrame:
    """Return per-trade round-trip summary derived from fills + policy orders."""
    columns = [
        "symbol",
        "direction",
        "entry_ts",
        "exit_ts",
        "entry_price",
        "exit_price",
        "qty",
        "entry_order_id",
        "exit_order_id",
        "entry_reason",
        "exit_reason",
        "gross_pnl",
        "fees",
        "net_pnl",
        "duration_minutes",
    ]
    if fills_df is None or fills_df.empty:
        return pd.DataFrame(columns=columns)

    fills = fills_df.copy()
    if "timestamp" in fills.columns and not pd.api.types.is_datetime64_any_dtype(
        fills["timestamp"]
    ):
        fills["timestamp"] = pd.to_datetime(fills["timestamp"], utc=True, errors="coerce")

    order_meta: dict[str, dict[str, Any]] = {}
    if orders_df is not None and not orders_df.empty and "order_id" in orders_df.columns:
        meta_cols = [
            col
            for col in [
                "symbol",
                "reason",
                "strategy",
                "strategy_detail",
                "signal_timestamp",
                "execution_timestamp",
                "side",
            ]
            if col in orders_df.columns
        ]
        order_meta = (
            orders_df.set_index("order_id")[meta_cols].to_dict("index")  # type: ignore[arg-type]
        )

    fills = fills.sort_values("timestamp").reset_index(drop=True)
    open_positions: dict[str, dict[str, Any]] = {}
    round_trips: list[dict[str, Any]] = []

    for fill in fills.itertuples(index=False):
        order_id = getattr(fill, "order_id", None)
        symbol = getattr(fill, "symbol", None)
        side = str(getattr(fill, "side", "")).upper()
        qty = float(getattr(fill, "quantity", 0) or 0)
        timestamp = getattr(fill, "timestamp", None)
        price = float(getattr(fill, "price", 0) or 0.0)
        commission = float(getattr(fill, "commission", 0) or 0.0)
        if not symbol or qty <= 0 or timestamp is None:
            continue

        metadata = order_meta.get(order_id or "", {})
        reason = metadata.get("reason") or metadata.get("strategy_detail") or "unknown"

        direction = "LONG" if side == "BUY" else "SHORT"
        position = open_positions.get(symbol)

        if position is None:
            open_positions[symbol] = {
                "direction": direction,
                "entry_ts": timestamp,
                "entry_price": price,
                "qty": qty,
                "order_id": order_id,
                "reason": reason,
                "fees": commission,
            }
            continue

        if position["direction"] == direction:
            # Unexpected add-on; reset the position with the latest fill.
            open_positions[symbol] = {
                "direction": direction,
                "entry_ts": timestamp,
                "entry_price": price,
                "qty": qty,
                "order_id": order_id,
                "reason": reason,
                "fees": commission,
            }
            continue

        trade_qty = min(qty, position["qty"])
        if trade_qty <= 0:
            open_positions.pop(symbol, None)
            continue

        if position["direction"] == "LONG":
            gross_pnl = (price - position["entry_price"]) * trade_qty
        else:
            gross_pnl = (position["entry_price"] - price) * trade_qty

        fees = position.get("fees", 0.0) + commission
        net_pnl = gross_pnl - fees
        duration = None
        if isinstance(timestamp, pd.Timestamp) and isinstance(position["entry_ts"], pd.Timestamp):
            duration = (timestamp - position["entry_ts"]).total_seconds() / 60.0

        round_trips.append(
            {
                "symbol": symbol,
                "direction": position["direction"],
                "entry_ts": position["entry_ts"],
                "exit_ts": timestamp,
                "entry_price": position["entry_price"],
                "exit_price": price,
                "qty": trade_qty,
                "entry_order_id": position.get("order_id"),
                "exit_order_id": order_id,
                "entry_reason": position.get("reason"),
                "exit_reason": reason,
                "gross_pnl": gross_pnl,
                "fees": fees,
                "net_pnl": net_pnl,
                "duration_minutes": duration,
            }
        )
        open_positions.pop(symbol, None)

    if not round_trips:
        return pd.DataFrame(columns=columns)

    summary_df = pd.DataFrame(round_trips)
    summary_df = summary_df[columns]
    return summary_df


def write_trade_report(
    trade_df: pd.DataFrame,
    output_path: Path | str,
    *,
    max_rows: int = 50,
    target_range: tuple[float, float] = (3.0, 5.0),
) -> None:
    """Write a concise markdown report for per-trade outcomes."""
    output_path = Path(output_path)
    lines = [
        "# Trade Summary",
        "",
        f"- total_trades: {len(trade_df)}",
        f"- avg_duration_minutes: {trade_df['duration_minutes'].mean():.2f}"
        if not trade_df["duration_minutes"].isna().all()
        else "- avg_duration_minutes: n/a",
        "",
    ]
    symbol_counts = (
        trade_df["symbol"].value_counts().sort_values(ascending=False).to_dict()
        if not trade_df.empty
        else {}
    )
    lines.append("- trades_by_symbol:")
    if symbol_counts:
        for symbol, count in symbol_counts.items():
            lines.append(f"  - {symbol}: {int(count)}")
    else:
        lines.append("  - none")

    target_min, target_max = target_range
    lines.append(f"- trade_rate_target: {target_min:.1f} to {target_max:.1f} trades/day")
    entry_ts = pd.to_datetime(trade_df["entry_ts"], utc=True, errors="coerce")
    if not entry_ts.isna().all():
        session_dates = entry_ts.dt.tz_convert("America/New_York").dt.date
        per_day = pd.Series(session_dates).value_counts().sort_index()
        if not per_day.empty:
            within_target = int(per_day.between(target_min, target_max).sum())
            lines.append(
                f"- avg_trades_per_day: {per_day.mean():.2f} "
                f"(days={len(per_day)}, within_target={within_target})"
            )
        else:
            lines.append("- avg_trades_per_day: n/a")
    else:
        lines.append("- avg_trades_per_day: n/a")
    lines.append("")
    for idx, row in trade_df.head(max_rows).iterrows():
        entry_ts = row["entry_ts"]
        exit_ts = row["exit_ts"]
        duration = row["duration_minutes"]
        duration_txt = "n/a"
        if duration is not None:
            duration_txt = f"{duration:.1f}m"
        lines.append(
            f"- {row['symbol']} {row['direction']}: "
            f"enter {entry_ts} @ {row['entry_price']:.4f} "
            f"(reason={row['entry_reason']}), exit {exit_ts} @ {row['exit_price']:.4f} "
            f"(reason={row['exit_reason']}), pnl={row['net_pnl']:.4f}, duration={duration_txt}"
        )
    output_path.write_text("\n".join(lines))


def read_single_run_metrics(run_dir: str | Path) -> dict[str, Any]:
    """Return metrics for a single run directory."""
    run_path = Path(run_dir)
    if not run_path.exists():
        raise ValueError("Run directory not found")

    metrics_path = run_path / "metrics.json"
    if metrics_path.exists():
        with open(metrics_path) as handle:
            return json.load(handle)

    artifacts = {}
    for name in ["trades", "signals", "orders", "fills"]:
        file_path = run_path / f"{name}.parquet"
        if file_path.exists():
            artifacts[name] = pd.read_parquet(file_path)
        else:
            artifacts[name] = pd.DataFrame()

    if not artifacts:
        return {
            "trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
        }

    return MetricsCalculator.calculate_basic_metrics(artifacts)
