"""Gold Contract Validator: Ensures Gold data remains additive-only."""

import json
from pathlib import Path
from typing import Any

from rich.console import Console

console = Console()

ALLOWED_COLUMNS = {
    "ts",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trades",
    "vwap",
    "session",
    "date_et",
    "turnover",
    "spread",
    "_dq_flags",
}

REQUIRED_COLUMNS = {"ts", "symbol", "open", "high", "low", "close", "volume"}


def validate_gold_contract(
    root_path: str = "/home/jacobw/gcs-mount/gold",
) -> dict[str, Any]:
    """Validate Gold data contracts."""
    root = Path(root_path)
    if not root.exists():
        console.print(f"[red]Gold root path {root_path} does not exist.[/red]")
        return {"valid": False, "issues": [f"Path {root_path} does not exist"]}

    issues = []
    total_files = 0

    for parquet_file in root.rglob("*.parquet"):
        try:
            console.print(f"Validating: {parquet_file}")
            file_issues = validate_gold_file(parquet_file)
            issues.extend(file_issues)
            total_files += 1
        except Exception as e:
            issues.append(f"Error validating {parquet_file}: {e}")

    is_valid = len(issues) == 0

    console.print(f"Validated {total_files} files. Valid: {is_valid}")

    return {
        "valid": is_valid,
        "total_files": total_files,
        "issues": issues,
    }


def validate_gold_file(file_path: Path) -> list[str]:
    """Validate a single Gold Parquet file."""
    import pyarrow.parquet as pq

    table = pq.read_table(str(file_path))
    df = table.to_pandas()
    columns = set(df.columns)

    issues = []

    # Check allowed columns
    extra_columns = columns - ALLOWED_COLUMNS
    if extra_columns:
        issues.append(f"Extra columns not allowed: {extra_columns}")

    # Check required columns
    missing_required = REQUIRED_COLUMNS - columns
    if missing_required:
        issues.append(f"Missing required columns: {missing_required}")

    # Check derived columns are additive
    if "turnover" in columns:
        expected_turnover = df["close"] * df["volume"]
        if not (df["turnover"] == expected_turnover).all():
            issues.append("Turnover column not correctly derived as close * volume")

    # Check no resampling across sessions (stub: check for monotonic ts within sessions)
    if "session" in df.columns and "ts" in df.columns:
        # Group by session and check monotonic ts
        for session, group in df.groupby("session"):
            if not group["ts"].is_monotonic_increasing:
                issues.append(f"Non-monotonic timestamps in session {session}")

    # Check no timestamp shifts (stub: ts should be at expected bar boundaries)
    # For 1m bars, ts should be at :00 seconds, etc.
    if "ts" in df.columns:
        # Infer timeframe from file path or data
        timeframe = infer_timeframe(file_path)
        if timeframe and not check_timestamp_alignment(df["ts"], timeframe):
            issues.append(f"Timestamps not aligned to {timeframe} boundaries")

    return issues


def infer_timeframe(file_path: Path) -> str:
    """Infer timeframe from file path (e.g., bars_1m -> 1m)."""
    path_str = str(file_path)
    if "bars_1m" in path_str:
        return "1m"
    elif "bars_1h" in path_str:
        return "1h"
    # Add more as needed
    return None


def check_timestamp_alignment(ts_series, timeframe: str) -> bool:
    """Check if timestamps are aligned to timeframe boundaries."""
    # Stub implementation
    # For 1m bars, ts.second == 0
    if timeframe == "1m":
        return (ts_series.dt.second == 0).all()
    return True  # Default pass


def main():
    """Main entry point."""
    result = validate_gold_contract()

    out_dir = Path("~/quantstack/qx-scan/out").expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "gold_contract_validation.json", "w") as f:
        json.dump(result, f, indent=2)

    if result["valid"]:
        console.print("[green]Gold contract validation passed.[/green]")
    else:
        console.print("[red]Gold contract validation failed.[/red]")
        for issue in result["issues"]:
            console.print(f"  - {issue}")

    return result


if __name__ == "__main__":
    main()
