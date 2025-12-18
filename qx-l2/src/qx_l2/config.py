"""Configuration management for L2 collector."""

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG = {
    "system": {
        "name": "L2COLLECT",
        "client_id": 500,
    },
    "ibkr": {
        "host": "127.0.0.1",
        "port": 7497,
        "timeout": 30,
    },
    "symbols": {
        "mode": "hybrid",
        "core": ["HAL", "PFE", "LUV"],
        "rotating_pool": ["MOS", "ACHR", "CRGY", "FCX", "AA"],
        "max_symbols": 6,
    },
    "collection": {
        "levels": 10,
        "snapshot_interval_ms": 1000,
        "smart_depth": True,
        "rotate_seconds": 300,
    },
    "schedule": {
        "timezone": "America/New_York",
        "windows": ["09:30-10:30", "11:30-12:30", "14:00-15:00", "15:00-16:00"],
        "skip_weekends": True,
    },
    "storage": {
        "base_dir": "./data/l2",
        "format": "parquet",
        "compression": "snappy",
        "flush_rows": 300,
        "retention_days": 90,
    },
    "features": {
        "enabled": True,
        "obi_levels": [1, 3, 5, 10],
        "delta_windows_sec": [5, 30],
    },
    "journal": {
        "enabled": True,
        "db_path": "./data/l2/journal.db",
    },
}


def load_config(config_path: str = None) -> dict[str, Any]:
    """Load configuration from YAML file with defaults."""
    config = DEFAULT_CONFIG.copy()

    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            user_config = yaml.safe_load(f) or {}
        config = _deep_merge(config, user_config)

    # Environment variable overrides
    config = _apply_env_overrides(config)

    return config


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _apply_env_overrides(config: dict) -> dict:
    """Apply environment variable overrides."""
    env_mappings = {
        "L2_IBKR_HOST": ("ibkr", "host"),
        "L2_IBKR_PORT": ("ibkr", "port"),
        "L2_CLIENT_ID": ("system", "client_id"),
        "L2_STORAGE_DIR": ("storage", "base_dir"),
    }

    for env_var, path in env_mappings.items():
        value = os.environ.get(env_var)
        if value:
            section, key = path
            if key == "port" or key == "client_id":
                value = int(value)
            config[section][key] = value

    return config
