"""Summary table generators for qx-report package."""

from typing import Any

import pandas as pd

from .readers import ExperimentReader, RunReader


class PerRunSummaries:
    """Generates per-run metrics summary tables."""

    @staticmethod
    def create_summary_table(
        experiment_id: str, experiments_dir: str = "experiments"
    ) -> pd.DataFrame:
        """Create a comprehensive summary table for an experiment.

        Args:
            experiment_id: ID of the experiment to summarize
            experiments_dir: Directory containing experiments

        Returns:
            DataFrame with summary metrics for each run
        """
        exp_reader = ExperimentReader(experiment_id, experiments_dir)
        return exp_reader.summary_table()

    @staticmethod
    def format_metrics_table(df: pd.DataFrame) -> pd.DataFrame:
        """Format metrics table for display with proper formatting.

        Args:
            df: Raw metrics DataFrame

        Returns:
            Formatted DataFrame suitable for display
        """
        if df.empty:
            return df

        # Create a copy for formatting
        formatted_df = df.copy()

        # Format common metrics
        percentage_metrics = [
            "total_return",
            "win_rate",
            "max_drawdown",
            "sharpe_CI_low",
            "sharpe_CI_high",
        ]
        for metric in percentage_metrics:
            if metric in formatted_df.columns:
                formatted_df[metric] = formatted_df[metric].apply(
                    lambda x: f"{x:.2%}" if pd.notna(x) else "N/A"
                )

        # Format numeric metrics
        numeric_metrics = [
            "avg_R",
            "avg_trade_pnl",
            "median_r_multiple",
            "total_pnl",
            "ES_95",
        ]
        for metric in numeric_metrics:
            if metric in formatted_df.columns:
                formatted_df[metric] = formatted_df[metric].apply(
                    lambda x: f"{x:.4f}" if pd.notna(x) else "N/A"
                )

        # Format trade counts
        count_metrics = ["trades", "trade_count"]
        for metric in count_metrics:
            if metric in formatted_df.columns:
                formatted_df[metric] = formatted_df[metric].apply(
                    lambda x: f"{int(x)}" if pd.notna(x) else "0"
                )

        return formatted_df


class ABDiffTables:
    """Generates A/B comparison and difference tables."""

    @staticmethod
    def create_comparison_table(
        experiment_id: str, experiments_dir: str = "experiments"
    ) -> pd.DataFrame:
        """Create A/B comparison table showing metrics side by side.

        Args:
            experiment_id: ID of the experiment to compare
            experiments_dir: Directory containing experiments

        Returns:
            DataFrame with variants as columns and metrics as rows
        """
        exp_reader = ExperimentReader(experiment_id, experiments_dir)
        summary_df = exp_reader.summary_table()

        if summary_df.empty or len(summary_df) < 2:
            return pd.DataFrame()

        # Get metric columns (exclude identifier columns)
        exclude_cols = ["run_id", "variant"]
        metric_cols = [col for col in summary_df.columns if col not in exclude_cols]

        # Create comparison table
        comparison_data = {}
        for _, row in summary_df.iterrows():
            variant_name = row.get("variant", row.get("run_id", "Unknown"))
            comparison_data[variant_name] = row[metric_cols]

        comparison_df = pd.DataFrame(comparison_data)
        return comparison_df

    @staticmethod
    def create_difference_table(
        experiment_id: str,
        experiments_dir: str = "experiments",
        baseline_variant: str | None = None,
    ) -> pd.DataFrame:
        """Create difference table showing performance differences between variants.

        Args:
            experiment_id: ID of the experiment
            experiments_dir: Directory containing experiments
            baseline_variant: Variant to use as baseline (first variant if None)

        Returns:
            DataFrame showing differences from baseline
        """
        comparison_df = ABDiffTables.create_comparison_table(
            experiment_id, experiments_dir
        )

        if comparison_df.empty or len(comparison_df.columns) < 2:
            return pd.DataFrame()

        # Select baseline column
        if baseline_variant is None:
            baseline_variant = comparison_df.columns[0]

        if baseline_variant not in comparison_df.columns:
            raise ValueError(
                f"Baseline variant '{baseline_variant}' not found in comparison"
            )

        # Calculate differences
        baseline_values = comparison_df[baseline_variant]
        diff_data = {}

        for variant in comparison_df.columns:
            if variant == baseline_variant:
                diff_data[variant] = 0.0  # Baseline has zero difference
            else:
                diff_data[variant] = comparison_df[variant] - baseline_values

        diff_df = pd.DataFrame(diff_data, index=comparison_df.index)

        # Add percentage change for key metrics
        pct_change_data = {}
        for variant in comparison_df.columns:
            if variant == baseline_variant:
                pct_change_data[variant] = 0.0
            else:
                # Avoid division by zero
                pct_change = (
                    comparison_df[variant] / baseline_values.replace(0, float("nan"))
                    - 1
                )
                pct_change_data[variant] = pct_change

        pct_change_df = pd.DataFrame(pct_change_data, index=comparison_df.index)

        return diff_df, pct_change_df

    @staticmethod
    def format_diff_table(
        diff_df: pd.DataFrame, pct_change_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Format difference table with absolute and percentage changes.

        Args:
            diff_df: Absolute differences DataFrame
            pct_change_df: Percentage changes DataFrame

        Returns:
            Formatted DataFrame with both absolute and percentage changes
        """
        formatted_data = []

        for metric in diff_df.index:
            row_data = {"metric": metric}

            for variant in diff_df.columns:
                abs_diff = diff_df.loc[metric, variant]
                pct_diff = pct_change_df.loc[metric, variant]

                if pd.isna(abs_diff) or pd.isna(pct_diff):
                    row_data[f"{variant}_abs"] = "N/A"
                    row_data[f"{variant}_pct"] = "N/A"
                else:
                    # Format absolute difference
                    if abs(abs_diff) < 0.01:
                        row_data[f"{variant}_abs"] = f"{abs_diff:+.6f}"
                    else:
                        row_data[f"{variant}_abs"] = f"{abs_diff:+.4f}"

                    # Format percentage difference
                    row_data[f"{variant}_pct"] = f"{pct_diff:+.2%}"

            formatted_data.append(row_data)

        return pd.DataFrame(formatted_data)

    @staticmethod
    def identify_winner(
        experiment_id: str,
        experiments_dir: str = "experiments",
        primary_metric: str = "sharpe_CI_high",
    ) -> dict[str, Any]:
        """Identify the winning variant based on primary metric.

        Args:
            experiment_id: ID of the experiment
            experiments_dir: Directory containing experiments
            primary_metric: Metric to use for determining winner

        Returns:
            Dictionary with winner information
        """
        summary_df = PerRunSummaries.create_summary_table(
            experiment_id, experiments_dir
        )

        if summary_df.empty or primary_metric not in summary_df.columns:
            return {"error": f"Metric '{primary_metric}' not found"}

        # Find variant with highest primary metric
        best_idx = summary_df[primary_metric].idxmax()
        best_variant = summary_df.loc[best_idx]

        return {
            "winner": best_variant.get(
                "variant", best_variant.get("run_id", "Unknown")
            ),
            "primary_metric": primary_metric,
            "primary_value": best_variant[primary_metric],
            "all_metrics": best_variant.to_dict(),
        }


class LeaderboardGenerator:
    """Generates leaderboards for experiments."""

    @staticmethod
    def create_leaderboard(
        experiment_id: str,
        experiments_dir: str = "experiments",
        sort_metric: str = "sharpe_CI_high",
    ) -> pd.DataFrame:
        """Create a ranked leaderboard for an experiment.

        Args:
            experiment_id: ID of the experiment
            experiments_dir: Directory containing experiments
            sort_metric: Metric to sort by (higher is better)

        Returns:
            Ranked DataFrame with leaderboard
        """
        summary_df = PerRunSummaries.create_summary_table(
            experiment_id, experiments_dir
        )

        if summary_df.empty:
            return summary_df

        # Sort by primary metric (descending)
        if sort_metric in summary_df.columns:
            summary_df = summary_df.sort_values(sort_metric, ascending=False)

        # Add rank column
        summary_df = summary_df.reset_index(drop=True)
        summary_df.insert(0, "rank", range(1, len(summary_df) + 1))

        return summary_df

    @staticmethod
    def format_leaderboard(leaderboard_df: pd.DataFrame) -> str:
        """Format leaderboard as a readable string.

        Args:
            leaderboard_df: Ranked DataFrame

        Returns:
            Formatted string representation
        """
        if leaderboard_df.empty:
            return "No data available for leaderboard."

        # Select key columns for display
        key_cols = [
            "rank",
            "variant",
            "trades",
            "avg_R",
            "sharpe_CI_high",
            "total_return",
        ]
        display_cols = [col for col in key_cols if col in leaderboard_df.columns]

        if not display_cols:
            return "No display columns available for leaderboard."

        display_df = leaderboard_df[display_cols]

        # Format for string output
        lines = []
        lines.append("EXPERIMENT LEADERBOARD")
        lines.append("=" * 80)

        # Header
        header = " | ".join(f"{col:>12}" for col in display_df.columns)
        lines.append(header)
        lines.append("-" * len(header))

        # Data rows
        for _, row in display_df.iterrows():
            row_str = " | ".join(
                f"{str(row[col]):>12}" if col != "rank" else f"{int(row[col]):>12}"
                for col in display_df.columns
            )
            lines.append(row_str)

        return "\n".join(lines)


class TradeAnalysis:
    """Generates detailed trade list reports."""

    @staticmethod
    def generate_trade_list(run_id: str, runs_dir: str = "runs") -> pd.DataFrame | None:
        """Generate a detailed list of trades from a run.

        Args:
            run_id: Unique identifier for the run
            runs_dir: Base directory containing runs

        Returns:
            DataFrame with detailed trade information
        """
        reader = RunReader(run_id, runs_dir)
        trades_df = reader.trades
        return trades_df
