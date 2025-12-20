#!/usr/bin/env python3
"""Create complete R2000 + S&P 500 universe and prepare for download without price filters."""

import logging
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


def load_sp500_tickers():
    """Load S&P 500 tickers from the retrieved file."""
    sp500_file = Path(
        "/home/jacobw/quantstack/universe_data/sp500_tickers_retrieved.csv"
    )

    if sp500_file.exists():
        df = pd.read_csv(sp500_file)
        tickers = set(df["ticker"].astype(str).str.strip().str.upper())
        logger.info(f"Loaded {len(tickers)} S&P 500 tickers from file")
        return tickers
    else:
        logger.error("S&P 500 file not found. Run get_complete_sp500.py first.")
        return set()


def load_russell2000_tickers():
    """Load Russell 2000 tickers from Excel file."""
    r2k_file = Path("/home/jacobw/data_download/russell_2000.xlsx")

    if not r2k_file.exists():
        logger.error("Russell 2000 file not found")
        return set()

    try:
        df = pd.read_excel(r2k_file)

        if "Ticker" in df.columns:
            tickers = df["Ticker"].dropna().astype(str).str.strip().str.upper()
            # Clean tickers - remove any problematic ones
            clean_tickers = set()
            for ticker in tickers:
                # Only keep valid ticker formats
                if (
                    ticker.replace("-", "").replace(".", "").isalpha()
                    and len(ticker) <= 5
                ):
                    clean_tickers.add(ticker)

            logger.info(f"Loaded {len(clean_tickers)} Russell 2000 tickers")
            return clean_tickers
        else:
            logger.error("No 'Ticker' column found in Russell 2000 file")
            return set()

    except Exception as e:
        logger.error(f"Error loading Russell 2000 file: {e}")
        return set()


def analyze_gold_coverage(universe_tickers):
    """Analyze current gold data coverage."""
    logger.info("Analyzing gold data coverage...")

    gold_root = Path("/home/jacobw/gcs-mount/gold/stocks/1m")

    if not gold_root.exists():
        logger.error(f"Gold root not found: {gold_root}")
        return {}

    coverage = {
        "has_data": set(),
        "missing_completely": set(),
        "has_historical": set(),  # Has 2021-2024 data
        "missing_historical": set(),
        "only_2025": set(),
        "good_coverage": set(),
    }

    # Get existing tickers
    existing_tickers = set()
    for ticker_dir in gold_root.iterdir():
        if ticker_dir.is_dir() and ticker_dir.name.isupper():
            existing_tickers.add(ticker_dir.name)

    coverage["has_data"] = universe_tickers & existing_tickers
    coverage["missing_completely"] = universe_tickers - existing_tickers

    # Analyze year coverage for existing tickers
    for ticker in coverage["has_data"]:
        ticker_path = gold_root / ticker
        year_dirs = [
            d for d in ticker_path.iterdir() if d.is_dir() and d.name.isdigit()
        ]
        years = sorted([int(d.name) for d in year_dirs])

        if years:
            # Check for historical data (2021-2024)
            historical_years = [y for y in years if 2021 <= y <= 2024]

            if historical_years:
                coverage["has_historical"].add(ticker)
                coverage["good_coverage"].add(ticker)
            else:
                coverage["missing_historical"].add(ticker)

            # Check if only 2025 data
            if years == [2025]:
                coverage["only_2025"].add(ticker)

    # Log analysis
    logger.info(f"Universe size: {len(universe_tickers):,}")
    logger.info(f"Has some data: {len(coverage['has_data']):,}")
    logger.info(f"Missing completely: {len(coverage['missing_completely']):,}")
    logger.info(f"Has historical (2021-2024): {len(coverage['has_historical']):,}")
    logger.info(f"Missing historical: {len(coverage['missing_historical']):,}")
    logger.info(f"Only 2025 data: {len(coverage['only_2025']):,}")

    return coverage


def create_action_plan(coverage):
    """Create action plan for data management."""
    logger.info("Creating action plan...")

    # Actions needed
    actions = {
        "download_missing": coverage["missing_completely"],
        "download_historical": coverage["missing_historical"],
        "remove_2025_only": coverage["only_2025"],
        "keep_good": coverage["good_coverage"],
    }

    # Total work needed
    total_download = actions["download_missing"] | actions["download_historical"]

    logger.info(f"Download missing tickers: {len(actions['download_missing']):,}")
    logger.info(
        f"Download historical for existing: {len(actions['download_historical']):,}"
    )
    logger.info(f"Remove 2025-only directories: {len(actions['remove_2025_only']):,}")
    logger.info(f"Keep as-is (good coverage): {len(actions['keep_good']):,}")
    logger.info(f"Total download needed: {len(total_download):,}")

    return actions


def save_universe_and_plan(sp500_tickers, r2k_tickers, coverage, actions):
    """Save universe data and action plan."""
    logger.info("Saving universe and action plan...")

    output_dir = Path("/home/jacobw/quantstack/universe_data")
    output_dir.mkdir(exist_ok=True)

    # Universe composition
    full_universe = sp500_tickers | r2k_tickers
    overlap = sp500_tickers & r2k_tickers
    r2k_only = r2k_tickers - sp500_tickers
    sp500_only = sp500_tickers - r2k_tickers

    # Save universe files
    pd.DataFrame({"ticker": sorted(sp500_tickers)}).to_csv(
        output_dir / "sp500_complete.csv", index=False
    )

    pd.DataFrame({"ticker": sorted(r2k_tickers)}).to_csv(
        output_dir / "russell2000_complete.csv", index=False
    )

    pd.DataFrame({"ticker": sorted(full_universe)}).to_csv(
        output_dir / "complete_universe.csv", index=False
    )

    pd.DataFrame({"ticker": sorted(overlap)}).to_csv(
        output_dir / "sp500_r2k_overlap.csv", index=False
    )

    pd.DataFrame({"ticker": sorted(r2k_only)}).to_csv(
        output_dir / "russell2000_only.csv", index=False
    )

    pd.DataFrame({"ticker": sorted(sp500_only)}).to_csv(
        output_dir / "sp500_only.csv", index=False
    )

    # Save action plan files
    total_download = actions["download_missing"] | actions["download_historical"]

    pd.DataFrame({"ticker": sorted(actions["download_missing"])}).to_csv(
        output_dir / "action_download_missing.csv", index=False
    )

    pd.DataFrame({"ticker": sorted(actions["download_historical"])}).to_csv(
        output_dir / "action_download_historical.csv", index=False
    )

    pd.DataFrame({"ticker": sorted(total_download)}).to_csv(
        output_dir / "action_download_all.csv", index=False
    )

    pd.DataFrame({"ticker": sorted(actions["remove_2025_only"])}).to_csv(
        output_dir / "action_remove_2025_only.csv", index=False
    )

    pd.DataFrame({"ticker": sorted(actions["keep_good"])}).to_csv(
        output_dir / "action_keep_good.csv", index=False
    )

    # Create summary
    summary = {
        "universe_total": len(full_universe),
        "sp500_count": len(sp500_tickers),
        "russell2000_count": len(r2k_tickers),
        "overlap_count": len(overlap),
        "r2k_only_count": len(r2k_only),
        "sp500_only_count": len(sp500_only),
        "has_data_count": len(coverage["has_data"]),
        "missing_completely_count": len(coverage["missing_completely"]),
        "good_coverage_count": len(coverage["good_coverage"]),
        "download_needed_count": len(total_download),
        "remove_2025_only_count": len(actions["remove_2025_only"]),
        "coverage_percentage": round(
            len(coverage["good_coverage"]) / len(full_universe) * 100, 1
        ),
        "created_at": datetime.now().isoformat(),
    }

    pd.DataFrame([summary]).to_csv(output_dir / "universe_summary.csv", index=False)

    # Create updated config
    create_updated_config(output_dir, summary)

    logger.info(f"All files saved to: {output_dir}")
    return summary


def create_updated_config(output_dir, summary):
    """Create updated configuration for downloads."""

    config_content = f"""# Complete Universe Configuration (R2K + S&P 500)
# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
# Universe size: {summary['universe_total']:,} tickers
# Coverage: {summary['coverage_percentage']}%

# REMOVE ALL PRICE FILTERS - Download complete universe
lookback_years: 4                    # From 2021-01-01
prefilter_frac_min: 0.0             # No price filtering
month_chunk: "1M"
concurrency: 8

http:
  timeout_sec: 30
  max_retries: 6
  backoff_base_sec: 1.5

paths:
  universe_dir: "{output_dir.absolute()}"
  prefilter_dir: "artefacts/prefilter"
  checkpoints_dir: "artefacts/checkpoints"
  bronze_root: "/home/jacobw/gcs-mount/bronze/stocks/1m"
  silver_root: "/home/jacobw/gcs-mount/silver/stocks/1m"
  gold_root: "/home/jacobw/gcs-mount/gold/stocks/1m"

calendar: "XNYS"
price_band: [0.01, 100000.0]        # Effectively no price limits

polygon:
  api_key_env: "POLYGON_API_KEY"

# Universe settings - FULL COVERAGE
universe:
  mode: "complete"                   # Complete R2K + S&P 500
  include_sp500: true
  include_russell2000: true
  remove_price_filters: true
  start_date: "2021-01-01"
  end_date: "2025-12-31"
  
# Download priorities
download:
  priority_1: "missing_completely"   # {summary['missing_completely_count']:,} tickers
  priority_2: "missing_historical"   # Additional historical data
  total_needed: {summary['download_needed_count']:,}
"""

    config_path = output_dir / "complete_universe_config.yaml"
    with open(config_path, "w") as f:
        f.write(config_content)

    logger.info(f"Updated config saved to: {config_path}")


def main():
    """Main execution."""
    logger.info("Creating complete R2K + S&P 500 universe (no price filters)...")

    # Load ticker lists
    sp500_tickers = load_sp500_tickers()
    r2k_tickers = load_russell2000_tickers()

    if not sp500_tickers or not r2k_tickers:
        logger.error("Failed to load ticker lists")
        return

    # Analyze universe
    full_universe = sp500_tickers | r2k_tickers
    overlap = sp500_tickers & r2k_tickers

    logger.info(f"\n=== UNIVERSE COMPOSITION ===")
    logger.info(f"S&P 500: {len(sp500_tickers):,} tickers")
    logger.info(f"Russell 2000: {len(r2k_tickers):,} tickers")
    logger.info(f"Overlap: {len(overlap):,} tickers")
    logger.info(f"Total unique: {len(full_universe):,} tickers")
    logger.info(f"R2K only: {len(r2k_tickers - sp500_tickers):,}")
    logger.info(f"S&P 500 only: {len(sp500_tickers - r2k_tickers):,}")

    # Analyze current coverage
    coverage = analyze_gold_coverage(full_universe)

    # Create action plan
    actions = create_action_plan(coverage)

    # Save everything
    summary = save_universe_and_plan(sp500_tickers, r2k_tickers, coverage, actions)

    # Final report
    logger.info(f"\n=== FINAL SUMMARY ===")
    logger.info(f"Complete universe: {summary['universe_total']:,} tickers")
    logger.info(f"Current coverage: {summary['coverage_percentage']}%")
    logger.info(f"Need to download: {summary['download_needed_count']:,} tickers")
    logger.info(
        f"Can remove (2025-only): {summary['remove_2025_only_count']:,} directories"
    )

    logger.info(f"\n=== NEXT STEPS ===")
    logger.info(f"1. Review files in: /home/jacobw/quantstack/universe_data/")
    logger.info(
        f"2. Download {summary['download_needed_count']:,} missing/incomplete tickers"
    )
    logger.info(
        f"3. Remove {summary['remove_2025_only_count']:,} 2025-only directories"
    )
    logger.info(f"4. Update data_download config to use complete_universe_config.yaml")


if __name__ == "__main__":
    main()
