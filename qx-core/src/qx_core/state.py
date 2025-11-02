"""Run state management."""

from datetime import UTC, datetime
from pathlib import Path

import yaml


def write_state(outdir: str, metadata: dict) -> str:
    """Write project_state.yaml with run metadata."""
    state = {
        "timestamp": datetime.now(UTC).isoformat(),
        "versions": metadata.get("versions", {}),
        "shas": metadata.get("shas", {}),
        "config_hash": metadata.get("config_hash", ""),
        "data_range": metadata.get("data_range", {}),
        "symbols": metadata.get("symbols", []),
        "seeds": metadata.get("seeds", {}),
        "artifacts": metadata.get("artifacts", {}),
    }
    path = Path(outdir) / "state" / "project_state.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(state, f, default_flow_style=False)
    return str(path)
