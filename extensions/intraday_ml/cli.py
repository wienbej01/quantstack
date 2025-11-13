"""Intraday ML CLI interface for experiment orchestration.

This module provides CLI commands for running A/B experiments with the
intraday ML extension, ensuring fairness validation and reproducibility.
"""

import pathlib
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .experiments import run_entry_ab_experiment, validate_fairness

console = Console()
app = typer.Typer(help=f"Intraday ML Extension v{__version__}")


@app.command("entry-ab")
def entry_ab(
    cfg: pathlib.Path = typer.Option(..., "--cfg", help="Base config file"),
    variants: str = typer.Option(
        ...,
        "--variants",
        help="Variant overlay files pattern, e.g., configs/extensions/intraday_ml/overlays/*.yaml",
    ),
    name: str = typer.Option(..., "--name", help="Experiment ID"),
    force: bool = typer.Option(False, "--force", help="Force run even if checksums differ"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show experiment plan without executing"),
) -> None:
    """Run entry A/B test with multiple intraday ML policy variants."""
    console.print(f"[bold blue]Intraday ML Entry/A/B Experiment[/bold blue]: {name}")

    # Validate config file exists
    if not cfg.exists():
        console.print(f"[red]Config file not found: {cfg}[/red]")
        raise typer.Exit(1)

    # Find variant files
    import glob

    variant_files = sorted(glob.glob(variants))
    if not variant_files:
        console.print(f"[red]No variant files found: {variants}[/red]")
        raise typer.Exit(1)

    console.print(f"Found {len(variant_files)} variant(s):")
    for variant in variant_files:
        console.print(f"  - {variant}")

    if dry_run:
        console.print("\n[yellow]DRY RUN MODE - No execution will occur[/yellow]")
        return

    # Run experiment
    try:
        results = run_entry_ab_experiment(
            base_config_path=str(cfg),
            variant_paths=variant_files,
            experiment_name=name,
            force=force,
        )

        # Display results
        _display_experiment_results(results, name)

    except Exception as e:
        console.print(f"[red]Experiment failed: {e}[/red]")
        raise typer.Exit(1)


@app.command("validate")
def validate_experiment(
    experiment_dir: pathlib.Path = typer.Option(
        ..., "--exp-dir", help="Experiment directory to validate"
    ),
) -> None:
    """Validate experiment fairness and checksum consistency."""
    console.print(f"[bold blue]Validating experiment[/bold blue]: {experiment_dir}")

    if not experiment_dir.exists():
        console.print(f"[red]Experiment directory not found: {experiment_dir}[/red]")
        raise typer.Exit(1)

    try:
        validation_result = validate_fairness(str(experiment_dir))
        _display_validation_results(validation_result)

    except Exception as e:
        console.print(f"[red]Validation failed: {e}[/red]")
        raise typer.Exit(1)


@app.command("version")
def version() -> None:
    """Show intraday ML extension version."""
    console.print(f"Intraday ML Extension v{__version__}")


def _display_experiment_results(results: dict[str, Any], experiment_name: str) -> None:
    """Display experiment results in a formatted table."""
    console.print(f"\n[bold green]Experiment Results: {experiment_name}[/bold green]")

    table = Table(title="Variant Summary")
    table.add_column("Variant", style="cyan")
    table.add_column("Trades", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Avg R", justify="right")
    table.add_column("Total PnL", justify="right")
    table.add_column("Status", style="green")

    for variant_name, metrics in results.get("variants", {}).items():
        table.add_row(
            variant_name,
            str(metrics.get("trades", 0)),
            f"{metrics.get('win_rate', 0):.2%}",
            f"{metrics.get('avg_R', 0):.3f}",
            f"{metrics.get('total_pnl', 0):.2f}",
            "✅ Complete",
        )

    console.print(table)

    # Display checksum validation
    checksums = results.get("checksums", {})
    if checksums.get("fair", False):
        console.print("[green]✓ Checksum validation passed - fair comparison[/green]")
    else:
        console.print("[yellow]⚠ Checksum validation warnings detected[/yellow]")


def _display_validation_results(validation_result: dict[str, Any]) -> None:
    """Display validation results."""
    if validation_result.get("valid", False):
        console.print("[green]✓ Experiment validation passed[/green]")
    else:
        console.print("[red]✗ Experiment validation failed[/red]")

    issues = validation_result.get("issues", [])
    if issues:
        console.print("\n[red]Issues found:[/red]")
        for issue in issues:
            console.print(f"  • {issue}")

    checksum_info = validation_result.get("checksums", {})
    if checksum_info:
        console.print("\n[blue]Checksum Information:[/blue]")
        for key, value in checksum_info.items():
            console.print(f"  {key}: {value}")


def main() -> None:
    """Main CLI entry point."""
    app()


if __name__ == "__main__":
    main()
