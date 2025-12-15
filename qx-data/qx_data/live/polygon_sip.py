"""Polygon SIP selector with comprehensive NYSE detection."""

import logging
import os
from typing import Any, Optional
import time

import requests


class PolygonSIPSelector:
    """SIP universe selection with proper NYSE identification."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")
        if not self.api_key:
            raise ValueError("POLYGON_API_KEY required")
        self.base_url = "https://api.polygon.io"
        self.logger = logging.getLogger(__name__)

    def load_gold_universe(self) -> list[str]:
        """Load universe from GCS gold data."""
        try:
            gold_path = "/home/jacobw/gcs-mount/gold/stocks/1m/"
            
            if not os.path.exists(gold_path):
                self.logger.warning(f"Gold data path not found: {gold_path}")
                return self._fallback_universe()
            
            # Get all ticker directories
            symbols = []
            for item in os.listdir(gold_path):
                item_path = os.path.join(gold_path, item)
                if os.path.isdir(item_path) and item != "1m":  # Skip symlink
                    symbols.append(item)
            
            symbols = sorted(symbols)
            self.logger.info(f"Loaded gold universe: {len(symbols)} symbols")
            return symbols
            
        except Exception as e:
            self.logger.error(f"Failed to load gold universe: {e}")
            return self._fallback_universe()

    def _fallback_universe(self) -> list[str]:
        """Fallback universe if gold data not available."""
        return [
            'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA', 'JPM', 'JNJ', 'V',
            'PG', 'UNH', 'HD', 'MA', 'DIS', 'PYPL', 'ADBE', 'NFLX', 'CRM', 'CMCSA',
            'XOM', 'VZ', 'ABT', 'PFE', 'KO', 'PEP', 'T', 'INTC', 'CSCO', 'WMT'
        ]

    def get_previous_day_data(self, symbol: str) -> Optional[dict[str, Any]]:
        """Get previous day data for symbol."""
        try:
            url = f"{self.base_url}/v2/aggs/ticker/{symbol}/prev"
            params = {"apikey": self.api_key}
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if data.get("status") == "OK" and data.get("results"):
                return data["results"][0]
            
            return None
            
        except Exception as e:
            self.logger.debug(f"No data for {symbol}: {e}")
            return None

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

    def calculate_hmm_score(self, symbol: str, data: dict[str, Any]) -> float:
        """Calculate HMM score for symbol."""
        try:
            volume = data.get("v", 0)
            high = data.get("h", 0)
            low = data.get("l", 0)
            close = data.get("c", 0)
            open_price = data.get("o", 0)
            
            if close == 0:
                return 0.0
                
            # Price range filter ($5-$50)
            if close < 5 or close > 50:
                return 0.0
                
            # Volume filter (minimum 500K shares)
            if volume < 500_000:
                return 0.0
            
            # News attention score: Volume × |returns| × 100
            returns = abs((close - open_price) / open_price) if open_price > 0 else 0
            news_attention = volume * returns * 100
            
            # Volume score (normalize to 10M volume)
            volume_score = min(volume / 10_000_000, 1.0)
            
            # Volatility score (normalize to 5% daily range)
            volatility = (high - low) / close if close > 0 else 0
            volatility_score = min(volatility * 20, 1.0)
            
            # News attention score (normalize)
            attention_score = min(news_attention / 1_000_000, 1.0)
            
            # Combined HMM score
            score = (attention_score * 0.5 + volume_score * 0.3 + volatility_score * 0.2)
            return score
            
        except Exception as e:
            self.logger.error(f"Score calculation failed for {symbol}: {e}")
            return 0.0

    def get_sip_universe(self, 
                        top_k: int = 40,
                        min_score: float = 0.1) -> list[str]:
        """Get SIP universe from gold data + Polygon scoring."""
        
        start_time = time.time()
        
        # 1. Load gold universe (1000+ symbols)
        all_symbols = self.load_gold_universe()
        
        if not all_symbols:
            raise RuntimeError("NO GOLD UNIVERSE LOADED - Check GCS mount")
        
        # 2. Score symbols with market data
        self.logger.info(f"Scoring {len(all_symbols)} gold symbols for SIP selection...")
        
        scored_symbols = []
        api_calls = 0
        
        for i, symbol in enumerate(all_symbols):
            # Get market data
            data = self.get_previous_day_data(symbol)
            api_calls += 1
            
            if data is None:
                continue
                
            # Calculate HMM score
            score = self.calculate_hmm_score(symbol, data)
            
            if score >= min_score:
                scored_symbols.append((symbol, score))
            
            # Progress logging
            if (i + 1) % 100 == 0:
                self.logger.info(f"Processed {i+1}/{len(all_symbols)}, qualified: {len(scored_symbols)}")
            
            # Rate limiting
            if api_calls % 5 == 0:
                time.sleep(0.1)
        
        if not scored_symbols:
            raise RuntimeError(f"NO SYMBOLS PASSED SIP SELECTION from {len(all_symbols)} gold symbols")
        
        # 3. Sort by score and select top K
        scored_symbols.sort(key=lambda x: x[1], reverse=True)
        selected = [symbol for symbol, score in scored_symbols[:top_k]]
        
        elapsed = time.time() - start_time
        self.logger.info(f"SIP selection complete: {len(selected)} symbols in {elapsed:.1f}s")
        self.logger.info(f"Gold symbols processed: {len(all_symbols)}")
        self.logger.info(f"Qualified symbols: {len(scored_symbols)}")
        self.logger.info(f"Top 10 scores: {scored_symbols[:10]}")
        
        return selected

    def get_nyse_symbols(self, sip_universe: list[str]) -> list[str]:
        """Get NYSE symbols from SIP universe using Polygon API."""
        self.logger.info(f"Identifying NYSE symbols from {len(sip_universe)} SIP symbols...")
        
        nyse_symbols = []
        api_calls = 0
        
        for symbol in sip_universe:
            exchange = self.get_ticker_exchange(symbol)
            api_calls += 1
            
            if exchange == "XNYS":  # NYSE exchange code
                nyse_symbols.append(symbol)
                self.logger.debug(f"NYSE: {symbol}")
            
            # Rate limiting
            if api_calls % 5 == 0:
                time.sleep(0.1)
        
        if not nyse_symbols:
            # Fallback: use top SIP symbols
            self.logger.warning("No NYSE symbols found in SIP universe, using top SIP symbols")
            nyse_symbols = sip_universe[:6]
        
        # Limit to 6 for L2 collection
        selected_nyse = nyse_symbols[:6]
        
        self.logger.info(f"NYSE symbols selected for L2: {selected_nyse}")
        return selected_nyse
