"""CLI for dataset instrumentation (Sprint 1)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from extensions.intraday_ml.eval import DatasetInstrumentor


def _load_master_config(path: Path) -> dict[str, Any]:
    with open(path) as handle:
        master = yaml.safe_load(handle)
    includes = master.get("includes", {})
    configs: dict[str, Any] = {}
    for name, cfg_path in includes.items():
        with open(cfg_path) as handle:
            configs[name] = yaml.safe_load(handle)

    if not configs:
        raise ValueError(
            "Master config must declare includes for universe/splits/features/targets."
        )

    return master, configs


def _resolve_artifact_dir(master_config: dict[str, Any], override: str | None) -> Path:
    if override:
        return Path(override)
    artifacts_root = master_config.get("artifacts") or "artefacts/extensions/intraday_ml/phaseA"
    return Path(artifacts_root) / "instrumentation"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Instrument datasets per split and emit label distributions.",
    )
    parser.add_argument("--config", required=True, help="Path to master Phase-A config.")
    parser.add_argument(
        "--splits",
        nargs="+",
        default=["train", "val", "test", "oos"],
        help="Target splits to instrument (must exist in splits config).",
    )
    parser.add_argument(
        "--artifact-dir",
        default=None,
        help="Override artifact directory for outputs.",
    )
    parser.add_argument(
        "--buffer-days",
        type=int,
        default=None,
        help="Override label buffer days (default from master or 5).",
    )

    args = parser.parse_args()
    master_config, configs = _load_master_config(Path(args.config))

    artifact_dir = _resolve_artifact_dir(master_config, args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    data_loader_config = dict(master_config.get("data", {}))
    data_loader_config.setdefault("root", "/home/jacobw/gcs-mount/gold")
    data_loader_config.setdefault("validate", True)
    data_loader_config.setdefault("sort", True)

    buffer_days = (
        args.buffer_days
        if args.buffer_days is not None
        else master_config.get("label_buffer_days", 5)
    )

    instrumentor = DatasetInstrumentor(
        splits_config=configs["splits"],
        sip_config=master_config.get("sip_filter", {"enabled": False}),
        features_config=configs["features"],
        targets_config=configs["targets"],
        data_loader_config=data_loader_config,
        artifact_dir=artifact_dir,
        label_buffer_days=buffer_days,
    )

    candidate_symbols = configs["universe"].get("symbols")
    if not candidate_symbols:
        raise ValueError("Universe config must define a non-empty 'symbols' list.")

    summary: list[dict[str, Any]] = []
    for split in args.splits:
        print(f"[instrumentor] Processing split '{split}'...")
        result = instrumentor.instrument_split(split, candidate_symbols)
        summary.append(
            {
                "split": split,
                "symbols": result.symbols,
                "rows": result.rows,
                "label_counts": result.label_counts,
                "dataset_path": str(result.dataset_path) if result.dataset_path else None,
                "daily_distribution_path": str(result.daily_distribution_path)
                if result.daily_distribution_path
                else None,
                "symbol_distribution_path": str(result.symbol_distribution_path)
                if result.symbol_distribution_path
                else None,
            }
        )
        print(
            f"   symbols={len(result.symbols)} rows={result.rows} label_counts={result.label_counts}"
        )

    summary_path = artifact_dir / "instrumentation_summary.json"
    with open(summary_path, "w") as handle:
        json.dump({"splits": summary}, handle, indent=2)
    print(f"[instrumentor] Summary written to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
