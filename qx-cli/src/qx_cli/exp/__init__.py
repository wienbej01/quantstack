"""Experiments harness CLI commands."""

import typer

app = typer.Typer()

from qx_cli.exp import compare, cost_sweep, entry_ab, portfolio, regime_slice, risk_grid, wf