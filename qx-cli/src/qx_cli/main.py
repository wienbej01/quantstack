"""Main CLI interface for QuantStack experiments."""

import os
import sys
from pathlib import Path

import typer

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from qx_cli.commands.regime import app as regime_app
from qx_cli.commands.warehouse import app as warehouse_app
from qx_cli.experiments.cost_sweep import (
    CostSweepExperiment,
    create_default_cost_sweep_config,
)

app = typer.Typer(help="QuantStack experiment orchestration CLI")

# Add sub-apps
app.add_typer(
    warehouse_app,
    name="warehouse",
    help="Warehouse commands for data ingestion and querying",
)
app.add_typer(regime_app, name="regime", help="Regime detection and analysis commands")


@app.command()
def run_cost_sweep(
    name: str | None = typer.Option(None, help="Experiment name"),
    symbols: list[str] | None = typer.Option(
        None, help="Symbols to test (comma-separated)"
    ),
    start_date: str | None = typer.Option(None, help="Start date (YYYY-MM-DD)"),
    end_date: str | None = typer.Option(None, help="End date (YYYY-MM-DD)"),
    commission_per_share: str | None = typer.Option(
        None, help="Commission per share values (comma-separated)"
    ),
    commission_min: str | None = typer.Option(
        None, help="Minimum commission values (comma-separated)"
    ),
    slippage_bps: str | None = typer.Option(
        None, help="Slippage in basis points (comma-separated)"
    ),
    vwap_window: int | None = typer.Option(None, help="VWAP window size"),
    min_rvol: float | None = typer.Option(None, help="Minimum relative volume"),
    max_positions: int | None = typer.Option(None, help="Maximum positions"),
    output_dir: str | None = typer.Option("runs", help="Output directory"),
    parallel: bool | None = typer.Option(False, help="Run in parallel"),
    config_file: Path | None = typer.Option(None, help="Configuration file path"),
) -> None:
    """Run a cost sweep experiment."""

    # Load configuration
    if config_file and config_file.exists():
        import json

        with open(config_file) as f:
            config_dict = json.load(f)
        config = CostSweepConfig.from_dict(config_dict)
        typer.echo(f"Loaded configuration from {config_file}")
    else:
        config = create_default_cost_sweep_config()

    # Override with command line arguments
    if name:
        config.name = name
    if symbols:
        config.symbols = symbols
    if start_date:
        config.start_date = start_date
    if end_date:
        config.end_date = end_date
    if commission_per_share:
        config.commission_per_share = [
            float(x.strip()) for x in commission_per_share.split(",")
        ]
    if commission_min:
        config.commission_min = [float(x.strip()) for x in commission_min.split(",")]
    if slippage_bps:
        config.slippage_bps = [int(x.strip()) for x in slippage_bps.split(",")]
    if vwap_window:
        config.vwap_window = vwap_window
    if min_rvol:
        config.min_rvol = min_rvol
    if max_positions:
        config.max_positions = max_positions
    if output_dir:
        config.output_dir = output_dir
    if parallel:
        config.parallel = parallel

    # Create and run experiment
    experiment = CostSweepExperiment(config)

    typer.echo(f"Starting cost sweep experiment: {experiment.experiment_id}")
    typer.echo(
        f"Testing {len(config.commission_per_share) * len(config.commission_min) * len(config.slippage_bps)} parameter combinations"
    )

    try:
        result = experiment.execute()

        typer.echo("✓ Experiment completed successfully!")
        typer.echo(f"Duration: {result.duration_seconds:.2f} seconds")
        typer.echo(f"Status: {result.status}")

        if result.artifacts:
            typer.echo("Artifacts saved:")
            for name, path in result.artifacts.items():
                typer.echo(f"  {name}: {path}")

        if result.results and "cost_sweep_analysis" in result.results:
            analysis = result.results["cost_sweep_analysis"]
            if "best_configuration" in analysis:
                best_config = analysis["best_configuration"]
                typer.echo("\nBest configuration:")
                typer.echo(
                    f"  Commission per share: ${best_config.get('commission_per_share', 'N/A')}"
                )
                typer.echo(
                    f"  Commission min: ${best_config.get('commission_min', 'N/A')}"
                )
                typer.echo(f"  Slippage bps: {best_config.get('slippage_bps', 'N/A')}")

                if "best_metrics" in analysis:
                    best_metrics = analysis["best_metrics"]
                    typer.echo("\nBest metrics:")
                    for metric, value in best_metrics.items():
                        if isinstance(value, float):
                            if metric in [
                                "total_return",
                                "max_drawdown",
                                "win_rate",
                                "profit_factor",
                            ]:
                                typer.echo(f"  {metric}: {value:.2%}")
                            else:
                                typer.echo(f"  {metric}: {value:.4f}")
                        else:
                            typer.echo(f"  {metric}: {value}")

    except Exception as e:
        typer.echo(f"✗ Experiment failed: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def create_config(
    output_path: Path = typer.Argument(..., help="Output configuration file path"),
    experiment_type: str = typer.Option("cost_sweep", help="Experiment type"),
) -> None:
    """Create a default configuration file."""

    if experiment_type == "cost_sweep":
        config = create_default_cost_sweep_config()
    else:
        typer.echo(f"Unknown experiment type: {experiment_type}", err=True)
        raise typer.Exit(1)

    import json

    with open(output_path, "w") as f:
        json.dump(config.to_dict(), f, indent=2, default=str)

    typer.echo(f"Created {experiment_type} configuration file: {output_path}")


@app.command()
def list_experiments(
    output_dir: str = typer.Option("runs", help="Output directory")
) -> None:
    """List completed experiments."""

    runs_path = Path(output_dir)
    if not runs_path.exists():
        typer.echo(f"No experiments found in {output_dir}")
        return

    # Look for experiment artifacts
    experiment_dirs = [d for d in runs_path.iterdir() if d.is_dir()]

    if not experiment_dirs:
        typer.echo(f"No experiments found in {output_dir}")
        return

    typer.echo("Completed experiments:")
    for exp_dir in sorted(experiment_dirs):
        typer.echo(f"  {exp_dir.name}")


@app.command()
def model_list() -> None:
    """List available regime models."""

    from qx_core.schemas import RegimeType

    typer.echo("Available regime models:")
    for regime in RegimeType:
        typer.echo(f"  - {regime.value}")


if __name__ == "__main__":
    app()

    from qx_core.schemas import RegimeType

    typer.echo("Available regime models:")
    for regime in RegimeType:
        typer.echo(f"  - {regime.value}")


if __name__ == "__main__":
    app()

    typer.echo("Available regime models:")
    for regime in RegimeType:
        typer.echo(f"  - {regime.value}")


if __name__ == "__main__":
    app()
