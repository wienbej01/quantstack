"""CLI entry point for L2 collector."""

import argparse
import logging
import sys

from qx_l2 import L2Collector, load_config


def setup_logging(level: str = "INFO"):
    """Setup logging configuration."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("l2_collector.log"),
        ],
    )


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="L2 Order Book Data Collector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run in daemon mode (waits for collection windows)
  l2-collect --daemon
  
  # Run single collection cycle now
  l2-collect --once
  
  # Override symbols
  l2-collect --once --symbols HAL PFE LUV
  
  # Use custom config
  l2-collect --config my_config.yaml --daemon
        """,
    )

    parser.add_argument(
        "--config", default="configs/default.yaml", help="Path to configuration file"
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as daemon, collecting during scheduled windows",
    )
    parser.add_argument(
        "--once", action="store_true", help="Run single collection cycle"
    )
    parser.add_argument("--symbols", nargs="+", help="Override symbols to collect")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.log_level)
    logger = logging.getLogger(__name__)

    # Load config
    try:
        config = load_config(args.config)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return 1

    # Override symbols if provided
    if args.symbols:
        config["symbols"]["mode"] = "static"
        config["symbols"]["core"] = args.symbols
        logger.info(f"Overriding symbols: {args.symbols}")

    # Create collector
    try:
        collector = L2Collector(config)
    except Exception as e:
        logger.error(f"Failed to create collector: {e}")
        return 1

    # Run based on mode
    try:
        if args.daemon:
            logger.info("Starting daemon mode...")
            collector.run_daemon()
        elif args.once:
            logger.info("Running single collection cycle...")
            collector.run_once()
        else:
            # Interactive mode
            collector.run_interactive()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Collection failed: {e}", exc_info=True)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
