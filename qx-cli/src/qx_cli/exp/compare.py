"""Compare experiments command."""

import json
import pathlib

import typer
from rich.console import Console
from rich.table import Table

from qx_cli.exp import app

console = Console()


@app.command("compare")
def compare(
    exp: pathlib.Path = typer.Option(..., "--exp", help="Experiment directory"),
    force: bool = typer.Option(
        False, "--force", help="Force comparison even if checksums differ"
    ),
) -> None:
    """Compare variants in an experiment."""
    console.print(f"Comparing experiment: {exp}")

    exp_dir = pathlib.Path(exp)
    manifest_path = exp_dir / "manifest.json"
    checksum_path = exp_dir / "inputs_checksum.json"

    if not manifest_path.exists():
        console.print("Manifest not found", style="red")
        raise typer.Exit(1)

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Check fairness
    if not force:
        checksums = []
        for run_id in manifest["run_ids"]:
            run_checksum = pathlib.Path("runs") / run_id / "inputs_checksum.json"
            if run_checksum.exists():
                with open(run_checksum) as f:
                    checksums.append(json.load(f))
            else:
                console.print(f"Run {run_id} checksum missing", style="red")
                raise typer.Exit(1)

        # Check if all checksums match (stub: always pass for now)
        if not _checksums_match(checksums):
            console.print(
                "Input checksums differ. Use --force to compare anyway.", style="red"
            )
            raise typer.Exit(1)

    # Collect metrics from runs
    results = []
    for run_id in manifest["run_ids"]:
        metrics_path = pathlib.Path("runs") / run_id / "metrics.json"
        if metrics_path.exists():
            with open(metrics_path) as f:
                metrics = json.load(f)
            results.append({"run_id": run_id, "metrics": metrics})

    # Generate compare report
    compare_data = {
        "experiment": str(exp),
        "variants": len(results),
        "results": results,
        "leaderboard": sorted(
            results, key=lambda x: x["metrics"].get("sharpe_ratio", 0.0), reverse=True
        ),
    }

    with open(exp_dir / "compare.json", "w") as f:
        json.dump(compare_data, f, indent=2)

    # Generate markdown
    _generate_compare_md(exp_dir, compare_data)

    # Display table
    table = Table(title="Experiment Comparison")
    table.add_column("Run ID", style="cyan")
    table.add_column("Total Return", justify="right")
    table.add_column("Sharpe Ratio", justify="right")
    table.add_column("Win Rate", justify="right")

    for result in compare_data["leaderboard"]:
        m = result["metrics"]
        table.add_row(
            result["run_id"][:8],
            f"{m.get('total_return', 0.0):.3f}",
            f"{m.get('sharpe_ratio', 0.0):.3f}",
            f"{m.get('win_rate', 0.0):.3f}",
        )

    console.print(table)


def compare_experiments(exp_dir: pathlib.Path) -> None:
    """Internal function to compare experiments."""
    # Reuse the compare logic
    compare(exp_dir)


def _checksums_match(checksums: list) -> bool:
    """Check if all checksums match for fairness (bars, features, sip, seed)."""
    if not checksums:
        return True
    first = checksums[0]
    keys_to_check = ["bars_norm_hash", "features_hash", "sip_hash", "seed"]
    return all(all(c.get(k) == first.get(k) for k in keys_to_check) for c in checksums)


def _generate_compare_md(exp_dir: pathlib.Path, data: dict) -> None:
    """Generate markdown report."""
    md = f"""# Experiment Comparison: {data['experiment']}

## Summary
- Variants: {data['variants']}

## Leaderboard
| Run ID | Total Return | Sharpe Ratio | Win Rate |
|--------|-------------|--------------|----------|
"""
    for result in data["leaderboard"]:
        m = result["metrics"]
        md += f"| {result['run_id'][:8]} | {m.get('total_return', 0.0):.3f} | {m.get('sharpe_ratio', 0.0):.3f} | {m.get('win_rate', 0.0):.3f} |\n"

    with open(exp_dir / "compare.md", "w") as f:
        f.write(md)
