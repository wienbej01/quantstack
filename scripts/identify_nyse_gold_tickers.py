#!/usr/bin/env python3
"""One-time scan to identify NYSE tickers from gold universe."""

import os
import time
import requests
from pathlib import Path


def main():
    """Identify NYSE tickers from gold universe and save list."""
    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        print("❌ POLYGON_API_KEY not set")
        return
    
    # Load all gold tickers
    gold_path = "/home/jacobw/gcs-mount/gold/stocks/1m/"
    if not os.path.exists(gold_path):
        print(f"❌ Gold path not found: {gold_path}")
        return
    
    all_symbols = []
    for item in os.listdir(gold_path):
        item_path = os.path.join(gold_path, item)
        if os.path.isdir(item_path) and item != "1m":
            all_symbols.append(item)
    
    all_symbols = sorted(all_symbols)
    print(f"🔍 Scanning {len(all_symbols)} gold tickers for NYSE listing...")
    
    nyse_tickers = []
    api_calls = 0
    
    for i, symbol in enumerate(all_symbols):
        try:
            url = f"https://api.polygon.io/v3/reference/tickers/{symbol}"
            response = requests.get(url, params={"apikey": api_key}, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "OK" and data.get("results"):
                    exchange = data["results"].get("primary_exchange", "")
                    if exchange == "XNYS":
                        nyse_tickers.append(symbol)
                        print(f"NYSE: {symbol}")
            
            api_calls += 1
            
            # Progress
            if (i + 1) % 50 == 0:
                print(f"Processed {i+1}/{len(all_symbols)}, NYSE found: {len(nyse_tickers)}")
            
            # Rate limiting
            if api_calls % 5 == 0:
                time.sleep(0.1)
                
        except Exception as e:
            print(f"Error {symbol}: {e}")
    
    # Save NYSE ticker list
    output_file = Path("data/nyse_gold_tickers.txt")
    output_file.parent.mkdir(exist_ok=True)
    
    with open(output_file, "w") as f:
        f.write("\n".join(sorted(nyse_tickers)))
    
    print(f"\n✅ NYSE ticker identification complete:")
    print(f"   Total gold tickers: {len(all_symbols)}")
    print(f"   NYSE tickers: {len(nyse_tickers)}")
    print(f"   Saved to: {output_file}")
    print(f"\nSample NYSE tickers: {nyse_tickers[:10]}")


if __name__ == "__main__":
    main()
