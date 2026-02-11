#!/usr/bin/env python3
"""Validate L2 integration without full installation."""

import sys
from pathlib import Path


def validate_integration():
    """Validate the L2 integration files."""
    print("🔍 Validating L2 Integration...")

    # Check required files exist
    required_files = [
        "qx-data/qx_data/live/__init__.py",
        "qx-data/qx_data/live/l2_collector.py",
        "qx-screener/qx_screener/sip/live_sip.py",
        "experiments/live_regime_aware/config.yaml",
        "scripts/live_regime_trading.py",
        "scripts/test_l2_integration.py",
        "requirements-live.txt",
        "docs/LIVE_TRADING.md",
    ]

    missing_files = []
    for file_path in required_files:
        if not Path(file_path).exists():
            missing_files.append(file_path)

    if missing_files:
        print("❌ Missing files:")
        for f in missing_files:
            print(f"   - {f}")
        return False

    print("✅ All required files present")

    # Check transalpha L2 system exists
    transalpha_l2 = Path.home() / "transalpha" / "l2"
    if not transalpha_l2.exists():
        print(f"❌ Transalpha L2 system not found at: {transalpha_l2}")
        return False

    print(f"✅ Transalpha L2 system found at: {transalpha_l2}")

    # Check key L2 files
    l2_files = ["multi_l2_collector.py", "l2_features.py", "time_windows.py"]

    for l2_file in l2_files:
        if not (transalpha_l2 / l2_file).exists():
            print(f"❌ Missing L2 file: {l2_file}")
            return False

    print("✅ All L2 system files present")

    # Test import structure (without actual imports)
    try:
        # Add paths for testing
        sys.path.insert(0, str(transalpha_l2))
        sys.path.insert(0, "qx-data")
        sys.path.insert(0, "qx-screener")

        print("✅ Import paths configured")

    except Exception as e:
        print(f"❌ Import configuration failed: {e}")
        return False

    # Check configuration structure
    config_path = Path("experiments/live_regime_aware/config.yaml")
    try:
        import yaml

        with open(config_path) as f:
            config = yaml.safe_load(f)

        required_sections = ["data", "sip", "strategy"]
        for section in required_sections:
            if section not in config:
                print(f"❌ Missing config section: {section}")
                return False

        if "l2" not in config["data"]:
            print("❌ Missing L2 configuration")
            return False

        print("✅ Configuration structure valid")

    except Exception as e:
        print(f"❌ Configuration validation failed: {e}")
        return False

    print("\n🎉 L2 Integration Validation Complete!")
    print("\n📋 Next Steps:")
    print("1. Ensure IBKR TWS/Gateway running on port 7497")
    print("2. Subscribe to market data (see L2_DATA_ACCESS_SUMMARY.md)")
    print("3. Set POLYGON_API_KEY environment variable")
    print("4. Run: make test-l2 (after installing dependencies)")
    print("5. Run: make live-trade (for live trading)")

    return True


if __name__ == "__main__":
    success = validate_integration()
    sys.exit(0 if success else 1)
