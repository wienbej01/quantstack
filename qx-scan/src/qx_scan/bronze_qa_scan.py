"""Bronze→Silver QA Scanner: Read-only analysis for normalization planning."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()


def scan_bronze_qa(root_path: str = "/home/jacobw/gcs-mount/bronze") -> dict[str, Any]:
    """Scan Bronze data for QA issues and normalization planning."""
    root = Path(root_path)
    if not root.exists():
        console.print(f"[red]Bronze root path {root_path} does not exist.[/red]")
        return {}

    scan_results = defaultdict(lambda: {"files": [], "issues": []})
    total_files = 0

    # Scan for Parquet files in Bronze
    for parquet_file in root.rglob("*.parquet"):
        try:
            console.print(f"Scanning: {parquet_file}")
            file_info = analyze_parquet_file(parquet_file)
            family = infer_family(parquet_file)
            scan_results[family]["files"].append(file_info)
            total_files += 1
        except Exception as e:
            console.print(f"[red]Error scanning {parquet_file}: {e}[/red]")

    # Generate normalization plan
    norm_plan = generate_normalization_plan(scan_results)

    console.print(f"Scanned {total_files} files across {len(scan_results)} families.")
    return {
        "scan_results": dict(scan_results),
        "normalization_plan": norm_plan,
        "total_files": total_files,
    }


def analyze_parquet_file(file_path: Path) -> dict[str, Any]:
    """Analyze a single Parquet file for schema and issues."""
    import pyarrow.parquet as pq

    table = pq.read_table(str(file_path))
    df = table.to_pandas()

    issues = []
    columns = df.columns.tolist()

    # Schema variant detection
    has_t = "t" in columns
    has_ts = "ts" in columns or "timestamp" in columns
    has_ohlcv = all(c in columns for c in ["open", "high", "low", "close", "volume"])

    if not has_ohlcv:
        issues.append("Missing required OHLCV columns")

    # Timestamp audit
    if has_t and has_ts:
        issues.append("Manual ts injection detected (both t and ts present)")
        ts_manual = True
    else:
        ts_manual = False

    if has_t:
        # Check if t is epoch ms
        if df["t"].dtype != "int64":
            issues.append("t column not int64 (expected epoch ms)")
    elif has_ts:
        # Infer timezone
        pass  # Stub

    # Type audit
    if "volume" in df.columns and df["volume"].dtype == "float64":
        issues.append("Volume is float (should be int)")

    # Check OHLCV values
    if has_ohlcv:
        if (df["high"] < df["low"]).any():
            issues.append("High < Low detected")
        if (df[["open", "high", "low", "close"]] < 0).any().any():
            issues.append("Negative OHLC values")
        if "volume" in df.columns and (df["volume"] < 0).any():
            issues.append("Negative volume")

    # Non-monotonic ts
    ts_col = "t" if has_t else ("ts" if "ts" in columns else "timestamp")
    if ts_col in df.columns and not df[ts_col].is_monotonic_increasing:
        issues.append("Non-monotonic timestamps")

    # Metrics
    metrics = {
        "row_count": len(df),
        "file_size": file_path.stat().st_size,
        "columns": columns,
        "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
        "min_ts": df[ts_col].min() if ts_col in df.columns else None,
        "max_ts": df[ts_col].max() if ts_col in df.columns else None,
    }

    return {
        "path": str(file_path),
        "schema_variant": "short" if has_t else "long",
        "ts_manual": ts_manual,
        "issues": issues,
        "metrics": metrics,
    }


def infer_family(file_path: Path) -> str:
    """Infer data family from path."""
    # Stub: use parent directory name
    return file_path.parent.name


def generate_normalization_plan(scan_results: dict[str, Any]) -> dict[str, Any]:
    """Generate normalization plan from scan results."""
    plan = {}

    for family, data in scan_results.items():
        variants = {}
        for file_info in data["files"]:
            variant = file_info["schema_variant"]
            if variant not in variants:
                variants[variant] = {
                    "rename_map": {},
                    "cast_rules": {},
                    "tz_rules": "UTC",
                    "files": 0,
                }
            variants[variant]["files"] += 1

            # Build rename map based on variant
            if variant == "short":
                variants[variant]["rename_map"] = {
                    "t": "ts",
                    "o": "open",
                    "h": "high",
                    "l": "low",
                    "c": "close",
                    "v": "volume",
                    "vw": "vwap",
                    "n": "trades",
                }
                variants[variant]["cast_rules"] = {
                    "volume": "int64",
                    "trades": "int64",
                }
            # Long form already normalized

        plan[family] = variants

    return plan


def main():
    """Main entry point for Bronze QA scan."""
    result = scan_bronze_qa()

    out_dir = Path("~/quantstack/qx-scan/out").expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    # bronze_scan.json
    with open(out_dir / "bronze_scan.json", "w") as f:
        json.dump(result["scan_results"], f, indent=2)

    # bronze_issues.md
    issues_md = "# Bronze QA Issues\n\n"
    issue_counts = defaultdict(int)
    for family, data in result["scan_results"].items():
        issues_md += f"## {family}\n"
        for file_info in data["files"]:
            if file_info["issues"]:
                issues_md += f"- {file_info['path']}: {', '.join(file_info['issues'])}\n"
                for issue in file_info["issues"]:
                    issue_counts[issue] += 1

    issues_md += "\n## Summary\n"
    for issue, count in issue_counts.items():
        issues_md += f"- {issue}: {count}\n"

    with open(out_dir / "bronze_issues.md", "w") as f:
        f.write(issues_md)

    # silver_norm_plan.json
    with open(out_dir / "silver_norm_plan.json", "w") as f:
        json.dump(result["normalization_plan"], f, indent=2)

    console.print(f"QA scan complete. Outputs in {out_dir}")


if __name__ == "__main__":
    main()
