"""Enhanced entry A/B testing command with improved fairness validation."""

import pathlib

import typer
from rich.console import Console

from .fairness import FairnessConfig
from .orchestration import ABOrchestrator

app = typer.Typer()
console = Console()


@app.command("enhanced-entry-ab")
def enhanced_entry_ab(
    cfg: pathlib.Path = typer.Option(..., "--cfg", help="Base config file"),
    variants: str = typer.Option(
        ...,
        "--variants",
        help="Variant overlay files pattern, e.g., test_config/variant_*.json",
    ),
    name: str = typer.Option(..., "--name", help="Experiment ID"),
    force: bool = typer.Option(
        False, "--force", help="Force run even if checksums differ"
    ),
    allow_unfair: bool = typer.Option(
        False,
        "--allow-unfair",
        help="Allow experiment to proceed despite fairness violations",
    ),
) -> None:
    """Run enhanced entry A/B test with improved fairness validation."""
    console.print(f"Running enhanced entry-ab experiment: {name}")

    # Parse variant files
    if "," in variants:
        variant_files = [
            pathlib.Path(f.strip()) for f in variants.split(",") if f.strip()
        ]
    else:
        import glob

        variant_files = [pathlib.Path(f) for f in sorted(glob.glob(variants))]

    if not variant_files:
        console.print(f"No variant files found for pattern: {variants}", style="red")
        raise typer.Exit(1)

    # Configure fairness validation
    fairness_config = FairnessConfig(
        allow_unfair=allow_unfair,
        require_identical_base_checksums=True,
        require_identical_data_hashes=not force,
    )

    # Create orchestrator and run experiment
    orchestrator = ABOrchestrator(fairness_config)

    try:
        result = orchestrator.run_experiment(cfg, variant_files, name, force=force)

        # Print results summary
        console.print("\n✅ Experiment completed successfully!", style="green")
        console.print(f"Experiment ID: {result['experiment_name']}")
        console.print(f"Runs created: {len(result['run_results'])}")

        if result["fairness_result"]:
            fairness = result["fairness_result"]
            if fairness.is_fair:
                console.print("✅ Fairness validation passed", style="green")
            else:
                console.print(f"⚠️  Fairness issues: {fairness.reason}", style="yellow")
            if fairness.warnings:
                console.print(
                    f"Warnings: {', '.join(fairness.warnings)}", style="yellow"
                )

        # Print performance summary
        console.print("\nPerformance Summary:")
        for run_result in result["run_results"]:
            run_id = run_result["run_id"]
            metrics = run_result["metrics"]
            trading = metrics.get("trading", {})
            performance = metrics.get("performance", {})

            console.print(f"  {run_id}:")
            console.print(
                f"    Trades: {trading.get('total_trades', 0)} | "
                f"Win Rate: {performance.get('win_rate', 0):.2%} | "
                f"Return: {performance.get('total_return', 0):.3%}"
            )

    except Exception as e:
        console.print(f"❌ Experiment failed: {e}", style="red")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
