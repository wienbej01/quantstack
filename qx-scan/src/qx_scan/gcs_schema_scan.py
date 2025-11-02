#!/usr/bin/env python3
"""GCS schema scanner: Inspect bronze/silver/gold, unify schemas, detect anomalies."""

import json
from pathlib import Path
from typing import Any

import pyarrow.dataset as ds
from rich.console import Console
from rich.table import Table

console = Console()


def scan_gcs_schemas(root_path: str = "/home/jacobw/gcs-mount") -> dict[str, Any]:
    """Scan GCS-like directory for Parquet schemas."""
    root = Path(root_path)
    if not root.exists():
        console.print(f"[red]Root path {root_path} does not exist.[/red]")
        return {}

    families = {}
    issues = []
    total_scanned = 0

    # Scan subdirs for Parquet files, limit to 20 per subdir
    for subdir in root.iterdir():
        if subdir.is_dir():
            console.print(f"Scanning subdir: {subdir.name}")
            parquet_files = list(subdir.rglob("*.parquet"))[:20]  # Top 20 per folder
            for parquet_file in parquet_files:
                try:
                    console.print(f"Processing file: {parquet_file}")
                    dataset = ds.dataset(str(parquet_file), format="parquet")
                    schema = dataset.schema
                    family = subdir.name  # Use subdir as family
                    if family not in families:
                        families[family] = {"files": 0, "total_size": 0, "schemas": []}
                    families[family]["files"] += 1
                    families[family]["total_size"] += parquet_file.stat().st_size
                    families[family]["schemas"].append(str(schema))
                    total_scanned += 1
                    if total_scanned % 10 == 0:
                        console.print(f"Scanned {total_scanned} files so far.")
                except Exception as e:
                    issues.append(f"Error reading {parquet_file}: {e}")

    # Unify schemas per family
    for family, data in families.items():
        unique_schemas = list(set(data["schemas"]))
        data["unique_schemas"] = len(unique_schemas)
        if len(unique_schemas) > 1:
            issues.append(
                f"Family {family} has {len(unique_schemas)} different schemas."
            )

    console.print(f"Total scanned: {total_scanned}")
    return {"families": families, "issues": issues}


def main():
    """Main entry point."""
    result = scan_gcs_schemas()

    # Write outputs
    out_dir = Path("~/quantstack/qx-scan/out").expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON
    with open(out_dir / "gcs_schema.json", "w") as f:
        json.dump(result, f, indent=2)

    # MD
    md_content = "# GCS Schema Scan\n\n"
    for family, data in result["families"].items():
        md_content += f"## {family}\n- Files: {data['files']}\n- Total Size: {data['total_size']} bytes\n- Unique Schemas: {data['unique_schemas']}\n\n"

    with open(out_dir / "gcs_schema.md", "w") as f:
        f.write(md_content)

    # Issues
    with open(out_dir / "issues.md", "w") as f:
        f.write("# Issues\n\n" + "\n".join(result["issues"]))

    # Rich table
    table = Table(title="Top Families by Size")
    table.add_column("Family", style="cyan")
    table.add_column("Files", justify="right")
    table.add_column("Size (MB)", justify="right")

    sorted_families = sorted(
        result["families"].items(), key=lambda x: x[1]["total_size"], reverse=True
    )
    for family, data in sorted_families[:10]:  # Top 10
        size_mb = data["total_size"] / (1024 * 1024)
        table.add_row(family, str(data["files"]), f"{size_mb:.2f}")

    console.print(table)


if __name__ == "__main__":
    main()
