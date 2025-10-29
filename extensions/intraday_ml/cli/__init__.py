"""Intraday ML CLI interface.

Provides Typer-based CLI for ML model training, inference, and A/B testing.
"""

import pathlib
import typer
from rich.console import Console
from typing import Optional

from .enhanced_entry_ab import enhanced_entry_ab
from .fairness import validate_fairness

app = typer.Typer(help="Intraday ML Extension CLI")
console = Console()


@app.command("version")
def version():
    """Show version information."""
    console.print("Intraday ML Extension v0.1.0")
    console.print("Machine Learning enhanced intraday trading strategies")


@app.command("entry-ab")
def entry_ab(
    cfg: pathlib.Path = typer.Option(..., "--cfg", help="Base config file"),
    variants: str = typer.Option(..., "--variants", help="Variant overlay files pattern"),
    name: str = typer.Option(..., "--name", help="Experiment name"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be done without executing"),
    force: bool = typer.Option(False, "--force", help="Force run even with issues"),
    allow_unfair: bool = typer.Option(False, "--allow-unfair", help="Allow unfair experiments"),
):
    """Run entry/exit A/B testing experiment."""
    if not cfg.exists():
        console.print(f"Config file not found: {cfg}", style="red")
        raise typer.Exit(1)

    # Parse variant files
    import glob
    variant_files = [pathlib.Path(f) for f in sorted(glob.glob(variants))]

    if not variant_files:
        console.print(f"No variant files found for pattern: {variants}", style="red")
        raise typer.Exit(1)

    if dry_run:
        console.print("DRY RUN MODE", style="yellow")
        console.print(f"Config: {cfg}")
        console.print(f"Variants: {len(variant_files)} files")
        console.print(f"Experiment: {name}")
        console.print("Would run enhanced entry-ab experiment...")
        return

    console.print(f"Running entry-ab experiment: {name}")

    # Import and run the actual experiment
    from .orchestration import ABOrchestrator
    from .fairness import FairnessConfig

    fairness_config = FairnessConfig(
        allow_unfair=allow_unfair,
        require_identical_base_checksums=True,
        require_identical_data_hashes=not force,
    )

    orchestrator = ABOrchestrator(fairness_config)

    try:
        result = orchestrator.run_experiment(cfg, variant_files, name, force=force)

        console.print(f"\nExperiment Results: {name}")
        console.print(f"Runs: {len(result['run_results'])}")

        # Print performance summary
        for run_result in result['run_results']:
            metrics = run_result['metrics']
            trading = metrics.get('trading', {})
            performance = metrics.get('performance', {})

            console.print(f"  {run_result['run_id'][:8]}: "
                         f"Trades: {trading.get('total_trades', 0)} | "
                         f"Win Rate: {performance.get('win_rate', 0):.1%} | "
                         f"Return: {performance.get('total_return', 0):.2%}")

    except Exception as e:
        console.print(f"Experiment failed: {e}", style="red")
        raise typer.Exit(1)


@app.command("validate")
def validate(
    exp_dir: pathlib.Path = typer.Option(..., "--exp-dir", help="Experiment directory to validate"),
):
    """Validate experiment fairness and checksums."""
    if not exp_dir.exists():
        console.print(f"Experiment directory not found: {exp_dir}", style="red")
        raise typer.Exit(1)

    try:
        result = validate_fairness(exp_dir)
        if result.get("valid", False):
            console.print("Experiment validation passed", style="green")
        else:
            console.print(f"Experiment validation failed: {result.get('message', 'Unknown error')}", style="red")
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"Validation error: {e}", style="red")
        raise typer.Exit(1)


def main():
    """Main entry point for CLI."""
    app()


def run_entry_ab_experiment(cfg_path, variant_paths, experiment_name):
    """Function for testing entry-ab experiments."""
    from .orchestration import ABOrchestrator
    from .fairness import FairnessConfig

    fairness_config = FairnessConfig(allow_unfair=False)
    orchestrator = ABOrchestrator(fairness_config)

    return orchestrator.run_experiment(
        pathlib.Path(cfg_path),
        [pathlib.Path(p) for p in variant_paths],
        experiment_name
    )


if __name__ == "__main__":
    main()