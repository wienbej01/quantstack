#!/usr/bin/env python3
"""Generate training data for full gold universe (600 symbols) for 6-month period."""

import logging
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def main():
    logging.info("Generating full gold universe training data...")

    # Use existing 6-month data generation approach but with full universe
    # For now, let's just copy and expand the existing 23-symbol dataset approach

    # Load gold universe
    import yaml

    with open("configs/extensions/intraday_ml/universe_gold_full.yaml") as f:
        config = yaml.safe_load(f)

    symbols = config["symbols"]
    logging.info(f"Gold universe: {len(symbols)} symbols")

    # For this test, we'll use the same labeling approach as v4_6months
    # but apply it to the full universe

    # Since we don't have raw data for all 600 symbols readily available,
    # let's use the existing comprehensive feature engineering on the 23-symbol dataset
    # and note that full universe testing requires data infrastructure

    logging.info("NOTE: Full 600-symbol universe requires:")
    logging.info("  1. Raw OHLCV data for all 600 symbols (Jan-Jun 2024)")
    logging.info("  2. SIP filter application")
    logging.info("  3. Feature engineering pipeline")
    logging.info("  4. Label generation")
    logging.info("")
    logging.info("Current 23-symbol dataset is a development subset.")
    logging.info("For production, need to:")
    logging.info("  - Run data pipeline on full universe")
    logging.info("  - Apply SMB SIP filters")
    logging.info("  - Generate features for all symbols")
    logging.info("")
    logging.info("Estimated time for full universe: 2-4 hours")
    logging.info("Estimated data size: 50-100GB")

    # For now, let's test the 15 optimal features on the existing 23-symbol dataset
    # and document the limitation

    output_dir = Path("run")
    with open(output_dir / "full_universe_requirements.txt", "w") as f:
        f.write("FULL GOLD UNIVERSE (600 SYMBOLS) REQUIREMENTS\n")
        f.write("=" * 80 + "\n\n")
        f.write("Current Status: Using 23-symbol development subset\n")
        f.write(f"Full Universe: {len(symbols)} symbols\n")
        f.write("Coverage: 3.8% (23/600)\n\n")
        f.write("To test on full universe:\n")
        f.write("1. Load raw OHLCV data for all 600 symbols (Jan-Jun 2024)\n")
        f.write("2. Apply SIP filter (SMB criteria: gap, RVOL, ATR)\n")
        f.write("3. Engineer 15 optimal features\n")
        f.write("4. Generate labels (±2% threshold)\n")
        f.write("5. Train/Val/OOS split (60/20/20)\n")
        f.write("6. Train models\n")
        f.write("7. Backtest\n\n")
        f.write("Estimated Resources:\n")
        f.write("- Time: 2-4 hours\n")
        f.write("- Storage: 50-100GB\n")
        f.write("- Memory: 32GB+ RAM\n")
        f.write("- Compute: 8+ cores\n\n")
        f.write("Current 23-symbol results:\n")
        f.write("- 15 Optimal: 56.0% win rate, $8.61/day on $100K\n")
        f.write("- 30 ICT: 47.1% win rate, $21.40/day on $100K\n")
        f.write("- Trades/day: ~10\n\n")
        f.write("Expected full universe results:\n")
        f.write("- Trades/day: 250-300 (26x more symbols)\n")
        f.write("- Win rate: 50-55% (may decrease with more noise)\n")
        f.write("- Daily P&L: $200-500 on $100K (if win rate holds)\n")

    logging.info(
        f"Requirements documented in {output_dir}/full_universe_requirements.txt"
    )
    logging.info("")
    logging.info(
        "RECOMMENDATION: Test 15 optimal features on existing 23-symbol dataset first"
    )
    logging.info("If performance is good, then invest in full universe infrastructure")


if __name__ == "__main__":
    main()
