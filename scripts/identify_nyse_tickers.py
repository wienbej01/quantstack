#!/usr/bin/env python3
"""Identify NYSE tickers from gold data using Polygon API."""

import os
import time
import requests
from pathlib import Path


def get_ticker_details(symbol: str, api_key: str) -> dict:
    """Get ticker details from Polygon API."""
    try:
        url = f"https://api.polygon.io/v3/reference/tickers/{symbol}"
        params = {"apikey": api_key}
        
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        if data.get("status") == "OK" and data.get("results"):
            return data["results"]
        return {}
        
    except Exception as e:
        print(f"Error for {symbol}: {e}")
        return {}


def main():
    """Identify NYSE tickers from gold data."""
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        print("❌ POLYGON_API_KEY not set")
        return
    
    # Load all gold tickers
    with open("/tmp/all_gold_tickers.txt", "r") as f:
        all_tickers = [line.strip() for line in f if line.strip()]
    
    print(f"Checking {len(all_tickers)} tickers for NYSE listing...")
    
    nyse_tickers = []
    nasdaq_tickers = []
    other_tickers = []
    
    for i, ticker in enumerate(all_tickers):
        details = get_ticker_details(ticker, api_key)
        
        if details:
            primary_exchange = details.get("primary_exchange", "")
            market = details.get("market", "")
            
            if "NYSE" in primary_exchange or "New York" in primary_exchange:
                nyse_tickers.append(ticker)
                print(f"NYSE: {ticker} ({primary_exchange})")
            elif "NASDAQ" in primary_exchange:
                nasdaq_tickers.append(ticker)
            else:
                other_tickers.append(ticker)
                print(f"OTHER: {ticker} ({primary_exchange})")
        
        # Progress and rate limiting
        if (i + 1) % 50 == 0:
            print(f"Processed {i+1}/{len(all_tickers)}: NYSE={len(nyse_tickers)}, NASDAQ={len(nasdaq_tickers)}, Other={len(other_tickers)}")
        
        if (i + 1) % 5 == 0:
            time.sleep(0.1)  # Rate limiting
    
    print(f"\n📊 Final Results:")
    print(f"NYSE: {len(nyse_tickers)} tickers")
    print(f"NASDAQ: {len(nasdaq_tickers)} tickers") 
    print(f"Other: {len(other_tickers)} tickers")
    
    # Save NYSE tickers
    with open("/tmp/nyse_tickers.txt", "w") as f:
        f.write("\n".join(sorted(nyse_tickers)))
    
    print(f"\n✅ NYSE tickers saved to /tmp/nyse_tickers.txt")
    print(f"Sample NYSE tickers: {nyse_tickers[:10]}")


if __name__ == "__main__":
    main()
