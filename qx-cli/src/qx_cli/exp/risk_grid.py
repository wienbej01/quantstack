"""Risk grid testing command."""

import json
import pathlib
import uuid

import typer
from rich.console import Console

from qx_cli.exp import app

console = Console()


@app.command("risk-grid")
def risk_grid(
    cfg: pathlib.Path = typer.Option(..., "--cfg", help="Base config file"),
    grid: str = typer.Option(
        ..., "--grid", help="Grid parameters, e.g., max_risk_frac=0.005,0.01,0.02"
    ),
    name: str = typer.Option(..., "--name", help="Experiment ID"),
) -> None:
    """Run risk grid test with varying parameters."""
    console.print(f"Running risk-grid experiment: {name}")

    # Parse grid
    grid_params = _parse_grid(grid)

    # Create experiment directory
    exp_dir = pathlib.Path("experiments") / name
    exp_dir.mkdir(parents=True, exist_ok=True)

    # Load base config
    with open(cfg) as f:
        base_config = json.load(f)

    # For each grid point, run backtest
    run_ids = []
    for params in _generate_grid_points(grid_params):
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
        "type": "risk-grid",
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

    # Run compare
    from qx_cli.exp.compare import compare_experiments

    compare_experiments(exp_dir)

    console.print(f"Experiment {name} completed. Artifacts in {exp_dir}")


def _parse_grid(grid_str: str) -> dict[str, list[float]]:
    """Parse grid string like 'max_risk_frac=0.005,0.01,0.02'."""
    parts = grid_str.split("=")
    if len(parts) != 2:
        raise ValueError("Invalid grid format")
    key = parts[0]
    values = [float(x.strip()) for x in parts[1].split(",")]
    return {key: values}


def _generate_grid_points(
    grid_params: dict[str, list[float]]
) -> list[dict[str, float]]:
    """Generate all combinations of grid points."""
    # Simple single param for now
    points = []
    for key, values in grid_params.items():
        for val in values:
            points.append({key: val})
    return points


def _generate_run_artifacts(run_dir: pathlib.Path, config: dict) -> None:
    """Stub: Generate dummy run artifacts."""
    import pandas as pd

    # Dummy signals
    signals = pd.DataFrame(
        {
            "ts": pd.date_range("2023-01-01", periods=100, freq="1min"),
            "symbol": "AAPL",
            "side": "BUY",
            "strength": 1.0,
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
    )
    trades.to_parquet(run_dir / "trades.parquet")

    # Dummy risk_rejects and allocation_log
    pd.DataFrame(
        {"reason_code": "test", "limit_name": "test", "value": 1.0, "threshold": 0.5}
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
