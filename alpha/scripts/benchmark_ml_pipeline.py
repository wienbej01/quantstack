#!/usr/bin/env python
"""Summarize cached-ML preprocessing artifacts for laptop capacity planning."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark cached ML pipeline artifacts"
    )
    parser.add_argument(
        "--cache-dir", default="output/ml_compact_cache", help="Compact cache directory"
    )
    parser.add_argument(
        "--output-path",
        default="reports/ml_pipeline_benchmark.md",
        help="Markdown benchmark report path",
    )
    args = parser.parse_args()

    manifest_path = Path(args.cache_dir) / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Compact cache manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text())
    entries = manifest.get("entries", [])
    total_rows = sum(int(entry["rows"]) for entry in entries)
    total_event_rows = sum(int(entry.get("event_rows", 0)) for entry in entries)
    source_totals: dict[str, int] = {}
    for entry in entries:
        for source, count in entry.get("source_counts", {}).items():
            source_totals[source] = source_totals.get(source, 0) + int(count)

    lines = [
        "# ML Pipeline Benchmark",
        "",
        f"- cache dir: `{args.cache_dir}`",
        f"- cached symbol-days: {len(entries)}",
        f"- cached rows: {total_rows}",
        f"- event rows: {total_event_rows}",
        f"- unique dates: {len({entry['date'] for entry in entries})}",
        f"- unique symbols: {len({entry['symbol'] for entry in entries})}",
        "",
        "## Source Mix",
        "",
    ]
    lines.extend(
        f"- {source}: {count}" for source, count in sorted(source_totals.items())
    )

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
