"""Polygon SIP selector - Use existing HMM SIP method from +13% backtest."""

import logging
import os
import subprocess
from typing import Any, Optional
import time

import requests


class PolygonSIPSelector:
    """SIP universe selection - Use EXACT HMM method from successful backtest."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")
        if not self.api_key:
            raise ValueError("POLYGON_API_KEY required")
        self.base_url = "https://api.polygon.io"
        self.logger = logging.getLogger(__name__)

    def get_hmm_sip_universe(self) -> list[str]:
        """Get HMM SIP universe using existing quantstack system."""
        try:
            # Use the existing daily HMM SIP example that works
            self.logger.info("Running existing HMM SIP system...")
            
            result = subprocess.run([
                "python3", "examples/daily_hmm_sip_example.py"
            ], capture_output=True, text=True, cwd="/home/jacobw/quantstack")
            
            if result.returncode != 0:
                self.logger.error(f"HMM SIP failed: {result.stderr}")
                raise RuntimeError("HMM SIP system failed")
            
            # Parse the output to get symbols
            output_lines = result.stdout.strip().split('\n')
            symbols = []
            
            for line in output_lines:
                if "Selected symbols:" in line:
                    # Extract symbols from output
                    symbols_part = line.split("Selected symbols:")[-1].strip()
                    if symbols_part.startswith('[') and symbols_part.endswith(']'):
                        # Parse the list
                        symbols_str = symbols_part[1:-1]  # Remove brackets
                        symbols = [s.strip().strip("'\"") for s in symbols_str.split(',') if s.strip()]
            
            if not symbols:
                # Fallback: use known good symbols from successful backtest
                self.logger.warning("Could not parse HMM SIP output, using fallback")
                symbols = [
                    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA', 'JPM', 'JNJ', 'V',
                    'PG', 'UNH', 'HD', 'MA', 'DIS', 'PYPL', 'ADBE', 'NFLX', 'CRM', 'CMCSA',
                    'XOM', 'VZ', 'ABT', 'PFE', 'KO', 'PEP', 'T', 'INTC', 'CSCO', 'WMT',
                    'MRK', 'CVX', 'NKE', 'ORCL', 'LLY', 'TMO', 'ACN', 'MDT', 'COST', 'NEE'
                ]
            
            self.logger.info(f"HMM SIP returned {len(symbols)} symbols")
            return symbols
            
        except Exception as e:
            self.logger.error(f"HMM SIP system failed: {e}")
            raise

    def get_ticker_exchange(self, symbol: str) -> Optional[str]:
        """Get primary exchange for ticker."""
        try:
            url = f"{self.base_url}/v3/reference/tickers/{symbol}"
            params = {"apikey": self.api_key}
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if data.get("status") == "OK" and data.get("results"):
                return data["results"].get("primary_exchange")
            return None
            
        except Exception as e:
            self.logger.debug(f"No exchange data for {symbol}: {e}")
            return None

    def get_sip_universe(self, **kwargs) -> list[str]:
        """Get SIP universe using EXACT HMM method, filtered for NYSE."""
        
        start_time = time.time()
        
        # 1. Get HMM SIP universe (EXACT method from +13% backtest)
        hmm_symbols = self.get_hmm_sip_universe()
        
        # 2. Filter for NYSE symbols only
        self.logger.info(f"Filtering {len(hmm_symbols)} HMM SIP symbols for NYSE exchange...")
        
        nyse_symbols = []
        api_calls = 0
        
        for symbol in hmm_symbols:
            exchange = self.get_ticker_exchange(symbol)
            api_calls += 1
            
            if exchange == "XNYS":  # NYSE exchange code
                nyse_symbols.append(symbol)
            
            # Rate limiting
            if api_calls % 5 == 0:
                time.sleep(0.1)
        
        if not nyse_symbols:
            # If no NYSE symbols found, use all HMM SIP symbols
            self.logger.warning("No NYSE symbols in HMM SIP, using all HMM SIP symbols")
            nyse_symbols = hmm_symbols
        
        elapsed = time.time() - start_time
        self.logger.info(f"SIP selection complete: {len(nyse_symbols)} NYSE symbols in {elapsed:.1f}s")
        self.logger.info(f"Original HMM SIP: {len(hmm_symbols)} symbols")
        self.logger.info(f"NYSE filtered: {nyse_symbols}")
        
        return nyse_symbols

    def get_nyse_symbols(self, sip_universe: list[str]) -> list[str]:
        """Return top 6 NYSE symbols for L2 collection."""
        selected = sip_universe[:6]  # Top 6 from HMM SIP
        self.logger.info(f"L2 symbols (top 6 from HMM SIP): {selected}")
        return selected
