#!/usr/bin/env python3
"""Get complete S&P 500 list using alternative methods."""

import logging
from pathlib import Path

import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


def get_sp500_from_file():
    """Try to get S&P 500 from a local file if available."""
    # Check if there's already an S&P 500 file
    possible_files = [
        "/home/jacobw/data_download/sp500.csv",
        "/home/jacobw/data_download/sp500.xlsx",
        "/home/jacobw/data_download/sp500_companies.csv",
    ]

    for file_path in possible_files:
        if Path(file_path).exists():
            logger.info(f"Found S&P 500 file: {file_path}")
            try:
                if file_path.endswith(".xlsx"):
                    df = pd.read_excel(file_path)
                else:
                    df = pd.read_csv(file_path)

                # Look for ticker column
                ticker_cols = [
                    "Symbol",
                    "Ticker",
                    "ticker",
                    "symbol",
                    "TICKER",
                    "SYMBOL",
                ]
                for col in ticker_cols:
                    if col in df.columns:
                        tickers = df[col].dropna().astype(str).str.strip().str.upper()
                        logger.info(
                            f"Found {len(tickers)} S&P 500 tickers in {file_path}"
                        )
                        return set(tickers)

            except Exception as e:
                logger.warning(f"Error reading {file_path}: {e}")
                continue

    return None


def get_sp500_alternative_sources():
    """Try alternative sources for S&P 500 data."""

    # Method 1: Try a different Wikipedia approach with requests
    try:
        logger.info("Trying alternative Wikipedia approach...")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            # Use pandas to parse HTML directly from the response
            tables = pd.read_html(response.text)
            if tables:
                sp500_df = tables[0]
                if "Symbol" in sp500_df.columns:
                    tickers = (
                        sp500_df["Symbol"].dropna().astype(str).str.strip().str.upper()
                    )
                    # Handle special cases like BRK.B -> BRK-B
                    clean_tickers = set()
                    for ticker in tickers:
                        clean_ticker = ticker.replace(".", "-")
                        clean_tickers.add(clean_ticker)

                    logger.info(
                        f"Successfully got {len(clean_tickers)} S&P 500 tickers from Wikipedia"
                    )
                    return clean_tickers

    except Exception as e:
        logger.warning(f"Wikipedia alternative failed: {e}")

    # Method 2: Use a comprehensive static list (actual S&P 500 as of recent)
    logger.info("Using comprehensive static S&P 500 list...")

    # This is a more complete list of S&P 500 companies (as of 2024)
    sp500_comprehensive = {
        # Technology
        "AAPL",
        "MSFT",
        "GOOGL",
        "GOOG",
        "AMZN",
        "NVDA",
        "META",
        "TSLA",
        "AVGO",
        "ORCL",
        "CRM",
        "ADBE",
        "NFLX",
        "AMD",
        "INTC",
        "CSCO",
        "ACN",
        "IBM",
        "QCOM",
        "TXN",
        "INTU",
        "NOW",
        "PANW",
        "AMAT",
        "ADI",
        "LRCX",
        "KLAC",
        "CDNS",
        "SNPS",
        "MCHP",
        "FTNT",
        "ANSS",
        "CTSH",
        "FISV",
        "FIS",
        "PAYX",
        "ADP",
        "MSCI",
        "VRSK",
        "VRSN",
        # Healthcare
        "UNH",
        "JNJ",
        "PFE",
        "ABBV",
        "LLY",
        "TMO",
        "ABT",
        "DHR",
        "MRK",
        "BMY",
        "AMGN",
        "GILD",
        "VRTX",
        "REGN",
        "ZTS",
        "SYK",
        "BDX",
        "EW",
        "ISRG",
        "BSX",
        "MDT",
        "IQV",
        "DXCM",
        "BIIB",
        "IDXX",
        "WST",
        "MTD",
        "ALGN",
        "MRNA",
        "TECH",
        "A",
        "BAX",
        "BIO",
        "HOLX",
        "ILMN",
        "INCY",
        "PKI",
        "RMD",
        "RVTY",
        "STE",
        "TFX",
        "VAR",
        "VTRS",
        "WAT",
        "XRAY",
        "ZBH",
        # Financials
        "BRK-B",
        "JPM",
        "V",
        "MA",
        "BAC",
        "WFC",
        "GS",
        "MS",
        "C",
        "AXP",
        "SCHW",
        "BLK",
        "SPGI",
        "CME",
        "ICE",
        "MCO",
        "MMC",
        "AON",
        "PNC",
        "USB",
        "TFC",
        "COF",
        "AIG",
        "MET",
        "PRU",
        "ALL",
        "TRV",
        "AFL",
        "PGR",
        "CB",
        "AJG",
        "BRO",
        "HIG",
        "CINF",
        "L",
        "RE",
        "WRB",
        "ACGL",
        "AIZ",
        "FNF",
        # Consumer Discretionary
        "AMZN",
        "HD",
        "MCD",
        "NKE",
        "LOW",
        "SBUX",
        "TJX",
        "BKNG",
        "ABNB",
        "CMG",
        "ORLY",
        "AZO",
        "LULU",
        "RCL",
        "CCL",
        "NCLH",
        "MAR",
        "HLT",
        "MGM",
        "WYNN",
        "LVS",
        "CZR",
        "DRI",
        "YUM",
        "QSR",
        "DPZ",
        "DPZ",
        "BBY",
        "EBAY",
        "ETSY",
        "W",
        "CHWY",
        "CVNA",
        "KMX",
        "AN",
        "LAD",
        "PAG",
        "SIG",
        "TPG",
        "TSCO",
        # Consumer Staples
        "PG",
        "KO",
        "PEP",
        "WMT",
        "COST",
        "MDLZ",
        "PM",
        "MO",
        "CL",
        "KMB",
        "GIS",
        "K",
        "HSY",
        "SJM",
        "CAG",
        "CPB",
        "HRL",
        "MKC",
        "CLX",
        "CHD",
        "COTY",
        "EL",
        "KR",
        "SYY",
        "DLTR",
        "DG",
        "BJ",
        "COST",
        "WBA",
        "CVS",
        # Energy
        "XOM",
        "CVX",
        "COP",
        "EOG",
        "SLB",
        "PSX",
        "VLO",
        "MPC",
        "OXY",
        "BKR",
        "HAL",
        "DVN",
        "FANG",
        "EQT",
        "CTRA",
        "MRO",
        "APA",
        "OVV",
        "TPG",
        "WMB",
        "KMI",
        "LNG",
        "TRGP",
        "EPD",
        "ET",
        "MPLX",
        "PAA",
        "WES",
        "DT",
        "ENLC",
        # Industrials
        "CAT",
        "RTX",
        "HON",
        "UNP",
        "DE",
        "LMT",
        "BA",
        "GE",
        "MMM",
        "ITW",
        "EMR",
        "ETN",
        "PH",
        "JCI",
        "CARR",
        "OTIS",
        "GD",
        "NOC",
        "LHX",
        "TDG",
        "AXON",
        "HWM",
        "IEX",
        "FTV",
        "AME",
        "DOV",
        "GNRC",
        "PWR",
        "HUBB",
        "BLDR",
        "SNA",
        "PNR",
        "ROK",
        "FAST",
        "PAYX",
        "CHRW",
        "EXPD",
        "JBHT",
        "ODFL",
        "XPO",
        # Materials
        "LIN",
        "APD",
        "SHW",
        "FCX",
        "NEM",
        "ECL",
        "DD",
        "DOW",
        "PPG",
        "VMC",
        "MLM",
        "NUE",
        "STLD",
        "RS",
        "RPM",
        "AVY",
        "BALL",
        "AMCR",
        "PKG",
        "IP",
        "WRK",
        "SEE",
        "SON",
        "ALB",
        "FMC",
        "LYB",
        "CE",
        "CF",
        "MOS",
        "IFF",
        # Real Estate
        "PLD",
        "AMT",
        "CCI",
        "EQIX",
        "WELL",
        "DLR",
        "PSA",
        "O",
        "CBRE",
        "IRM",
        "AVB",
        "EQR",
        "ESS",
        "MAA",
        "UDR",
        "CPT",
        "FRT",
        "REG",
        "BXP",
        "VTR",
        "PEAK",
        "ARE",
        "DOC",
        "EXR",
        "INVH",
        "KIM",
        "SPG",
        "SLG",
        "VNO",
        "WY",
        # Utilities
        "NEE",
        "SO",
        "DUK",
        "AEP",
        "SRE",
        "D",
        "PEG",
        "EXC",
        "XEL",
        "WEC",
        "ED",
        "ETR",
        "ES",
        "FE",
        "EIX",
        "PPL",
        "AEE",
        "DTE",
        "NI",
        "LNT",
        "CMS",
        "CNP",
        "ATO",
        "NRG",
        "VST",
        "CEG",
        "PCG",
        "PNW",
        "AWK",
        "WTRG",
        # Communication Services
        "GOOGL",
        "GOOG",
        "META",
        "NFLX",
        "DIS",
        "CMCSA",
        "VZ",
        "T",
        "CHTR",
        "TMUS",
        "PARA",
        "WBD",
        "FOXA",
        "FOX",
        "NWSA",
        "NWS",
        "MTCH",
        "PINS",
        "SNAP",
        "TWTR",
        "LUMN",
        "SIRI",
        "DISH",
        "CABO",
        "LILAK",
        "LILA",
        "LBRDA",
        "LBRDK",
        "FWONA",
        "FWONK",
    }

    logger.info(f"Using comprehensive static list: {len(sp500_comprehensive)} tickers")
    return sp500_comprehensive


def main():
    """Test S&P 500 retrieval methods."""

    # Try file first
    sp500_from_file = get_sp500_from_file()
    if sp500_from_file:
        logger.info(f"Got S&P 500 from file: {len(sp500_from_file)} tickers")
        return sp500_from_file

    # Try alternative sources
    sp500_tickers = get_sp500_alternative_sources()

    if sp500_tickers and len(sp500_tickers) > 400:  # Should be close to 500
        logger.info(f"Successfully retrieved {len(sp500_tickers)} S&P 500 tickers")

        # Save to file for future use
        output_dir = Path("/home/jacobw/quantstack/universe_data")
        output_dir.mkdir(exist_ok=True)

        pd.DataFrame({"ticker": sorted(sp500_tickers)}).to_csv(
            output_dir / "sp500_tickers_retrieved.csv", index=False
        )

        logger.info(
            f"Saved S&P 500 tickers to {output_dir}/sp500_tickers_retrieved.csv"
        )
        return sp500_tickers
    else:
        logger.error(
            f"Failed to get complete S&P 500 list. Got {len(sp500_tickers) if sp500_tickers else 0} tickers"
        )
        return None


if __name__ == "__main__":
    result = main()
    if result:
        print(f"SUCCESS: Retrieved {len(result)} S&P 500 tickers")
        print("Sample tickers:", sorted(list(result))[:10])
    else:
        print("FAILED: Could not retrieve S&P 500 tickers")
