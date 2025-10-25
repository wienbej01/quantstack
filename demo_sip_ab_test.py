#!/usr/bin/env python3
"""
Demonstration script for SIP A/B testing with HMM SIP vs Legacy SIP

This script shows how to run an A/B test comparing the original SIP screener
with the new HMM SIP selector using the created overlay configurations.
"""

import subprocess
import sys
from pathlib import Path


def show_usage():
    """Show usage instructions."""
    print("SIP A/B Testing Demo")
    print("=" * 40)
    print()
    print("This demo shows how to run A/B tests comparing:")
    print("  • Legacy SIP (original relative volume screener)")
    print("  • HMM SIP (new Hidden Markov Model selector)")
    print()
    print("Created overlay files:")
    print("  • experiments/vwap_revert/overlays/sip_legacy.yaml")
    print("  • experiments/vwap_revert/overlays/sip_hmmsip_top40.yaml")
    print()
    print("To run the A/B test:")
    print("  python -m qx_cli exp entry-ab \\")
    print("    --cfg experiments/vwap_revert/strategy.yaml \\")
    print(
        "    --variants 'experiments/vwap_revert/overlays/sip_legacy.yaml,experiments/vwap_revert/overlays/sip_hmmsip_top40.yaml' \\"
    )
    print("    --name sip_ab_demo")
    print()
    print("Expected output:")
    print("  • Different sip_hash values for each variant")
    print("  • Identical bars_norm_hash and features_hash")
    print("  • Log messages showing SIP method and parameters")
    print("  • Artifacts saved to runs/ and experiments/ directories")
    print()
    print("Configuration comparison:")
    show_config_comparison()


def show_config_comparison():
    """Show the configuration differences."""
    print("Legacy SIP Configuration:")
    print("  method: original")
    print("  top_n: 5")
    print("  rvol_col: f__vol__rel_volume_30")
    print("  whitelist: [AAPL, GOOGL]")
    print()
    print("HMM SIP Configuration:")
    print("  method: hmm_sip")
    print("  top_k: 40")
    print("  score_floor: 0.0")
    print("  enable_gold_fallback: true")
    print("  external_premarket_root: ~/hybrid-local/signals/sip/universe/pre")
    print("  p_hat_threshold: null")
    print()


def verify_overlay_files():
    """Verify that overlay files exist."""
    required_files = [
        "experiments/vwap_revert/overlays/sip_legacy.yaml",
        "experiments/vwap_revert/overlays/sip_hmmsip_top40.yaml",
    ]

    missing_files = []
    for file_path in required_files:
        if not Path(file_path).exists():
            missing_files.append(file_path)

    if missing_files:
        print("❌ Missing overlay files:")
        for file_path in missing_files:
            print(f"   • {file_path}")
        return False
    else:
        print("✅ All overlay files exist")
        return True


def run_demo_test():
    """Run a simple demo test."""
    print("Running demo functionality test...")
    print()

    # Test basic config loading
    try:
        import yaml

        # Test legacy overlay
        with open("experiments/vwap_revert/overlays/sip_legacy.yaml") as f:
            legacy_config = yaml.safe_load(f)

        # Test HMM overlay
        with open("experiments/vwap_revert/overlays/sip_hmmsip_top40.yaml") as f:
            hmm_config = yaml.safe_load(f)

        # Verify configurations
        assert legacy_config.get("sip", {}).get("method") == "original"
        assert hmm_config.get("sip", {}).get("method") == "hmm"
        assert legacy_config.get("sip", {}).get("top_n") == 5
        assert hmm_config.get("sip", {}).get("top_k") == 40

        print("✅ Configuration loading test passed")
        print(
            f"  Legacy SIP: method={legacy_config['sip']['method']}, top_n={legacy_config['sip']['top_n']}"
        )
        print(
            f"  HMM SIP: method={hmm_config['sip']['method']}, top_k={hmm_config['sip']['top_k']}"
        )

    except Exception as e:
        import traceback

        print(f"❌ Configuration loading test failed: {e}")
        print(f"Traceback: {traceback.format_exc()}")
        return False

    return True


def main():
    """Main demo function."""
    show_usage()

    # Verify overlay files exist
    if not verify_overlay_files():
        print("\n❌ Demo cannot proceed - missing overlay files")
        return 1

    print()

    # Run demo test
    if not run_demo_test():
        print("\n❌ Demo test failed")
        return 1

    print("\n✅ Demo completed successfully!")
    print()
    print("Next steps:")
    print("1. Run the actual A/B test using the command shown above")
    print("2. Check the inputs_checksum.json files for different sip_hash values")
    print("3. Compare the results in the experiments/ directory")
    print("4. Analyze any differences in trading performance")

    return 0


if __name__ == "__main__":
    sys.exit(main())
