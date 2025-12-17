"""Polygon SIP selector - REAL analysis on pre-identified NYSE gold tickers."""

import logging
import os
from pathlib import Path
from typing import Any, Optional
import time

import requests


class PolygonSIPSelector:
    """SIP universe selection - REAL analysis on 557 NYSE gold tickers."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")
        if not self.api_key:
            raise ValueError("POLYGON_API_KEY required")
        self.base_url = "https://api.polygon.io"
        self.logger = logging.getLogger(__name__)

    def load_nyse_gold_tickers(self) -> list[str]:
        """Load pre-identified NYSE tickers from gold universe."""
        nyse_file = Path("data/nyse_gold_tickers.txt")
        
        if not nyse_file.exists():
            raise RuntimeError(f"NYSE ticker list not found: {nyse_file}. Run scripts/identify_nyse_gold_tickers.py first")
        
        with open(nyse_file, 'r') as f:
            symbols = [line.strip() for line in f if line.strip()]
        
        self.logger.info(f"Loaded pre-identified NYSE gold tickers: {len(symbols)} symbols")
        return symbols

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

    def calculate_sip_score(self, symbol: str, data: dict[str, Any]) -> float:
        """Calculate SIP score using EXACT method from successful backtest."""
        try:
            volume = data.get("v", 0)
            high = data.get("h", 0)
            low = data.get("l", 0)
            close = data.get("c", 0)
            open_price = data.get("o", 0)
            
            if close == 0:
                return 0.0
                
            # Price range filter ($5-$50) - from successful backtest
            if close < 5 or close > 50:
                return 0.0
                
            # Volume filter (minimum 100K shares)
            if volume < 100_000:
                return 0.0
            
            # SIP scoring method from successful backtest
            # News attention: Volume × |returns| × 100
            returns = abs((close - open_price) / open_price) if open_price > 0 else 0
            news_attention = volume * returns * 100
            
            # Volume expansion (normalize to 10M volume)
            volume_score = min(volume / 10_000_000, 1.0)
            
            # Volatility expansion (normalize to 5% daily range)
            volatility = (high - low) / close if close > 0 else 0
            volatility_score = min(volatility * 20, 1.0)
            
            # News attention score (normalize)
            attention_score = min(news_attention / 1_000_000, 1.0)
            
            # Combined SIP score (emphasize news attention for "stocks in play")
            score = (attention_score * 0.5 + volume_score * 0.3 + volatility_score * 0.2)
            return score
            
        except Exception as e:
            self.logger.error(f"Score calculation failed for {symbol}: {e}")
            return 0.0

    def get_sip_universe(self, top_k: int = 40, score_floor: float = 0.01) -> list[str]:
        """Run REAL SIP analysis on 557 pre-identified NYSE gold tickers."""
        
        start_time = time.time()
        
        # Load pre-identified NYSE tickers (557 symbols)
        nyse_symbols = self.load_nyse_gold_tickers()
        
        # Run SIP analysis on NYSE symbols only
        self.logger.info(f"Running REAL SIP analysis on {len(nyse_symbols)} NYSE gold tickers...")
        
        scored_symbols = []
        api_calls = 0
        
        for i, symbol in enumerate(nyse_symbols):
            # Get market data
            data = self.get_previous_day_data(symbol)
            api_calls += 1
            
            if data is None:
                continue
                
            # Calculate SIP score
            score = self.calculate_sip_score(symbol, data)
            
            if score >= score_floor:
                scored_symbols.append((symbol, score))
            
            # Progress logging
            if (i + 1) % 50 == 0:
                self.logger.info(f"Processed {i+1}/{len(nyse_symbols)}, qualified: {len(scored_symbols)}")
            
            # Rate limiting
            if api_calls % 5 == 0:
                time.sleep(0.1)
        
        if not scored_symbols:
            raise RuntimeError(f"NO NYSE SYMBOLS PASSED SIP ANALYSIS from {len(nyse_symbols)} NYSE gold tickers")
        
        # Sort by score (highest first)
        scored_symbols.sort(key=lambda x: x[1], reverse=True)
        
        # Apply top_k limit
        scored_symbols = scored_symbols[:top_k]
        sip_universe = [symbol for symbol, score in scored_symbols]
        
        elapsed = time.time() - start_time
        self.logger.info(f"REAL SIP analysis complete: {len(sip_universe)} NYSE symbols in {elapsed:.1f}s")
        self.logger.info(f"NYSE tickers processed: {len(nyse_symbols)}")
        self.logger.info(f"Top 10 SIP scores: {scored_symbols[:10]}")
        
        return sip_universe

    def get_nyse_symbols(self, sip_universe: list[str]) -> list[str]:
        """Return top 6 NYSE symbols for L2 collection."""
        selected = sip_universe[:6]  # Top 6 highest scoring
        self.logger.info(f"L2 symbols (top 6 SIP): {selected}")
        return selected
