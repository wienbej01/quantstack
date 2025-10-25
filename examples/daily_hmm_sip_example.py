"""
Example: Using Daily HMM_SIP with VWAP Strategy

This example demonstrates how to use the daily HMM_SIP universe selection
feature with the VWAP reversion strategy.
"""

import copy
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore


def create_daily_hmm_config() -> dict[str, Any]:
    """Create experiment configuration with daily HMM_SIP"""
    config = {
        "base_config": {
            "gold_root": "/home/jacobw/gcs-mount",
            "family": "stocks",
            "dates": ["2024-01-03", "2024-01-04", "2024-01-05"],
            "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META"],
            "features": [
                {
                    "name": "core_basics",
                    "params": {
                        "vwap_window_m": 30,
                        "rel_vol_window_m": 30,
                        "atr_window": 14,
                    },
                }
            ],
            "policy": "vwap_revert",
            "policy_params": {
                "entry_threshold": 0.02,
                "exit_threshold": 0.01,
                "max_position_bars": 20,
                "max_concurrent_positions": 3,
            },
            "sip": {
                "method": "hmm",
                "config": {"mode": "daily", "score_floor": 0.01, "top_k": 3},
            },
        },
        "variants": [
            {"name": "daily_hmm_default", "policy_params": {}},
            {
                "name": "daily_hmm_aggressive",
                "policy_params": {
                    "entry_threshold": 0.015,
                    "max_concurrent_positions": 5,
                },
            },
        ],
    }
    return config


def create_comparison_configs() -> tuple[dict[str, Any], dict[str, Any]]:
    """Create configs for comparing daily vs legacy HMM_SIP"""

    # Daily HMM_SIP config
    daily_config = {
        "base_config": {
            "gold_root": "/home/jacobw/gcs-mount",
            "family": "stocks",
            "dates": ["2024-01-03", "2024-01-04"],
            "symbols": ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "META", "NVDA", "JPM"],
            "features": [
                {
                    "name": "core_basics",
                    "params": {
                        "vwap_window_m": 30,
                        "rel_vol_window_m": 30,
                        "atr_window": 14,
                    },
                }
            ],
            "policy": "vwap_revert",
            "policy_params": {
                "entry_threshold": 0.02,
                "exit_threshold": 0.01,
                "max_position_bars": 20,
                "max_concurrent_positions": 3,
            },
            "sip": {
                "method": "hmm",
                "config": {"mode": "daily", "score_floor": 0.01, "top_k": 4},
            },
        },
        "variants": [
            {"name": "daily_conservative", "policy_params": {"entry_threshold": 0.025}}
        ],
    }

    # Legacy HMM_SIP config (create fresh copy before daily config is modified)
    legacy_config = copy.deepcopy(daily_config)
    legacy_config["base_config"]["sip"]["config"]["mode"] = "legacy"  # type: ignore[index]
    legacy_config["variants"][0]["name"] = "legacy_conservative"  # type: ignore[index]

    return daily_config, legacy_config


def save_configs() -> tuple[Path, Path, Path]:
    """Save example configurations to files"""

    # Create daily HMM example
    daily_config = create_daily_hmm_config()
    daily_path = Path("daily_hmm_vwap_example.yaml")
    with open(daily_path, "w") as f:
        yaml.dump(daily_config, f, default_flow_style=False)

    # Create comparison configs
    daily_comp_config, legacy_config = create_comparison_configs()

    daily_comp_path = Path("daily_hmm_comparison.yaml")
    with open(daily_comp_path, "w") as f:
        yaml.dump(daily_comp_config, f, default_flow_style=False)

    legacy_path = Path("legacy_hmm_comparison.yaml")
    with open(legacy_path, "w") as f:
        yaml.dump(legacy_config, f, default_flow_style=False)

    return daily_path, daily_comp_path, legacy_path


def print_config_summary(config: dict[str, Any], name: str) -> None:
    """Print a summary of the configuration"""
    print(f"\n{name} Configuration Summary:")
    print(f"  - Symbols: {len(config['base_config']['symbols'])}")
    print(f"  - Dates: {len(config['base_config']['dates'])} days")
    print(f"  - Daily Top-K: {config['base_config']['sip']['config']['top_k']}")
    print(f"  - Score Floor: {config['base_config']['sip']['config']['score_floor']}")
    print(f"  - Mode: {config['base_config']['sip']['config']['mode']}")
    print(f"  - Variants: {len(config['variants'])}")


def main() -> None:
    """Run daily HMM_SIP example"""
    print("Daily HMM_SIP Example with VWAP Strategy")
    print("=" * 50)

    # Save configurations
    daily_path, daily_comp_path, legacy_path = save_configs()

    print("Configurations created:")
    print(f"  - Daily HMM example: {daily_path}")
    print(f"  - Daily comparison: {daily_comp_path}")
    print(f"  - Legacy comparison: {legacy_path}")

    # Load and display summaries
    with open(daily_path) as f:
        daily_config = yaml.safe_load(f)

    with open(daily_comp_path) as f:
        daily_comp_config = yaml.safe_load(f)

    with open(legacy_path) as f:
        legacy_config = yaml.safe_load(f)

    print_config_summary(daily_config, "Daily HMM VWAP")
    print_config_summary(daily_comp_config, "Daily HMM Comparison")
    print_config_summary(legacy_config, "Legacy HMM Comparison")

    # Print usage instructions
    print("\nUsage Instructions:")
    print("=" * 20)
    print("\n1. Run daily HMM experiment:")
    print(f"   qx-cli exp entry-ab {daily_path}")

    print("\n2. Run comparison experiments:")
    print(f"   qx-cli exp entry-ab {daily_comp_path}")
    print(f"   qx-cli exp entry-ab {legacy_path}")

    print("\n3. Compare results:")
    print(
        "   qx-cli exp compare experiments/daily_hmm_comparison/ experiments/legacy_hmm_comparison/"
    )

    print("\n4. Custom configuration parameters:")
    print("   - Adjust 'score_floor' to change minimum HMM score threshold")
    print("   - Adjust 'top_k' to change maximum symbols per day")
    print("   - Set 'mode: legacy' to use original HMM_SIP behavior")

    print("\nExample configuration tuning:")
    print("=" * 30)

    # Show example parameter variations
    tuning_examples = [
        {"name": "Conservative", "score_floor": 0.02, "top_k": 10},
        {"name": "Balanced", "score_floor": 0.01, "top_k": 20},
        {"name": "Aggressive", "score_floor": 0.005, "top_k": 40},
    ]

    for example in tuning_examples:
        print(f"\n{example['name']} Settings:")
        print(f"  score_floor: {example['score_floor']}")
        print(f"  top_k: {example['top_k']}")
        print(f"  Expected daily universe size: ~{example['top_k']} symbols")

    print("\nTroubleshooting Tips:")
    print("=" * 20)
    print("- Zero trades? Try reducing score_floor or increasing top_k")
    print("- Too many symbols? Increase score_floor or decrease top_k")
    print("- Performance issues? Reduce top_k to limit universe size")
    print("- Always compare with legacy mode using the compare command")

    print(f"\nExample completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
