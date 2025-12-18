#!/usr/bin/env python3
"""Create R2000 + S&P 500 universe and prepare for download without price filters."""

import os
import pandas as pd
from pathlib import Path
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def get_sp500_static_list():
    """Static S&P 500 list (major companies)."""
    # Major S&P 500 companies - this covers most of the large caps
    sp500_tickers = {
        'AAPL', 'MSFT', 'GOOGL', 'GOOG', 'AMZN', 'NVDA', 'TSLA', 'META', 'BRK-B', 'UNH',
        'JNJ', 'XOM', 'JPM', 'V', 'PG', 'MA', 'HD', 'CVX', 'LLY', 'ABBV',
        'PFE', 'KO', 'AVGO', 'PEP', 'TMO', 'COST', 'WMT', 'MRK', 'BAC', 'NFLX',
        'DIS', 'ABT', 'ACN', 'CRM', 'VZ', 'ADBE', 'DHR', 'NKE', 'TXN', 'RTX',
        'NEE', 'QCOM', 'PM', 'T', 'LOW', 'SPGI', 'UNP', 'HON', 'INTU', 'GS',
        'COP', 'IBM', 'CAT', 'AMD', 'AMGN', 'BKNG', 'ELV', 'DE', 'AXP', 'BLK',
        'SYK', 'MDLZ', 'GILD', 'ADP', 'TJX', 'VRTX', 'LRCX', 'ADI', 'C', 'SCHW',
        'MMC', 'TMUS', 'CVS', 'MO', 'ZTS', 'FI', 'SO', 'CB', 'DUK', 'BSX',
        'PYPL', 'NOW', 'AON', 'SLB', 'ITW', 'WM', 'HCA', 'ICE', 'PNC', 'FCX',
        'EQIX', 'CL', 'USB', 'NSC', 'APD', 'EMR', 'GD', 'KLAC', 'CSX', 'MCO',
        'EOG', 'WFC', 'PLD', 'CME', 'DG', 'TGT', 'F', 'GM', 'MU', 'ANET',
        'ORLY', 'ECL', 'SHW', 'AIG', 'PCAR', 'TFC', 'NXPI', 'MCHP', 'ROP', 'ROST',
        'PAYX', 'CARR', 'KMB', 'OTIS', 'DXCM', 'CTAS', 'MNST', 'IDXX', 'FAST', 'EW',
        'VRSK', 'CPRT', 'CMG', 'ODFL', 'KR', 'BDX', 'GLW', 'MKTX', 'CTSH', 'ANSS',
        'BIIB', 'EA', 'IEX', 'CHTR', 'SBUX', 'AZO', 'REGN', 'FISV', 'WBA', 'ALL',
        'GIS', 'HLT', 'ILMN', 'CSGP', 'EXC', 'KHC', 'ALGN', 'CDNS', 'SNPS', 'MSCI',
        'WDAY', 'ADSK', 'AEE', 'XEL', 'FTNT', 'MPWR', 'VICI', 'TEAM', 'CRWD', 'PANW'
    }
    
    logger.info(f"Using static S&P 500 list: {len(sp500_tickers)} tickers")
    return sp500_tickers

def get_russell2000_tickers():
    """Get Russell 2000 ticker list from local file."""
    logger.info("Loading Russell 2000 tickers from local file...")
    
    r2k_file = Path("/home/jacobw/data_download/russell_2000.xlsx")
    
    if not r2k_file.exists():
        logger.error("Russell 2000 file not found")
        return set()
    
    try:
        df = pd.read_excel(r2k_file)
        
        if 'Ticker' in df.columns:
            tickers = df['Ticker'].dropna().astype(str).str.strip().str.upper()
            # Clean tickers - remove any with special characters that might cause issues
            clean_tickers = set()
            for ticker in tickers:
                if ticker.isalpha() or '-' in ticker:  # Allow letters and hyphens
                    clean_tickers.add(ticker)
            
            logger.info(f"Found {len(clean_tickers)} valid Russell 2000 tickers")
            return clean_tickers
        else:
            logger.error("No 'Ticker' column found in Russell 2000 file")
            return set()
            
    except Exception as e:
        logger.error(f"Error loading Russell 2000 file: {e}")
        return set()

def analyze_current_gold_coverage(universe_tickers):
    """Analyze current gold data coverage for the universe."""
    logger.info("Analyzing current gold data coverage...")
    
    gold_root = Path("/home/jacobw/gcs-mount/gold/stocks/1m")
    
    if not gold_root.exists():
        logger.error(f"Gold root not found: {gold_root}")
        return {}
    
    coverage = {
        'has_data': set(),
        'missing_completely': set(),
        'has_2021_data': set(),
        'missing_2021_data': set(),
        'only_2025_data': set(),
        'good_coverage': set()  # Has 2021+ data
    }
    
    existing_tickers = set()
    for ticker_dir in gold_root.iterdir():
        if ticker_dir.is_dir():
            existing_tickers.add(ticker_dir.name)
    
    coverage['has_data'] = universe_tickers & existing_tickers
    coverage['missing_completely'] = universe_tickers - existing_tickers
    
    # Check for 2021+ data coverage
    for ticker in coverage['has_data']:
        ticker_path = gold_root / ticker
        year_dirs = [d for d in ticker_path.iterdir() if d.is_dir() and d.name.isdigit()]
        years = sorted([int(d.name) for d in year_dirs])
        
        if years:
            if min(years) <= 2021:
                coverage['has_2021_data'].add(ticker)
                coverage['good_coverage'].add(ticker)
            else:
                coverage['missing_2021_data'].add(ticker)
                
            if years == [2025]:
                coverage['only_2025_data'].add(ticker)
    
    # Log summary
    logger.info(f"Universe size: {len(universe_tickers)}")
    logger.info(f"Has some data: {len(coverage['has_data'])}")
    logger.info(f"Missing completely: {len(coverage['missing_completely'])}")
    logger.info(f"Has 2021+ data: {len(coverage['has_2021_data'])}")
    logger.info(f"Missing 2021+ data: {len(coverage['missing_2021_data'])}")
    logger.info(f"Only 2025 data: {len(coverage['only_2025_data'])}")
    logger.info(f"Good coverage (2021+): {len(coverage['good_coverage'])}")
    
    return coverage

def create_download_strategy(coverage):
    """Create download strategy for missing data."""
    logger.info("Creating download strategy...")
    
    # What needs to be downloaded
    needs_download = coverage['missing_completely'] | coverage['missing_2021_data'] | coverage['only_2025_data']
    
    # What can be cleaned up (2025-only data)
    can_remove_2025_only = coverage['only_2025_data']
    
    strategy = {
        'download_needed': needs_download,
        'remove_2025_only': can_remove_2025_only,
        'keep_as_is': coverage['good_coverage']
    }
    
    logger.info(f"Need to download: {len(needs_download)} tickers")
    logger.info(f"Can remove 2025-only: {len(can_remove_2025_only)} tickers")
    logger.info(f"Keep as-is (good): {len(coverage['good_coverage'])} tickers")
    
    return strategy

def save_universe_and_strategy(sp500_tickers, r2k_tickers, coverage, strategy):
    """Save universe and download strategy to files."""
    logger.info("Saving universe and strategy files...")
    
    output_dir = Path("/home/jacobw/quantstack/universe_data")
    output_dir.mkdir(exist_ok=True)
    
    # Combined universe
    full_universe = sp500_tickers | r2k_tickers
    overlap = sp500_tickers & r2k_tickers
    
    # Save ticker lists
    pd.DataFrame({'ticker': sorted(sp500_tickers)}).to_csv(
        output_dir / 'sp500_tickers.csv', index=False)
    
    pd.DataFrame({'ticker': sorted(r2k_tickers)}).to_csv(
        output_dir / 'russell2000_tickers.csv', index=False)
    
    pd.DataFrame({'ticker': sorted(full_universe)}).to_csv(
        output_dir / 'full_universe.csv', index=False)
    
    pd.DataFrame({'ticker': sorted(overlap)}).to_csv(
        output_dir / 'sp500_r2k_overlap.csv', index=False)
    
    # Save strategy files
    pd.DataFrame({'ticker': sorted(strategy['download_needed'])}).to_csv(
        output_dir / 'tickers_to_download.csv', index=False)
    
    pd.DataFrame({'ticker': sorted(strategy['remove_2025_only'])}).to_csv(
        output_dir / 'tickers_remove_2025_only.csv', index=False)
    
    pd.DataFrame({'ticker': sorted(strategy['keep_as_is'])}).to_csv(
        output_dir / 'tickers_keep_as_is.csv', index=False)
    
    # Summary report
    summary = {
        'total_universe': len(full_universe),
        'sp500_count': len(sp500_tickers),
        'russell2000_count': len(r2k_tickers),
        'overlap_count': len(overlap),
        'has_data': len(coverage['has_data']),
        'missing_completely': len(coverage['missing_completely']),
        'good_coverage_2021plus': len(coverage['good_coverage']),
        'needs_download': len(strategy['download_needed']),
        'can_remove_2025_only': len(strategy['remove_2025_only']),
        'coverage_percentage': round(len(coverage['good_coverage']) / len(full_universe) * 100, 1)
    }
    
    pd.DataFrame([summary]).to_csv(output_dir / 'universe_summary.csv', index=False)
    
    # Create download configuration
    create_download_config(output_dir)
    
    logger.info(f"Files saved to: {output_dir}")
    return summary

def create_download_config(output_dir):
    """Create updated download configuration."""
    config_content = f"""# Updated Universe Configuration - No Price Filters
# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

# Remove price band restrictions - download full R2K + S&P 500
lookback_years: 4                    # Download from 2021-01
prefilter_frac_min: 0.0             # No price filter requirement
month_chunk: "1M"
concurrency: 8

http:
  timeout_sec: 30
  max_retries: 6
  backoff_base_sec: 1.5

paths:
  universe_dir: "{output_dir}"
  prefilter_dir: "artefacts/prefilter"
  checkpoints_dir: "artefacts/checkpoints"
  bronze_root: "/home/jacobw/gcs-mount/bronze/stocks/1m"
  silver_root: "/home/jacobw/gcs-mount/silver/stocks/1m"
  gold_root: "/home/jacobw/gcs-mount/gold/stocks/1m"

calendar: "XNYS"
price_band: [0.01, 10000.0]         # Effectively no price filter

polygon:
  api_key_env: "POLYGON_API_KEY"

# Universe settings
universe:
  include_sp500: true
  include_russell2000: true
  start_date: "2021-01-01"
  end_date: "2025-12-31"
  remove_price_filters: true
"""
    
    config_path = output_dir / "updated_download_config.yaml"
    with open(config_path, 'w') as f:
        f.write(config_content)
    
    logger.info(f"Download config saved to: {config_path}")

def main():
    """Main function."""
    logger.info("Creating R2K + S&P 500 universe without price filters...")
    
    # Get ticker lists
    sp500_tickers = get_sp500_static_list()
    r2k_tickers = get_russell2000_tickers()
    
    if not r2k_tickers:
        logger.error("Failed to get Russell 2000 tickers")
        return
    
    # Combine and analyze
    full_universe = sp500_tickers | r2k_tickers
    overlap = sp500_tickers & r2k_tickers
    
    logger.info(f"\n=== UNIVERSE COMPOSITION ===")
    logger.info(f"S&P 500: {len(sp500_tickers)} tickers")
    logger.info(f"Russell 2000: {len(r2k_tickers)} tickers")
    logger.info(f"Overlap: {len(overlap)} tickers")
    logger.info(f"Combined universe: {len(full_universe)} tickers")
    
    # Analyze current coverage
    coverage = analyze_current_gold_coverage(full_universe)
    
    # Create download strategy
    strategy = create_download_strategy(coverage)
    
    # Save everything
    summary = save_universe_and_strategy(sp500_tickers, r2k_tickers, coverage, strategy)
    
    # Print final summary
    logger.info(f"\n=== FINAL SUMMARY ===")
    for key, value in summary.items():
        logger.info(f"{key}: {value}")
    
    logger.info(f"\n=== ACTION ITEMS ===")
    logger.info(f"1. Download {summary['needs_download']} missing tickers")
    logger.info(f"2. Remove {summary['can_remove_2025_only']} 2025-only ticker directories")
    logger.info(f"3. Current coverage: {summary['coverage_percentage']}%")
    logger.info(f"4. Files saved to: /home/jacobw/quantstack/universe_data/")

if __name__ == "__main__":
    main()
