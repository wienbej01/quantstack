"""Cost sweep testing command."""

import json
import pathlib
import uuid

import typer
import yaml
from rich.console import Console

from qx_cli.exp import app

console = Console()


@app.command("cost-sweep")
def cost_sweep(
    cfg: pathlib.Path = typer.Option(..., "--cfg", help="Base config file"),
    grid: str = typer.Option(..., "--grid", help="Grid parameters, e.g., bps=0.5,1,2 slippage_ticks=0,1,2"),
    name: str = typer.Option(..., "--name", help="Experiment ID"),
) -> None:
    """Run cost sweep test with varying cost parameters."""
    console.print(f"Running cost-sweep experiment: {name}")

    # Parse grid (multi-param)
    grid_params = _parse_multi_grid(grid)

    # Create experiment directory
    exp_dir = pathlib.Path("experiments") / name
    exp_dir.mkdir(parents=True, exist_ok=True)

    # Load base config
    with open(cfg) as f:
        base_config = yaml.safe_load(f)

    # For each grid point, run backtest
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

    # Run compare
    from qx_cli.exp.compare import compare_experiments
    compare_experiments(exp_dir)

    console.print(f"Experiment {name} completed. Artifacts in {exp_dir}")


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


def _generate_run_artifacts(run_dir: pathlib.Path, config: dict) -> None:
    """Stub: Generate dummy run artifacts."""
    import pandas as pd

    # Dummy signals
    timestamps = pd.date_range("2023-01-01", periods=100, freq="1min")
    signals = pd.DataFrame({
        "ts": timestamps,
        "symbol": ["AAPL"] * len(timestamps),
        "side": ["BUY"] * len(timestamps),
        "strength": [1.0] * len(timestamps),
    })
    signals.to_parquet(run_dir / "signals.parquet")

    # Dummy orders, fills, positions, equity
    for fname in ["orders.parquet", "fills.parquet", "positions.parquet", "equity.parquet"]:
        pd.DataFrame({"dummy": [1, 2, 3]}).to_parquet(run_dir / fname)

    # Dummy trades
    trades = pd.DataFrame([{
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
    }])
    trades.to_parquet(run_dir / "trades.parquet")

    # Dummy risk_rejects and allocation_log
    pd.DataFrame([{"reason_code": "test", "limit_name": "test", "value": 1.0, "threshold": 0.5}]).to_parquet(run_dir / "risk_rejects.parquet")
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