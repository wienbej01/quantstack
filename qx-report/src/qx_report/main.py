"""Main CLI interface for qx-report package."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .readers import RunReader
from .summaries import ABDiffTables, LeaderboardGenerator, PerRunSummaries

app = typer.Typer(help="QuantStack reporting tool for experiment analysis")
console = Console()


@app.command()
def summarize(
    experiment_id: str = typer.Argument(..., help="Experiment ID to summarize"),
    experiments_dir: str = typer.Option("experiments", help="Experiments directory"),
    format_output: bool = typer.Option(True, help="Format numbers for display"),
    output_file: Path | None = typer.Option(None, help="Save summary to file"),
) -> None:
    """Generate a summary table for an experiment."""
    console.print(f"Generating summary for experiment: {experiment_id}")

    try:
        # Create summary table
        summary_df = PerRunSummaries.create_summary_table(
            experiment_id, experiments_dir
        )

        if summary_df.empty:
            console.print("No data found for this experiment.", style="yellow")
            return

        # Format if requested
        if format_output:
            display_df = PerRunSummaries.format_metrics_table(summary_df)
        else:
            display_df = summary_df

        # Display table
        table = Table(title=f"Experiment Summary: {experiment_id}")

        # Add columns
        for col in display_df.columns:
            table.add_column(col, justify="left")

        # Add rows
        for _, row in display_df.iterrows():
            table.add_row(*[str(val) for val in row])

        console.print(table)

        # Save to file if requested
        if output_file:
            if output_file.suffix == ".csv":
                summary_df.to_csv(output_file, index=False)
            elif output_file.suffix in [".json", ".jsonl"]:
                summary_df.to_json(output_file, orient="records", indent=2)
            else:
                # Default to CSV
                summary_df.to_csv(output_file.with_suffix(".csv"), index=False)

            console.print(f"Summary saved to: {output_file}")

    except Exception as e:
        console.print(f"Error generating summary: {e}", style="red")
        raise typer.Exit(1)


@app.command()
def compare(
    experiment_id: str = typer.Argument(..., help="Experiment ID to compare"),
    experiments_dir: str = typer.Option("experiments", help="Experiments directory"),
    baseline: str | None = typer.Option(None, help="Baseline variant for comparison"),
    show_differences: bool = typer.Option(True, help="Show absolute and % differences"),
    output_file: Path | None = typer.Option(None, help="Save comparison to file"),
) -> None:
    """Generate A/B comparison tables."""
    console.print(f"Generating comparison for experiment: {experiment_id}")

    try:
        # Create comparison table
        comparison_df = ABDiffTables.create_comparison_table(
            experiment_id, experiments_dir
        )

        if comparison_df.empty:
            console.print(
                "No comparison data available (need at least 2 variants).",
                style="yellow",
            )
            return

        # Display comparison table
        console.print("Variant Comparison:", style="bold")
        comp_table = Table(title="Metrics by Variant")

        for col in comparison_df.columns:
            comp_table.add_column(col, justify="left")

        for metric in comparison_df.index:
            row_values = [
                f"{val:.4f}" if not pd.isna(val) else "N/A"
                for val in comparison_df.loc[metric]
            ]
            comp_table.add_row(metric, *row_values)

        console.print(comp_table)

        # Show differences if requested and we have multiple variants
        if show_differences and len(comparison_df.columns) > 1:
            try:
                diff_df, pct_df = ABDiffTables.create_difference_table(
                    experiment_id, experiments_dir, baseline
                )
                formatted_diff = ABDiffTables.format_diff_table(diff_df, pct_df)

                console.print("\nDifferences from Baseline:", style="bold")
                diff_table = Table(title="Absolute and % Differences")

                # Add columns (metric, then abs/pct for each variant)
                diff_table.add_column("Metric", justify="left")
                for variant in diff_df.columns:
                    diff_table.add_column(f"{variant} (Δ)", justify="right")
                    diff_table.add_column(f"{variant} (%)", justify="right")

                for _, row in formatted_diff.iterrows():
                    values = [
                        row[col] for col in formatted_df.columns if col != "metric"
                    ]
                    diff_table.add_row(row["metric"], *values)

                console.print(diff_table)

            except Exception as e:
                console.print(f"Could not generate differences: {e}", style="yellow")

        # Identify winner
        try:
            winner_info = ABDiffTables.identify_winner(experiment_id, experiments_dir)
            if "error" not in winner_info:
                console.print(
                    f"\n🏆 Winner: {winner_info['winner']}", style="green bold"
                )
                console.print(
                    f"Primary metric ({winner_info['primary_metric']}): {winner_info['primary_value']:.4f}"
                )
        except Exception as e:
            console.print(f"Could not identify winner: {e}", style="yellow")

        # Save to file if requested
        if output_file:
            if output_file.suffix == ".csv":
                comparison_df.to_csv(output_file)
            elif output_file.suffix in [".json", ".jsonl"]:
                comparison_df.to_json(output_file, orient="index", indent=2)
            else:
                comparison_df.to_csv(output_file.with_suffix(".csv"))

            console.print(f"Comparison saved to: {output_file}")

    except Exception as e:
        console.print(f"Error generating comparison: {e}", style="red")
        raise typer.Exit(1)


@app.command()
def leaderboard(
    experiment_id: str = typer.Argument(..., help="Experiment ID for leaderboard"),
    experiments_dir: str = typer.Option("experiments", help="Experiments directory"),
    sort_metric: str = typer.Option("sharpe_CI_high", help="Metric to sort by"),
    output_file: Path | None = typer.Option(None, help="Save leaderboard to file"),
) -> None:
    """Generate a ranked leaderboard."""
    console.print(f"Generating leaderboard for experiment: {experiment_id}")

    try:
        # Create leaderboard
        leaderboard_df = LeaderboardGenerator.create_leaderboard(
            experiment_id, experiments_dir, sort_metric
        )

        if leaderboard_df.empty:
            console.print("No data available for leaderboard.", style="yellow")
            return

        # Format and display
        leaderboard_str = LeaderboardGenerator.format_leaderboard(leaderboard_df)
        console.print(leaderboard_str)

        # Save to file if requested
        if output_file:
            if output_file.suffix == ".csv":
                leaderboard_df.to_csv(output_file, index=False)
            elif output_file.suffix in [".json", ".jsonl"]:
                leaderboard_df.to_json(output_file, orient="records", indent=2)
            else:
                leaderboard_df.to_csv(output_file.with_suffix(".csv"), index=False)

            console.print(f"Leaderboard saved to: {output_file}")

    except Exception as e:
        console.print(f"Error generating leaderboard: {e}", style="red")
        raise typer.Exit(1)


@app.command()
def inspect(
    run_id: str = typer.Argument(..., help="Run ID to inspect"),
    runs_dir: str = typer.Option("runs", help="Runs directory"),
    show_trades: bool = typer.Option(False, help="Show sample trades"),
    trade_count: int = typer.Option(5, help="Number of trades to show"),
) -> None:
    """Inspect a single run in detail."""
    console.print(f"Inspecting run: {run_id}")

    try:
        reader = RunReader(run_id, runs_dir)

        # Show summary metrics
        summary = reader.summary_metrics()
        console.print("Run Summary:", style="bold")

        for key, value in summary.items():
            if isinstance(value, float):
                if key in ["total_return", "win_rate", "max_drawdown"]:
                    console.print(f"  {key}: {value:.2%}")
                else:
                    console.print(f"  {key}: {value:.4f}")
            else:
                console.print(f"  {key}: {value}")

        # Show sample trades if requested
        if show_trades:
            trades_df = reader.trades
            if trades_df is not None and not trades_df.empty:
                console.print(f"\nSample Trades (first {trade_count}):", style="bold")

                trade_table = Table()
                for col in trades_df.columns[:10]:  # Limit columns
                    trade_table.add_column(col, justify="left")

                for _, trade in trades_df.head(trade_count).iterrows():
                    trade_table.add_row(*[str(val)[:20] for val in trade.values[:10]])

                console.print(trade_table)
            else:
                console.print("No trades found.", style="yellow")

    except Exception as e:
        console.print(f"Error inspecting run: {e}", style="red")
        raise typer.Exit(1)


if __name__ == "__main__":
    # Import pandas for the compare command
    import pandas as pd

    app()
