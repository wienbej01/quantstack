"""
Warehouse CLI commands for QuantStack.

Provides commands to ingest experiments into the warehouse
and query warehouse data.
"""

import json
import pathlib

import typer
from rich.table import Table

from ..utils import console

app = typer.Typer(help="Warehouse commands for experiment ingestion and querying")


@app.command()
def ingest(
    warehouse_path: str | None = typer.Option(
        "~/strategy_repo/warehouse/warehouse.db",
        "--warehouse-path",
        "-w",
        help="Path to warehouse database",
    ),
    runs_path: str | None = typer.Option(
        "~/quantstack/runs", "--runs-path", "-r", help="Path to runs directory"
    ),
    experiments_path: str | None = typer.Option(
        "~/quantstack/experiments",
        "--experiments-path",
        "-e",
        help="Path to experiments directory",
    ),
    experiment_id: str | None = typer.Option(
        None,
        "--experiment-id",
        "-x",
        help="Specific experiment ID to ingest (default: all)",
    ),
    track_lineage: bool = typer.Option(
        True,
        "--track-lineage/--no-track-lineage",
        help="Track data lineage and versioning",
    ),
) -> None:
    """
    Ingest experiment runs into the warehouse.

    Processes runs/ and experiments/ directories and loads
    artifacts into the warehouse for querying.
    """
    console.print("🚀 Starting warehouse ingestion...", style="bold blue")

    try:
        # Import here to avoid dependency issues if not available
        from strategy_repo.ingestors.ingest_runs import WarehouseIngestor

        with WarehouseIngestor(
            warehouse_path=warehouse_path,
            runs_path=runs_path,
            experiments_path=experiments_path,
        ) as ingestor:

            if experiment_id:
                # TODO: Implement single experiment ingestion
                console.print(
                    "⚠️  Single experiment ingestion not yet implemented. Ingesting all experiments.",
                    style="yellow",
                )
                results = ingestor.ingest_all()
            else:
                results = ingestor.ingest_all()

        console.print("✅ Ingestion completed successfully!", style="bold green")
        console.print(f"   Experiments processed: {results['experiments_processed']}")
        console.print(f"   Runs processed: {results['runs_processed']}")

        # Track lineage if requested
        if track_lineage:
            try:
                from strategy_repo.ingestors.lineage import LineageIngestor

                console.print("🔗 Tracking data lineage...", style="blue")

                lineage_ingestor = LineageIngestor(
                    warehouse_path.replace("/warehouse.db", "")
                )

                for exp_dir in pathlib.Path(experiments_path).expanduser().iterdir():
                    if exp_dir.is_dir():
                        try:
                            exp_id = lineage_ingestor.track_experiment(exp_dir)
                            # Track runs for this experiment
                            manifest_path = exp_dir / "manifest.json"
                            if manifest_path.exists():
                                with open(manifest_path) as f:
                                    manifest = json.load(f)
                                for run_id in manifest.get("run_ids", []):
                                    run_dir = (
                                        pathlib.Path(runs_path).expanduser() / run_id
                                    )
                                    if run_dir.exists():
                                        lineage_ingestor.track_run(run_dir, exp_id)
                        except Exception as e:
                            console.print(
                                f"   Lineage tracking failed for {exp_dir.name}: {e}",
                                style="dim yellow",
                            )

                console.print("✅ Lineage tracking completed!", style="bold green")

            except ImportError as e:
                console.print(f"⚠️  Lineage tracking not available: {e}", style="yellow")
            except Exception as e:
                console.print(f"⚠️  Lineage tracking failed: {e}", style="yellow")

        if results["errors"]:
            console.print(f"   Errors: {len(results['errors'])}", style="yellow")
            for error in results["errors"][:3]:
                console.print(f"     - {error}", style="dim yellow")

    except ImportError as e:
        console.print(f"❌ Warehouse ingestor not available: {e}", style="red")
        console.print("   Make sure the strategy_repo is properly set up.", style="red")
    except Exception as e:
        console.print(f"❌ Ingestion failed: {e}", style="red")


@app.command()
def schema(
    warehouse_path: str | None = typer.Option(
        "~/strategy_repo/warehouse/warehouse.db",
        "--warehouse-path",
        "-w",
        help="Path to warehouse database",
    )
) -> None:
    """Show warehouse schema."""
    try:
        from strategy_repo.llm.mcp_server import WarehouseMCP

        with WarehouseMCP(warehouse_path) as mcp:
            schema = mcp.get_schema()

        console.print("📋 Warehouse Schema", style="bold blue")

        # Tables
        if schema.tables:
            console.print("\n📊 Tables:", style="bold")
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Table", style="cyan")
            table.add_column("Columns", style="white")
            table.add_column("Types", style="green")

            for table_name, columns in schema.tables.items():
                col_list = ", ".join(columns.keys())
                type_list = ", ".join(columns.values())
                table.add_row(table_name, col_list, type_list)

            console.print(table)

        # Views
        if schema.views:
            console.print("\n👁️  Materialized Views:", style="bold")
            view_table = Table(show_header=True, header_style="bold magenta")
            view_table.add_column("View", style="cyan")
            view_table.add_column("Columns", style="white")
            view_table.add_column("Types", style="green")

            for view_name, columns in schema.views.items():
                col_list = ", ".join(columns.keys())
                type_list = ", ".join(columns.values())
                view_table.add_row(view_name, col_list, type_list)

            console.print(view_table)

    except ImportError as e:
        console.print(f"❌ Warehouse MCP server not available: {e}", style="red")
    except Exception as e:
        console.print(f"❌ Failed to get schema: {e}", style="red")


@app.command()
def query(
    sql_query: str = typer.Argument(..., help="SQL query to execute"),
    warehouse_path: str | None = typer.Option(
        "~/strategy_repo/warehouse/warehouse.db",
        "--warehouse-path",
        "-w",
        help="Path to warehouse database",
    ),
    limit: int | None = typer.Option(
        10, "--limit", "-l", help="Maximum number of rows to return"
    ),
) -> None:
    """Execute SQL query on warehouse."""
    try:
        from strategy_repo.llm.mcp_server import QueryRequest, WarehouseMCP

        with WarehouseMCP(warehouse_path) as mcp:
            request = QueryRequest(query=sql_query, limit=limit)
            response = mcp.execute_query(request)

        if response["success"]:
            if response["row_count"] > 0:
                console.print(
                    f"📊 Query Results ({response['row_count']} rows):",
                    style="bold blue",
                )
                table = Table(show_header=True, header_style="bold magenta")

                # Add columns
                for col in response["columns"]:
                    table.add_column(col)

                # Add rows
                for row in response["rows"]:
                    table.add_row(
                        *[str(val) if val is not None else "NULL" for val in row]
                    )

                console.print(table)
            else:
                console.print("📊 Query returned no results.", style="yellow")
        else:
            console.print(f"❌ Query failed: {response['error']}", style="red")

    except ImportError as e:
        console.print(f"❌ Warehouse MCP server not available: {e}", style="red")
    except Exception as e:
        console.print(f"❌ Query execution failed: {e}", style="red")


@app.command()
def views(
    warehouse_path: str | None = typer.Option(
        "~/strategy_repo/warehouse/warehouse.db",
        "--warehouse-path",
        "-w",
        help="Path to warehouse database",
    )
) -> None:
    """List all available materialized views."""
    try:
        from strategy_repo.llm.mcp_server import WarehouseMCP

        with WarehouseMCP(warehouse_path) as mcp:
            views = mcp.list_views()

        console.print("👁️  Available Materialized Views:", style="bold blue")
        if views:
            for view in views:
                console.print(f"   • {view}", style="cyan")
        else:
            console.print("   No views found.", style="yellow")

    except ImportError as e:
        console.print(f"❌ Warehouse MCP server not available: {e}", style="red")
    except Exception as e:
        console.print(f"❌ Failed to list views: {e}", style="red")


@app.command()
def view(
    view_name: str = typer.Argument(..., help="Name of the view"),
    warehouse_path: str | None = typer.Option(
        "~/strategy_repo/warehouse/warehouse.db",
        "--warehouse-path",
        "-w",
        help="Path to warehouse database",
    ),
) -> None:
    """Show details of a specific materialized view."""
    try:
        from strategy_repo.llm.mcp_server import WarehouseMCP

        with WarehouseMCP(warehouse_path) as mcp:
            view_info = mcp.get_view(view_name)

        console.print(f"👁️  View: {view_info['view_name']}", style="bold blue")
        console.print(f"📊 Columns ({len(view_info['columns'])}):", style="bold")
        for col in view_info["columns"]:
            console.print(f"   • {col}", style="cyan")

        if view_info["sample_data"]:
            console.print(
                f"\n📋 Sample Data ({view_info['sample_count']} rows):", style="bold"
            )
            table = Table(show_header=True, header_style="bold magenta")
            for col in view_info["columns"]:
                table.add_column(col)

            for row in view_info["sample_data"]:
                table.add_row(*[str(val) if val is not None else "NULL" for val in row])

            console.print(table)
        else:
            console.print("\n📋 No sample data available.", style="yellow")

    except ImportError as e:
        console.print(f"❌ Warehouse MCP server not available: {e}", style="red")
    except Exception as e:
        console.print(f"❌ Failed to get view: {e}", style="red")


@app.command()
def experiments(
    search: str | None = typer.Option(
        "", "--search", "-s", help="Search term for experiment names"
    ),
    limit: int | None = typer.Option(
        10, "--limit", "-l", help="Maximum number of experiments to show"
    ),
    warehouse_path: str | None = typer.Option(
        "~/strategy_repo/warehouse/warehouse.db",
        "--warehouse-path",
        "-w",
        help="Path to warehouse database",
    ),
) -> None:
    """List experiments from warehouse."""
    try:
        from strategy_repo.llm.mcp_server import WarehouseMCP

        with WarehouseMCP(warehouse_path) as mcp:
            response = mcp.search_experiments(search, limit)

        if response["success"] and response["row_count"] > 0:
            console.print(
                f"🧪 Experiments ({response['row_count']} found):", style="bold blue"
            )
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Experiment ID", style="cyan")
            table.add_column("Name", style="white")
            table.add_column("Type", style="green")
            table.add_column("Created", style="yellow")
            table.add_column("Variants", style="magenta")
            table.add_column("Status", style="blue")

            for row in response["rows"]:
                table.add_row(*[str(val) if val is not None else "NULL" for val in row])

            console.print(table)
        else:
            console.print("🧪 No experiments found.", style="yellow")

    except ImportError as e:
        console.print(f"❌ Warehouse MCP server not available: {e}", style="red")
    except Exception as e:
        console.print(f"❌ Failed to list experiments: {e}", style="red")


@app.command()
def leaderboard(
    metric: str = typer.Option(
        "sharpe_ci_high", "--metric", "-m", help="Performance metric to rank by"
    ),
    limit: int = typer.Option(
        10, "--limit", "-l", help="Maximum number of results to show"
    ),
    warehouse_path: str | None = typer.Option(
        "~/strategy_repo/warehouse/warehouse.db",
        "--warehouse-path",
        "-w",
        help="Path to warehouse database",
    ),
) -> None:
    """Show top performing runs."""
    try:
        from strategy_repo.llm.mcp_server import WarehouseMCP

        with WarehouseMCP(warehouse_path) as mcp:
            response = mcp.get_top_performers(metric, limit)

        if response["success"] and response["row_count"] > 0:
            console.print(f"🏆 Top Performers by {metric}:", style="bold blue")
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Run ID", style="cyan")
            table.add_column("Experiment", style="white")
            table.add_column("Variant", style="green")
            table.add_column("Policy", style="yellow")
            table.add_column(metric.replace("_", " ").title(), style="magenta")
            table.add_column("Trades", style="blue")
            table.add_column("Avg R", style="red")
            table.add_column("Win Rate", style="green")

            for row in response["rows"]:
                table.add_row(*[str(val) if val is not None else "NULL" for val in row])

            console.print(table)
        else:
            console.print("🏆 No performance data found.", style="yellow")

    except ImportError as e:
        console.print(f"❌ Warehouse MCP server not available: {e}", style="red")
    except Exception as e:
        console.print(f"❌ Failed to get leaderboard: {e}", style="red")


@app.command()
def status(
    warehouse_path: str | None = typer.Option(
        "~/strategy_repo/warehouse/warehouse.db",
        "--warehouse-path",
        "-w",
        help="Path to warehouse database",
    )
) -> None:
    """Show warehouse status and statistics."""
    try:
        from strategy_repo.llm.mcp_server import WarehouseMCP

        console.print("📊 Warehouse Status:", style="bold blue")

        with WarehouseMCP(warehouse_path) as mcp:
            # Get table counts
            tables = [
                "dim_experiments",
                "dim_runs",
                "fact_trades",
                "fact_signals",
                "fact_equity",
            ]
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Entity", style="cyan")
            table.add_column("Count", style="white")

            for table_name in tables:
                try:
                    count_result = mcp.con.execute(
                        f"SELECT COUNT(*) FROM {table_name}"
                    ).fetchone()
                    count = count_result[0] if count_result else 0
                    entity_name = (
                        table_name.replace("dim_", "").replace("fact_", "").title()
                    )
                    table.add_row(entity_name, str(count))
                except Exception:
                    table.add_row(
                        table_name.replace("dim_", "").replace("fact_", ""), "Error"
                    )

            console.print(table)

            # Get view count
            views = mcp.list_views()
            console.print(f"\n👁️  Materialized Views: {len(views)}", style="bold")

            if views:
                console.print("Available views: " + ", ".join(views), style="dim")

    except ImportError as e:
        console.print(f"❌ Warehouse MCP server not available: {e}", style="red")
    except Exception as e:
        console.print(f"❌ Failed to get status: {e}", style="red")


@app.command()
def lineage(
    experiment_id: str | None = typer.Option(
        None, "--experiment-id", "-x", help="Experiment ID to check lineage for"
    ),
    warehouse_path: str | None = typer.Option(
        "~/strategy_repo/warehouse",
        "--warehouse-path",
        "-w",
        help="Path to warehouse directory",
    ),
) -> None:
    """Show data lineage and reproducibility information."""
    try:
        from strategy_repo.ingestors.lineage import LineageIngestor

        lineage_ingestor = LineageIngestor(warehouse_path)

        if experiment_id:
            # Show specific experiment lineage
            console.print(
                f"🔗 Lineage for experiment: {experiment_id}", style="bold blue"
            )

            repro_check = lineage_ingestor.verify_experiment_reproducibility(
                experiment_id
            )
            status = (
                "✅ REPRODUCIBLE"
                if repro_check["reproducible"]
                else "❌ NOT REPRODUCIBLE"
            )
            console.print(
                f"Status: {status}",
                style="bold green" if repro_check["reproducible"] else "bold red",
            )

            if repro_check["input_hashes"]:
                console.print("\nInput Hashes:", style="bold")
                for hash_type, hash_value in repro_check["input_hashes"].items():
                    console.print(f"   {hash_type}: {hash_value}")

            if repro_check["issues"]:
                console.print("\nIssues:", style="bold red")
                for issue in repro_check["issues"]:
                    console.print(f"   • {issue}")

            # Show lineage chain
            lineage = lineage_ingestor.get_experiment_lineage(experiment_id)
            if lineage:
                console.print("\nLineage Chain:", style="bold")
                for i, node in enumerate(lineage):
                    console.print(
                        f"   {i+1}. {node['type']}: {node['name']} ({node['id']})"
                    )
                    console.print(f"      Hash: {node['hash']}")
                    console.print(f"      Created: {node['created_at']}")

        else:
            # Show all experiments with reproducibility status
            console.print("🔗 Experiment Reproducibility Status:", style="bold blue")

            # Load lineage and check all experiments
            experiments = [
                node
                for node in lineage_ingestor.lineage.nodes.values()
                if node.type == "experiment"
            ]

            if not experiments:
                console.print("No experiments found in lineage.", style="yellow")
                return

            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Experiment ID", style="cyan")
            table.add_column("Name", style="white")
            table.add_column("Reproducible", style="green")
            table.add_column("Created", style="yellow")

            for exp in sorted(experiments, key=lambda x: x.created_at, reverse=True):
                repro_check = lineage_ingestor.verify_experiment_reproducibility(exp.id)
                status = "✅ Yes" if repro_check["reproducible"] else "❌ No"
                table.add_row(
                    exp.id, exp.name, status, exp.created_at.strftime("%Y-%m-%d %H:%M")
                )

            console.print(table)

    except ImportError as e:
        console.print(f"❌ Lineage tracking not available: {e}", style="red")
    except Exception as e:
        console.print(f"❌ Failed to get lineage: {e}", style="red")


@app.command()
def reset(
    warehouse_path: str | None = typer.Option(
        "~/strategy_repo/warehouse/warehouse.db",
        "--warehouse-path",
        "-w",
        help="Path to warehouse database",
    ),
    confirm: bool = typer.Option(
        False, "--confirm", "-y", help="Confirm warehouse reset"
    ),
) -> None:
    """Reset warehouse (delete all data)."""
    if not confirm:
        console.print("❌ Warehouse reset requires --confirm flag", style="red")
        console.print("   This will delete all warehouse data!", style="bold red")
        return

    console.print("🗑️  Resetting warehouse...", style="bold red")

    try:
        warehouse_file = pathlib.Path(warehouse_path).expanduser()
        if warehouse_file.exists():
            warehouse_file.unlink()
            console.print("   Deleted warehouse database", style="red")

        # Also reset catalog
        catalog_path = pathlib.Path(warehouse_path).parent / "catalog"
        if catalog_path.exists():
            import shutil

            shutil.rmtree(catalog_path)
            console.print("   Deleted catalog directory", style="red")

        # Reset lineage
        lineage_file = pathlib.Path(warehouse_path).parent / "lineage.json"
        if lineage_file.exists():
            lineage_file.unlink()
            console.print("   Deleted lineage data", style="red")

        console.print("✅ Warehouse reset completed!", style="bold red")

    except Exception as e:
        console.print(f"❌ Failed to reset warehouse: {e}", style="red")


if __name__ == "__main__":
    app()
