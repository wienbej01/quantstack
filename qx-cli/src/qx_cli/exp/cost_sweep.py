"""Cost sweep testing command."""

import json
import os
import pathlib
import sys
import uuid

import typer
import yaml
from rich.console import Console

from qx_cli.exp import app

# Add experiments path to import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "experiments"))
try:
    from cost_sweep import CostSweepConfig, CostSweepExperiment
except ImportError:
    # Fallback for development when experiments module isn't built yet
    CostSweepExperiment = None
    CostSweepConfig = None

console = Console()


@app.command("cost-sweep")
def cost_sweep(
    cfg: pathlib.Path = typer.Option(..., "--cfg", help="Base config file"),
    grid: str = typer.Option(
        ...,
        "--grid",
        help="Grid parameters, e.g., commission_per_share=0.001,0.0035 slippage_bps=0,5,10",
    ),
    name: str = typer.Option(..., "--name", help="Experiment ID"),
) -> None:
    """Run cost sweep test with varying cost parameters."""

    # Check if experiment modules are available
    if CostSweepExperiment is None or CostSweepConfig is None:
        console.print(
            "Error: Cost sweep experiment modules not available. Please ensure the experiments package is built.",
            style="red",
        )
        console.print("Falling back to stub implementation.")
        return _run_stub_cost_sweep(cfg, grid, name)

    console.print(f"Running cost-sweep experiment: {name}")

    # Parse grid (multi-param)
    grid_params = _parse_multi_grid(grid)
    console.print(f"Grid parameters: {grid_params}")

    # Create experiment directory
    exp_dir = pathlib.Path("experiments") / name
    exp_dir.mkdir(parents=True, exist_ok=True)

    # Load base config
    with open(cfg) as f:
        base_config = yaml.safe_load(f)

    # Create CostSweepConfig
    cost_sweep_config = _create_cost_sweep_config(base_config, grid_params, name, exp_dir)

    # Create and run experiment
    experiment = CostSweepExperiment(cost_sweep_config)

    try:
        console.print(f"Starting cost sweep experiment: {experiment.experiment_id}")
        result = experiment.execute()

        console.print("✓ Experiment completed successfully!")
        console.print(f"Duration: {result.duration_seconds:.2f} seconds")
        console.print(f"Status: {result.status}")

        # Generate experiment manifest
        manifest = {
            "exp_id": name,
            "type": "cost-sweep",
            "base_config": str(cfg),
            "grid": grid,
            "experiment_id": experiment.experiment_id,
            "artifacts": result.artifacts,
            "seed": base_config.get("seed", 42),
        }
        with open(exp_dir / "manifest.json", "w") as f:
            json.dump(manifest, f, indent=2, default=str)

        # Generate inputs checksum (stub for now)
        checksum = {
            "bars_norm_hash": "dummy_bars_hash",
            "features_hash": "dummy_features_hash",
            "sip_hash": "dummy_sip_hash",
            "config_hash": "dummy_config_hash",
            "seed": base_config.get("seed", 42),
        }
        with open(exp_dir / "inputs_checksum.json", "w") as f:
            json.dump(checksum, f, indent=2)

        # Show results summary
        if result.results and "cost_sweep_analysis" in result.results:
            analysis = result.results["cost_sweep_analysis"]
            if "best_configuration" in analysis:
                best_config = analysis["best_configuration"]
                console.print("\n[bold]Best configuration:[/bold]")
                console.print(
                    f"  Commission per share: ${best_config.get('commission_per_share', 'N/A')}"
                )
                console.print(f"  Commission min: ${best_config.get('commission_min', 'N/A')}")
                console.print(f"  Slippage bps: {best_config.get('slippage_bps', 'N/A')}")

                if "best_metrics" in analysis:
                    best_metrics = analysis["best_metrics"]
                    console.print("\n[bold]Best metrics:[/bold]")
                    for metric, value in best_metrics.items():
                        if isinstance(value, float):
                            if metric in [
                                "total_return",
                                "max_drawdown",
                                "win_rate",
                                "profit_factor",
                            ]:
                                console.print(f"  {metric}: {value:.2%}")
                            else:
                                console.print(f"  {metric}: {value:.4f}")
                        else:
                            console.print(f"  {metric}: {value}")

        # Run compare if available
        try:
            from qx_cli.exp.compare import compare_experiments

            compare_experiments(exp_dir)
        except ImportError:
            console.print("Compare module not available, skipping comparison")

        console.print(f"Experiment {name} completed. Artifacts in {exp_dir}")

    except Exception as e:
        console.print(f"✗ Experiment failed: {e}", style="red")
        raise


def _create_cost_sweep_config(
    base_config: dict, grid_params: dict, name: str, exp_dir: pathlib.Path
) -> CostSweepConfig:
    """Create CostSweepConfig from base config and grid parameters."""

    # Extract cost parameters from grid or use defaults
    commission_per_share = grid_params.get("commission_per_share", [0.001, 0.0035, 0.005, 0.01])
    commission_min = grid_params.get("commission_min", [0.0, 0.35, 1.0])
    slippage_bps = grid_params.get("slippage_bps", [0, 2, 5, 10])
    tick_size = grid_params.get("tick_size", [0.01, 0.001])

    # Extract strategy parameters from base config
    strategy_config = base_config.get("strategy", {})
    portfolio_config = base_config.get("portfolio", {})

    return CostSweepConfig(
        name=name,
        description=base_config.get("description", f"Cost sweep experiment {name}"),
        symbols=base_config.get("symbols", ["AAPL", "GOOGL", "MSFT"]),
        start_date=base_config.get("start_date"),
        end_date=base_config.get("end_date"),
        output_dir=str(exp_dir),
        # Cost parameters
        commission_per_share=commission_per_share,
        commission_min=commission_min,
        slippage_bps=[int(bps) for bps in slippage_bps],
        tick_size=tick_size,
        # Strategy parameters
        strategy_name=strategy_config.get("name", "VwapRevert"),
        vwap_window=strategy_config.get("vwap_window", 30),
        min_rvol=strategy_config.get("min_rvol", 1.0),
        max_position_bars=strategy_config.get("max_position_bars", 50),
        position_size_pct=strategy_config.get("position_size_pct", 0.1),
        max_positions=strategy_config.get("max_positions", 5),
        # Portfolio parameters
        initial_cash=portfolio_config.get("initial_cash", 1_000_000.0),
        # Analysis parameters
        primary_metric=base_config.get("primary_metric", "sharpe_ratio"),
        secondary_metrics=base_config.get(
            "secondary_metrics", ["total_return", "max_drawdown", "win_rate"]
        ),
    )


def _parse_multi_grid(grid_str: str) -> dict[str, list[float]]:
    """Parse multi-param grid string."""
    params = {}
    for part in grid_str.split():
        key, values_str = part.split("=")
        values = [float(x.strip()) for x in values_str.split(",")]
        params[key] = values
    return params


def _generate_multi_grid_points(grid_params: dict[str, list[float]]) -> list[dict[str, float]]:
    """Generate all combinations (simple cartesian for now)."""
    # Stub: just one point per param set
    points = [{}]
    for key, values in grid_params.items():
        new_points = []
        for point in points:
            for val in values:
                new_points.append({**point, key: val})
        points = new_points
    return points


def _run_stub_cost_sweep(cfg: pathlib.Path, grid: str, name: str) -> None:
    """Fallback stub implementation when experiment modules aren't available."""
    console.print(f"Running stub cost-sweep experiment: {name}")

    # Parse grid (multi-param)
    grid_params = _parse_multi_grid(grid)

    # Create experiment directory
    exp_dir = pathlib.Path("experiments") / name
    exp_dir.mkdir(parents=True, exist_ok=True)

    # Load base config
    with open(cfg) as f:
        base_config = yaml.safe_load(f)

    # For each grid point, run backtest (stub)
    run_ids = []
    for params in _generate_multi_grid_points(grid_params):
        config = {**base_config, **params}
        run_id = str(uuid.uuid4())
        run_ids.append(run_id)
        run_dir = pathlib.Path("runs") / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Stub: generate dummy artifacts
        _generate_run_artifacts(run_dir, config)

    # Generate experiment manifest
    manifest = {
        "exp_id": name,
        "type": "cost-sweep",
        "base_config": str(cfg),
        "grid": grid,
        "run_ids": run_ids,
        "seed": base_config.get("seed", 42),
    }
    with open(exp_dir / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    # Generate inputs checksum (stub)
    checksum = {
        "bars_norm_hash": "dummy_bars_hash",
        "features_hash": "dummy_features_hash",
        "sip_hash": "dummy_sip_hash",
        "config_hash": "dummy_config_hash",
        "seed": base_config.get("seed", 42),
    }
    with open(exp_dir / "inputs_checksum.json", "w") as f:
        json.dump(checksum, f, indent=2)

    # Run compare if available
    try:
        from qx_cli.exp.compare import compare_experiments

        compare_experiments(exp_dir)
    except ImportError:
        console.print("Compare module not available, skipping comparison")

    console.print(f"Stub experiment {name} completed. Artifacts in {exp_dir}")


def _generate_run_artifacts(run_dir: pathlib.Path, config: dict) -> None:
    """Stub: Generate dummy run artifacts."""
    import pandas as pd

    # Dummy signals
    timestamps = pd.date_range("2023-01-01", periods=100, freq="1min")
    signals = pd.DataFrame(
        {
            "ts": timestamps,
            "symbol": ["AAPL"] * len(timestamps),
            "side": ["BUY"] * len(timestamps),
            "strength": [1.0] * len(timestamps),
        }
    )
    signals.to_parquet(run_dir / "signals.parquet")

    # Dummy orders, fills, positions, equity
    for fname in [
        "orders.parquet",
        "fills.parquet",
        "positions.parquet",
        "equity.parquet",
    ]:
        pd.DataFrame({"dummy": [1, 2, 3]}).to_parquet(run_dir / fname)

    # Dummy trades
    trades = pd.DataFrame(
        [
            {
                "entry_ts": pd.Timestamp("2023-01-01"),
                "exit_ts": pd.Timestamp("2023-01-02"),
                "symbol": "AAPL",
                "side": "BUY",
                "qty": 100,
                "entry_px": 100.0,
                "exit_px": 101.0,
                "pnl": 100.0,
                "r_multiple": 0.01,
                "mfe": 2.0,
                "mae": -1.0,
                "duration_s": 86400,
                "policy_tag": "test",
                "risk_tag": "test",
            }
        ]
    )
    trades.to_parquet(run_dir / "trades.parquet")

    # Dummy risk_rejects and allocation_log
    pd.DataFrame(
        [{"reason_code": "test", "limit_name": "test", "value": 1.0, "threshold": 0.5}]
    ).to_parquet(run_dir / "risk_rejects.parquet")
    pd.DataFrame({"allocation": [1.0]}).to_parquet(run_dir / "allocation_log.parquet")

    # Dummy metrics
    metrics = {
        "trades": 1,
        "avg_R": 0.01,
        "ES_95": -0.02,
        "pvalue_u": 0.5,
        "sharpe_CI_low": 0.5,
        "sharpe_CI_high": 1.5,
        "capacity_break_even_bps": 50.0,
    }
    with open(run_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)
