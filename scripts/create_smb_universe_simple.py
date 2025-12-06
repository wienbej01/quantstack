#!/usr/bin/env python3
"""Create SMB-style universe by selecting top movers from full gold universe."""

import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def get_all_symbols(
    gold_path: str = "/home/jacobw/gcs-mount/gold/stocks/1m",
) -> list[str]:
    """Get all symbols from gold data."""
    gold_dir = Path(gold_path)
    symbols = [
        d.name for d in gold_dir.iterdir() if d.is_dir() and not d.name.startswith(".")
    ]
    return sorted(symbols)


def main():
    """
    Create SMB universe by using ALL symbols from gold data.
    This replaces the 97-symbol static list with the full 1,108-symbol universe.
    """

    gold_path = "/home/jacobw/gcs-mount/gold/stocks/1m"
    output_file = Path("/home/jacobw/quantstack/run/smb_universe.txt")

    LOGGER.info("=" * 80)
    LOGGER.info("Creating SMB Universe (Full Gold Universe)")
    LOGGER.info("=" * 80)

    # Get all symbols
    symbols = get_all_symbols(gold_path)

    LOGGER.info(f"Found {len(symbols)} symbols in gold data")
    LOGGER.info(f"Sample: {symbols[:10]}")

    # Save to file
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, "w") as f:
        for symbol in symbols:
            f.write(f"{symbol}\n")

    LOGGER.info(f"Saved {len(symbols)} symbols to: {output_file}")
    LOGGER.info("=" * 80)
    LOGGER.info("Next steps:")
    LOGGER.info("1. Use this universe for training (replaces 97-symbol list)")
    LOGGER.info("2. Models will learn from ALL available stocks")
    LOGGER.info("3. Daily selection happens via ML predictions, not pre-filtering")
    LOGGER.info("=" * 80)


if __name__ == "__main__":
    main()
