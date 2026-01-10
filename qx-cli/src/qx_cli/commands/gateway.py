from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml

from qx_broker.gateway import GatewayConfig, GatewayManager, GatewayRestarter

app = typer.Typer(help="IBKR Gateway control and health checks")

DEFAULT_CONFIG_PATH = Path("configs/ibkr_gateway.yaml")


def load_config(config_path: Path) -> GatewayConfig:
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config not found at {config_path}. Run `qx gateway init-config` or "
            "provide --config."
        )
    data = yaml.safe_load(config_path.read_text()) or {}
    return GatewayConfig.from_dict(data)


@app.command("health")
def health(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, help="Gateway config path"),
    as_json: bool = typer.Option(False, "--json", help="Output JSON payload"),
) -> None:
    """Report current gateway health (port, processes, sockets)."""
    try:
        gateway_config = load_config(config)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)

    manager = GatewayManager(gateway_config)
    report = manager.check_health()

    if as_json:
        typer.echo(report.to_json())
        return

    typer.echo(f"Gateway reachable: {'yes' if report.reachable else 'no'}")
    typer.echo(f"Gateway processes: {report.process_count}")
    typer.echo(f"Established sockets: {report.estab_sockets} (clients={report.estab_clients})")
    typer.echo(f"CLOSE-WAIT sockets: {report.close_wait_sockets}")
    if report.warnings:
        typer.echo("Warnings:")
        for warning in report.warnings:
            typer.echo(f"- {warning}")


@app.command("restart")
def restart(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, help="Gateway config path"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Print actions without executing"
    ),
) -> None:
    """Restart gateway with service drain/start sequencing."""
    try:
        gateway_config = load_config(config)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)

    restarter = GatewayRestarter(gateway_config)
    report = restarter.restart(dry_run=dry_run)

    typer.echo("Restart steps:")
    for step in report.steps:
        typer.echo(f"- {step}")

    if report.warnings:
        typer.echo("Warnings:")
        for warning in report.warnings:
            typer.echo(f"- {warning}")

    if not report.success:
        raise typer.Exit(1)


@app.command("init-config")
def init_config(
    output_path: Path = typer.Option(DEFAULT_CONFIG_PATH, help="Output config path"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing file"),
) -> None:
    """Write a default gateway config file."""
    if output_path.exists() and not force:
        typer.echo(
            f"Config already exists at {output_path}. Use --force to overwrite.",
            err=True,
        )
        raise typer.Exit(2)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    template = {
        "host": "127.0.0.1",
        "port": 7497,
        "process_patterns": ["ibgateway", "tws"],
        "zombie_threshold": 10,
        "expected_client_ids": {
            "l2_scalping": [20, 21],
            "l2_collector": [521],
            "intraday_paper": [998, 11],
        },
    }
    output_path.write_text(yaml.safe_dump(template, sort_keys=False))
    typer.echo(f"Wrote config to {output_path}")
