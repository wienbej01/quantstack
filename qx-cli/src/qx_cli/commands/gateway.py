from __future__ import annotations

import json
from pathlib import Path

import typer
import yaml
from qx_broker.gateway import (
    GatewayConfig,
    GatewayController,
    GatewayManager,
    GatewayMonitor,
    GatewayRestarter,
    fetch_status,
    parse_clients,
)

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
    typer.echo(
        f"Established sockets: {report.estab_sockets} (clients={report.estab_clients})"
    )
    typer.echo(f"CLOSE-WAIT sockets: {report.close_wait_sockets}")
    if report.warnings:
        typer.echo("Warnings:")
        for warning in report.warnings:
            typer.echo(f"- {warning}")


@app.command("status")
def status(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, help="Gateway config path"),
) -> None:
    """Check IBKR system status page for maintenance."""
    try:
        gateway_config = load_config(config)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)

    report = fetch_status(gateway_config)
    typer.echo(report.message)
    if not report.ok:
        raise typer.Exit(1)


@app.command("clients")
def clients(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, help="Gateway config path"),
) -> None:
    """List active and seen client IDs (from gateway logs)."""
    try:
        gateway_config = load_config(config)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)

    snapshot = parse_clients(gateway_config)
    typer.echo(snapshot.message)
    typer.echo(f"Active client IDs: {snapshot.active_ids}")
    typer.echo(f"Seen client IDs: {snapshot.seen_ids}")


@app.command("start")
def start(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, help="Gateway config path"),
) -> None:
    """Start the gateway service."""
    try:
        gateway_config = load_config(config)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)

    controller = GatewayController(gateway_config)
    result = controller.start_gateway()
    for step in result.steps:
        typer.echo(f"- {step}")
    if not result.ok:
        raise typer.Exit(1)


@app.command("stop")
def stop(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, help="Gateway config path"),
) -> None:
    """Stop the gateway service."""
    try:
        gateway_config = load_config(config)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)

    controller = GatewayController(gateway_config)
    result = controller.stop_gateway()
    for step in result.steps:
        typer.echo(f"- {step}")
    if not result.ok:
        raise typer.Exit(1)


@app.command("close")
def close_gateway(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, help="Gateway config path"),
) -> None:
    """Alias for stop."""
    stop(config=config)


@app.command("reconnect")
def reconnect(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, help="Gateway config path"),
) -> None:
    """Stop and start gateway (alias for restart)."""
    restart(config=config, dry_run=False)


@app.command("restart-service")
def restart_service(
    service: str = typer.Argument(..., help="Service name to restart"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, help="Gateway config path"),
) -> None:
    """Restart a single service to drop its client connection."""
    try:
        gateway_config = load_config(config)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)

    controller = GatewayController(gateway_config)
    result = controller.restart_service(service)
    for step in result.steps:
        typer.echo(f"- {step}")
    if not result.ok:
        raise typer.Exit(1)


@app.command("drop-client")
def drop_client(
    client_id: int = typer.Argument(..., help="Client ID to drop"),
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, help="Gateway config path"),
) -> None:
    """Drop a client by restarting its owning service."""
    try:
        gateway_config = load_config(config)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)

    service_name = None
    for service, ids in gateway_config.expected_client_ids.items():
        if client_id in ids:
            service_name = service.replace("_", "-")
            break

    if not service_name:
        typer.echo(
            f"Client ID {client_id} not mapped in expected_client_ids.", err=True
        )
        raise typer.Exit(2)

    controller = GatewayController(gateway_config)
    result = controller.restart_service(service_name)
    for step in result.steps:
        typer.echo(f"- {step}")
    if not result.ok:
        raise typer.Exit(1)


@app.command("clean-clients")
def clean_clients(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, help="Gateway config path"),
) -> None:
    """Restart gateway if unknown client IDs are detected."""
    try:
        gateway_config = load_config(config)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)

    snapshot = parse_clients(gateway_config)
    expected_ids = {
        client_id
        for ids in gateway_config.expected_client_ids.values()
        for client_id in ids
    }
    unknown_ids = [cid for cid in snapshot.active_ids if cid not in expected_ids]
    if not unknown_ids:
        typer.echo("No unknown clients detected.")
        return

    typer.echo(f"Unknown clients detected: {unknown_ids}")
    restarter = GatewayRestarter(gateway_config)
    report = restarter.restart(dry_run=False)
    for step in report.steps:
        typer.echo(f"- {step}")
    if report.warnings:
        typer.echo("Warnings:")
        for warning in report.warnings:
            typer.echo(f"- {warning}")
    if not report.success:
        raise typer.Exit(1)


@app.command("monitor")
def monitor(
    config: Path = typer.Option(DEFAULT_CONFIG_PATH, help="Gateway config path"),
) -> None:
    """Run continuous gateway monitoring with auto-restart."""
    try:
        gateway_config = load_config(config)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2)

    GatewayMonitor(gateway_config).loop()


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
