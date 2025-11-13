"""Artifact readers for qx-report package."""

import json
import pathlib
from typing import Any

import pandas as pd


class RunReader:
    """Reads artifacts from a single run directory."""

    def __init__(self, run_id: str, runs_dir: str = "runs"):
        """Initialize reader for a specific run.

        Args:
            run_id: Unique identifier for the run
            runs_dir: Base directory containing runs
        """
        self.run_id = run_id
        self.run_dir = pathlib.Path(runs_dir) / run_id
        self._cache: dict[str, Any] = {}

    def _read_parquet(self, filename: str) -> pd.DataFrame | None:
        """Read a parquet file from the run directory."""
        filepath = self.run_dir / filename
        if not filepath.exists():
            return None

        if filename not in self._cache:
            try:
                self._cache[filename] = pd.read_parquet(filepath)
            except Exception as e:
                print(f"Warning: Could not read {filename}: {e}")
                self._cache[filename] = None

        return self._cache[filename]

    def _read_json(self, filename: str) -> dict[str, Any] | None:
        """Read a JSON file from the run directory."""
        filepath = self.run_dir / filename
        if not filepath.exists():
            return None

        if filename not in self._cache:
            try:
                with open(filepath) as f:
                    self._cache[filename] = json.load(f)
            except Exception as e:
                print(f"Warning: Could not read {filename}: {e}")
                self._cache[filename] = None

        return self._cache[filename]

    @property
    def metrics(self) -> dict[str, Any] | None:
        """Get run metrics from metrics.json."""
        return self._read_json("metrics.json")

    @property
    def signals(self) -> pd.DataFrame | None:
        """Get signals DataFrame."""
        return self._read_parquet("signals.parquet")

    @property
    def orders(self) -> pd.DataFrame | None:
        """Get orders DataFrame."""
        return self._read_parquet("orders.parquet")

    @property
    def fills(self) -> pd.DataFrame | None:
        """Get fills DataFrame."""
        return self._read_parquet("fills.parquet")

    @property
    def positions(self) -> pd.DataFrame | None:
        """Get positions DataFrame."""
        return self._read_parquet("positions.parquet")

    @property
    def equity(self) -> pd.DataFrame | None:
        """Get equity curve DataFrame."""
        return self._read_parquet("equity.parquet")

    @property
    def trades(self) -> pd.DataFrame | None:
        """Get trades DataFrame."""
        return self._read_parquet("trades.parquet")

    @property
    def risk_rejects(self) -> pd.DataFrame | None:
        """Get risk rejects DataFrame."""
        return self._read_parquet("risk_rejects.parquet")

    @property
    def allocation_log(self) -> pd.DataFrame | None:
        """Get allocation log DataFrame."""
        return self._read_parquet("allocation_log.parquet")

    def summary_metrics(self) -> dict[str, Any]:
        """Extract key summary metrics from the run."""
        base_metrics = self.metrics or {}

        # Extract trade-level metrics if trades exist
        trades_df = self.trades
        trade_metrics = {}

        if trades_df is not None and not trades_df.empty:
            trade_metrics = {
                "trade_count": int(len(trades_df)),
                "avg_trade_pnl": (
                    float(trades_df["pnl"].mean()) if "pnl" in trades_df.columns else 0.0
                ),
                "median_r_multiple": (
                    float(trades_df["r_multiple"].median())
                    if "r_multiple" in trades_df.columns
                    else 0.0
                ),
                "win_rate": (
                    float((trades_df["pnl"] > 0).mean()) if "pnl" in trades_df.columns else 0.0
                ),
                "total_pnl": (float(trades_df["pnl"].sum()) if "pnl" in trades_df.columns else 0.0),
            }

        # Extract equity curve metrics if available
        equity_df = self.equity
        equity_metrics = {}

        if equity_df is not None and not equity_df.empty and "equity" in equity_df.columns:
            equity_series = equity_df["equity"]
            returns = equity_series.pct_change().dropna()

            equity_metrics = {
                "initial_equity": (float(equity_series.iloc[0]) if len(equity_series) > 0 else 0.0),
                "final_equity": (float(equity_series.iloc[-1]) if len(equity_series) > 0 else 0.0),
                "total_return": (
                    float(equity_series.iloc[-1] / equity_series.iloc[0] - 1)
                    if len(equity_series) > 1
                    else 0.0
                ),
                "volatility": float(returns.std()) if len(returns) > 0 else 0.0,
                "max_drawdown": float(self._calculate_max_drawdown(equity_series)),
            }

        # Merge all metrics
        return {
            "run_id": self.run_id,
            **base_metrics,
            **trade_metrics,
            **equity_metrics,
        }

    def _calculate_max_drawdown(self, equity_series: pd.Series) -> float:
        """Calculate maximum drawdown from equity series."""
        if len(equity_series) < 2:
            return 0.0

        running_max = equity_series.expanding().max()
        drawdown = (equity_series - running_max) / running_max
        return drawdown.min()


class ExperimentReader:
    """Reads experiment-level artifacts and manifests."""

    def __init__(self, exp_id: str, experiments_dir: str = "experiments"):
        """Initialize reader for an experiment.

        Args:
            exp_id: Unique identifier for the experiment
            experiments_dir: Base directory containing experiments
        """
        self.exp_id = exp_id
        self.exp_dir = pathlib.Path(experiments_dir) / exp_id

    @property
    def manifest(self) -> dict[str, Any] | None:
        """Get experiment manifest."""
        manifest_path = self.exp_dir / "manifest.json"
        if not manifest_path.exists():
            return None

        try:
            with open(manifest_path) as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not read manifest: {e}")
            return None

    @property
    def compare_results(self) -> dict[str, Any] | None:
        """Get experiment comparison results."""
        compare_path = self.exp_dir / "compare.json"
        if not compare_path.exists():
            return None

        try:
            with open(compare_path) as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not read compare results: {e}")
            return None

    def get_run_readers(self) -> list[RunReader]:
        """Get RunReader instances for all runs in this experiment."""
        manifest = self.manifest
        if not manifest or "run_ids" not in manifest:
            return []

        # Use runs_dir relative to experiments_dir - handle multiple possible structures
        # Structure 1: temp_dir/experiments/exp_id + temp_dir/runs (sibling to experiments)
        # Structure 2: temp_dir/exp_id + temp_dir/runs (sibling to experiment)

        # First try runs as sibling to experiments directory
        runs_dir = self.exp_dir.parent.parent / "runs"
        if not runs_dir.exists():
            # Fall back to runs as sibling to experiment directory
            runs_dir = self.exp_dir.parent / "runs"
        return [RunReader(run_id, str(runs_dir)) for run_id in manifest["run_ids"]]

    def summary_table(self) -> pd.DataFrame:
        """Create a summary table with metrics for all runs."""
        run_readers = self.get_run_readers()
        summaries = []

        for reader in run_readers:
            summary = reader.summary_metrics()
            summaries.append(summary)

        if not summaries:
            return pd.DataFrame()

        df = pd.DataFrame(summaries)

        # Add variant information if available from manifest
        manifest = self.manifest
        if manifest and "variants" in manifest and len(manifest["variants"]) == len(df):
            df["variant"] = [pathlib.Path(v).stem for v in manifest["variants"]]

        return df
