"""Polygon API integration for SIP universe selection."""

import logging
import os
from typing import Any, Optional

import requests


class PolygonSIPSelector:
    """SIP universe selection using Polygon API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("POLYGON_API_KEY")
        self.base_url = "https://api.polygon.io"
        self.logger = logging.getLogger(__name__)

    def get_market_data(self, symbol: str) -> Optional[dict[str, Any]]:
        """Get market data for symbol."""
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
            self.logger.error(f"Failed to get data for {symbol}: {e}")
            return None

    def calculate_hmm_score(self, symbol: str) -> float:
        """Calculate HMM-like score for symbol."""
        data = self.get_market_data(symbol)
        if not data:
            return 0.0

        try:
            # Simple scoring based on volume and volatility
            volume = data.get("v", 0)
            high = data.get("h", 0)
            low = data.get("l", 0)
            close = data.get("c", 0)
            
            if close == 0:
                return 0.0
                
            # Volume score (normalized)
            volume_score = min(volume / 1_000_000, 10) / 10  # Cap at 10M volume
            
            # Volatility score
            volatility = (high - low) / close if close > 0 else 0
            volatility_score = min(volatility * 100, 5) / 5  # Cap at 5%
            
            # Combined score
            score = (volume_score * 0.6 + volatility_score * 0.4)
            return min(score, 1.0)
            
        except Exception as e:
            self.logger.error(f"Score calculation failed for {symbol}: {e}")
            return 0.0

    def get_sip_universe(self, 
                        candidate_symbols: Optional[list[str]] = None,
                        top_k: int = 40,
                        min_score: float = 0.1) -> list[str]:
        """Get SIP universe selection."""
        
        # Default candidate pool (top liquid stocks)
        if candidate_symbols is None:
            candidate_symbols = [
                'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA', 'JPM',
                'JNJ', 'V', 'PG', 'UNH', 'HD', 'MA', 'DIS', 'PYPL', 'ADBE', 'NFLX',
                'CRM', 'CMCSA', 'XOM', 'VZ', 'ABT', 'PFE', 'KO', 'PEP', 'T', 'INTC',
                'CSCO', 'WMT', 'MRK', 'CVX', 'NKE', 'ORCL', 'LLY', 'TMO', 'ACN', 'MDT',
                'COST', 'NEE', 'DHR', 'TXN', 'QCOM', 'HON', 'UPS', 'LOW', 'IBM', 'AMGN',
                'BA', 'CAT', 'GS', 'MMM', 'AXP', 'TRV', 'SHW', 'MCD', 'WBA', 'DOW'
            ]

        self.logger.info(f"Scoring {len(candidate_symbols)} symbols for SIP selection")
        
        # Score all symbols
        scored_symbols = []
        for symbol in candidate_symbols:
            score = self.calculate_hmm_score(symbol)
            if score >= min_score:
                scored_symbols.append((symbol, score))

        # Sort by score and select top K
        scored_symbols.sort(key=lambda x: x[1], reverse=True)
        selected = [symbol for symbol, score in scored_symbols[:top_k]]
        
        self.logger.info(f"Selected {len(selected)} symbols for SIP universe")
        self.logger.info(f"Top 5 scores: {scored_symbols[:5]}")
        
        return selected

    def get_nyse_symbols(self, sip_universe: list[str]) -> list[str]:
        """Filter for NYSE-listed symbols."""
        # NYSE symbols from the universe (approximate)
        nyse_symbols = [
            'JPM', 'JNJ', 'V', 'PG', 'UNH', 'HD', 'MA', 'DIS', 'XOM', 'VZ',
            'ABT', 'PFE', 'KO', 'PEP', 'T', 'CVX', 'NKE', 'LLY', 'TMO', 'ACN',
            'MDT', 'NEE', 'DHR', 'HON', 'UPS', 'LOW', 'IBM', 'BA', 'CAT', 'GS',
            'MMM', 'AXP', 'TRV', 'SHW', 'MCD', 'WBA', 'DOW'
        ]
        
        # Filter SIP universe for NYSE symbols
        nyse_filtered = [s for s in sip_universe if s in nyse_symbols]
        
        self.logger.info(f"NYSE symbols in SIP universe: {len(nyse_filtered)}")
        return nyse_filtered
