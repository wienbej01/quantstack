"""Intraday ML reporting CLI interface.

This module provides CLI commands for generating reports from
experiment artifacts, including single-run analysis and A/B comparisons.
"""

import pathlib
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from . import __version__

console = Console()
app = typer.Typer(help=f"Intraday ML Reporting v{__version__}")


@app.command("experiment")
def experiment_report(
    experiment_dir: pathlib.Path = typer.Option(
        ..., "--exp-dir", help="Experiment directory"
    ),
    output_format: str = typer.Option(
        "console",
        "--format",
        help="Output format (console, dict, json)",
    ),
    output_file: pathlib.Path = typer.Option(
        None, "--output", help="Output file (for json/dict formats only)"
    ),
) -> None:
    """Generate report from experiment artifacts."""
    console.print(
        f"[bold blue]Experiment Report Generation[/bold blue]: {experiment_dir}"
    )

    if not experiment_dir.exists():
        console.print(f"[red]Experiment directory not found: {experiment_dir}[/red]")
        raise typer.Exit(1)

    try:
        report_data = generate_experiment_report(
            str(experiment_dir), output_format=output_format
        )

        # Display results
        _display_report_results(report_data)

        # Write to file if specified
        if output_file and output_format != "console":
            import json

            if output_format == "json":
                with open(output_file, "w") as f:
                    json.dump(report_data, f, indent=2, default=str)
            elif output_format == "dict":
                with open(output_file, "w") as f:
                    f.write(str(report_data))

    except Exception as e:
        console.print(f"[red]Report generation failed: {e}[/red]")
        raise typer.Exit(1)


@app.command("run-metrics")
def run_metrics(
    run_dir: pathlib.Path = typer.Option(..., "--run-dir", help="Run directory"),
    output_format: str = typer.Option(
        "console",
        "--format",
        help="Output format (console, dict, json)",
    ),
    output_file: pathlib.Path = typer.Option(
        None, "--output", help="Output file (for json/dict formats only)"
    ),
) -> None:
    """Generate metrics from a single run directory."""
    console.print(f"[bold blue]Run Metrics[/bold blue]: {run_dir}")

    if not run_dir.exists():
        console.print(f"[red]Run directory not found: {run_dir}[/red]")
        raise typer.Exit(1)

    try:
        metrics = read_single_run_metrics(str(run_dir))

        # Display results
        _display_run_metrics(metrics)

        # Write to file if specified
        if output_file and output_format != "console":
            import json

            if output_format == "json":
                with open(output_file, "w") as f:
                    json.dump(metrics, f, indent=2, default=str)
            elif output_format == "dict":
                with open(output_file, "w") as f:
                    f.write(str(metrics))

    except Exception as e:
        console.print(f"[red]Metrics generation failed: {e}[/red]")
        raise typer.Exit(1)


@app.command("compare")
def compare_experiments(
    baseline_dir: pathlib.Path = typer.Option(
        ..., "--baseline", help="Baseline experiment directory"
    ),
    variant_dir: pathlib.Path = typer.Option(
        ..., "--variant", help="Variant experiment directory"
    ),
    output_format: str = typer.Option(
        "console",
        "--format",
        help="Output format (console, dict, json)",
    ),
    output_file: pathlib.Path = typer.Option(
        None, "--output", help="Output file (for json/dict formats only)"
    ),
) -> None:
    """Compare baseline and variant experiment results."""
    console.print(
        f"[bold blue]Experiment Comparison[/bold blue]: {baseline_dir} vs {variant_dir}"
    )

    if not baseline_dir.exists():
        console.print(f"[red]Baseline directory not found: {baseline_dir}[/red]")
        raise typer.Exit(1)

    if not variant_dir.exists():
        console.print(f"[red]Variant directory not found: {variant_dir}[/red]")
        raise typer.Exit(1)

    try:
        # This would implement a more complex comparison across different experiments
        # For Sprint 8 minimal implementation, show placeholder
        console.print(
            "[yellow]Experiment comparison requires full implementation[/yellow]"
        )
        console.print(
            "[yellow]This is a placeholder for Sprint 8 functionality[/yellow]"
        )

    except Exception as e:
        console.print(f"[red]Comparison failed: {e}[/red]")
        raise typer.Exit(1)


@app.command("version")
def version() -> None:
    """Show intraday ML reporting version."""
    console.print(f"Intraday ML Reporting v{__version__}")


def _display_report_results(report_data: dict[str, Any]) -> None:
    """Display experiment report results."""
    if not report_data:
        console.print("[yellow]No report data available[/yellow]")
        return

    console.print("\n[bold green]Experiment Report[/bold green]")

    # Experiment info
    exp_info = report_data.get("experiment_info", {})
    if exp_info:
        console.print(f"Name: {exp_info.get('experiment_name', 'N/A')}")
        console.print(f"ID: {exp_info.get('experiment_id', 'N/A')}")
        console.print(f"Timestamp: {exp_info.get('timestamp', 'N/A')}")
        console.print(f"Variants: {', '.join(exp_info.get('variants', []))}")

    # Checksum validation
    validation = report_data.get("checksum_validation", {})
    if validation:
        status = "✓ Passed" if validation.get("fair", False) else "⚠ Warnings"
        console.print(f"\nChecksum Validation: [bold {status}[/bold]")

    # Variant comparison
    comparison = report_data.get("variant_comparison", {})
    if comparison:
        console.print("\n[bold]Variant Comparison:[/bold]")

        # Show summary first
        summary = report_data.get("summary_metrics", {})
        if summary:
            console.print(f"Best Total PnL: {summary.get('best_total_pnl', 'N/A')}")
            console.print(f"Best Win Rate: {summary.get('best_win_rate', 'N/A'):.1%}")

        # Show variant details table
        if not isinstance(comparison, dict):
            # Convert dict to DataFrame for display
            import pandas as pd

            comparison_df = pd.DataFrame([comparison])
        else:
            comparison_df = comparison

        if hasattr(comparison_df, "to_parquet"):
            table = Table(title="Variant Metrics")
            table.add_column("Variant", style="cyan")
            for col in comparison_df.columns:
                if col != "variant":
                    table.add_column(col.replace("_", " ").title(), justify="right")

            for _, row in comparison_df.iterrows():
                variant_name = row.get("variant", "Unknown")
                other_cols = {k: v for k, v in row.items() if k != "variant"}
                table.add_row(
                    variant_name,
                    *[
                        f"{v:.3f}" if isinstance(v, (int, float)) else str(v)
                        for v in other_cols.values()
                    ],
                )

            console.print(table)

    else:
        console.print("[yellow]No variant comparison data available[/yellow]")


def _display_run_metrics(metrics: dict[str, Any]) -> None:
    """Display single run metrics."""
    if not metrics:
        console.print("[yellow]No metrics available[/yellow]")
        return

    console.print("\n[bold green]Run Metrics[/bold green]")

    table = Table(title="Performance Metrics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", justify="right")

    # Basic metrics
    basic_metrics = [
        ("Trades", metrics.get("trades", 0)),
        ("Win Rate", f"{metrics.get('win_rate', 0):.1%}"),
        ("Total PnL", f"{metrics.get('total_pnl', 0):.2f}"),
        ("Avg R", f"{metrics.get('avg_R', 0):.3f}"),
    ]

    # Risk metrics
    risk_metrics = [
        ("Risk Rejections", metrics.get("risk_rejections", 0)),
        ("Avg Stop Distance", f"{metrics.get('avg_stop_distance', 0):.3f}"),
        ("Max Position Size", f"{metrics.get('max_position_size', 0):.0f}"),
    ]

    # Execution metrics
    execution_metrics = [
        ("Order Fill Rate", f"{metrics.get('order_fill_rate', 0):.1%}"),
        ("Avg Slippage", f"{metrics.get('avg_slippage', 0):.3f}"),
        ("Total Fees", f"{metrics.get('total_fees', 0):.2f}"),
    ]

    # Add all metrics to table
    for section_name, section_metrics in [
        ("Basic Performance", basic_metrics),
        ("Risk Metrics", risk_metrics),
        ("Execution Metrics", execution_metrics),
    ]:
        if any(v for _, v in section_metrics if v != 0):
            console.print(f"\n[cyan]{section_name}[/cyan]")
            for metric_name, metric_value in section_metrics:
                table.add_row(metric_name, metric_value)
                console.print(table)
                table.rows.clear()

    # Add summary metrics
    if metrics.get("max_drawdown", 0) > 0:
        table.add_row("Max Drawdown", f"{metrics['max_drawdown']:.2f}")
        console.print("\n[cyan]Risk Metrics[/cyan]")
        console.print(table)


def main() -> None:
    """Main CLI entry point."""
    app()


if __name__ == "__main__":
    main()
