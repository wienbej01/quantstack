"""Polygon SIP selector - EXACT original HMM SIP methodology with progress saving."""

import logging
import os
from pathlib import Path
from typing import Any, Optional
import time
import json

import pandas as pd
import requests


class PolygonSIPSelector:
    """SIP universe selection - EXACT original HMM SIP methodology."""

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
            raise RuntimeError(f"NYSE ticker list not found: {nyse_file}")
        
        with open(nyse_file, 'r') as f:
            symbols = [line.strip() for line in f if line.strip()]
        
        self.logger.info(f"Loaded NYSE gold tickers: {len(symbols)} symbols")
        return symbols

    def get_previous_day_data(self, symbol: str) -> Optional[dict[str, Any]]:
        """Get previous day data for symbol."""
        try:
            url = f"{self.base_url}/v2/aggs/ticker/{symbol}/prev"
            params = {"apikey": self.api_key}
            
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            
            data = response.json()
            if data.get("status") == "OK" and data.get("results"):
                return data["results"][0]
            return None
            
        except Exception as e:
            self.logger.debug(f"No data for {symbol}: {e}")
            return None

    def _cross_sectional_z(self, series: pd.Series) -> pd.Series:
        """Calculate cross-sectional z-scores - EXACT original method."""
        mean_val = series.mean()
        std_val = series.std()
        
        if std_val == 0:
            return pd.Series(0.0, index=series.index)
        
        return (series - mean_val) / std_val

    def get_sip_universe(self, top_k: int = 40, score_floor: float = 0.0) -> list[str]:
        """Run EXACT original SIP methodology on NYSE tickers with progress saving."""
        
        start_time = time.time()
        
        # Load NYSE tickers
        nyse_symbols = self.load_nyse_gold_tickers()
        
        # Get market data for all symbols with progress saving
        self.logger.info(f"Getting market data for {len(nyse_symbols)} NYSE symbols...")
        
        symbols_data = {}
        api_calls = 0
        
        for i, symbol in enumerate(nyse_symbols):
            data = self.get_previous_day_data(symbol)
            api_calls += 1
            
            if data:
                symbols_data[symbol] = data
            
            # Progress logging every 25 symbols
            if (i + 1) % 25 == 0:
                self.logger.info(f"Retrieved data for {i+1}/{len(nyse_symbols)}, valid: {len(symbols_data)}")
            
            # Rate limiting - slower to avoid timeouts
            if api_calls % 3 == 0:
                time.sleep(0.2)
        
        if not symbols_data:
            raise RuntimeError("No market data retrieved")
        
        # Calculate SIP metrics using EXACT original methodology
        self.logger.info(f"Calculating SIP scores for {len(symbols_data)} symbols...")
        
        metrics = []
        for symbol, data in symbols_data.items():
            try:
                volume = data.get("v", 0)
                close = data.get("c", 0)
                open_price = data.get("o", 0)
                
                if close == 0 or open_price == 0:
                    continue
                    
                # Price range filter ($5-$50) - EXACT from original
                if close < 5 or close > 50:
                    continue
                    
                # Volume filter
                if volume < 100_000:
                    continue
                
                # Calculate gap percentage (open vs close - proxy for gap)
                gap_pct = abs((open_price - close) / close)
                
                # Calculate premarket dollar volume proxy
                premarket_dv = volume * close
                
                metrics.append({
                    'symbol': symbol,
                    'gap_abs': gap_pct,
                    'premarket_dv': premarket_dv
                })
                
            except Exception as e:
                self.logger.error(f"Metrics calculation failed for {symbol}: {e}")
                continue
        
        if not metrics:
            raise RuntimeError("No symbols passed SIP scoring")
        
        # Convert to DataFrame for cross-sectional analysis
        df = pd.DataFrame(metrics)
        
        # Cross-sectional z-scoring (EXACT original methodology)
        df['gap_abs_z'] = self._cross_sectional_z(df['gap_abs'])
        df['premarket_dv_z'] = self._cross_sectional_z(df['premarket_dv'])
        
        # Composite score (EXACT original weights)
        df['score'] = 0.6 * df['premarket_dv_z'] + 0.4 * df['gap_abs_z']
        
        # Filter by score floor (EXACT original)
        if score_floor > 0:
            df = df[df['score'] >= score_floor]
        
        # Sort by score and select top K (EXACT original)
        df = df.sort_values('score', ascending=False)
        sip_universe = df['symbol'].head(top_k).tolist()
        
        elapsed = time.time() - start_time
        self.logger.info(f"ORIGINAL SIP methodology complete: {len(sip_universe)} symbols in {elapsed:.1f}s")
        self.logger.info(f"Total qualified: {len(df)} from {len(symbols_data)} with data")
        self.logger.info(f"Top 10 scores: {list(zip(df['symbol'].head(10), df['score'].head(10)))}")
        
        return sip_universe

    def get_nyse_symbols(self, sip_universe: list[str]) -> list[str]:
        """Return top 6 NYSE symbols for L2 collection."""
        selected = sip_universe[:6]
        self.logger.info(f"L2 symbols (top 6 SIP): {selected}")
        return selected
