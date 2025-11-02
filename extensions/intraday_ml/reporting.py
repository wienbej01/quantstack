"""Reporting helpers for intraday ML experiments."""

from __future__ import annotations

import json
from dataclasses import dataclass
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

    def calculate_differences(
        self, comparison_df: pd.DataFrame, baseline: str
    ) -> pd.DataFrame:
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
                diff_df[f"{column}_pct_change"] = (
                    diff_df[f"{column}_diff"] / baseline_value * 100.0
                )
        return diff_df

    def generate_summary_table(self, comparison_df: pd.DataFrame) -> SummaryTable:
        """Create simple summary table from comparison DataFrame."""
        rows = []
        for variant, row in comparison_df.iterrows():
            rows.append({"variant": variant, **row.to_dict()})
        return SummaryTable(rows=rows)


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
