"""ML model integration for live trading - regime-aware approach."""

import logging
import pickle
from pathlib import Path
from typing import Any, Optional

import numpy as np


class RegimeAwarePredictor:
    """Regime-aware ML predictor using cross-sectional features."""

    def __init__(self, model_path: str):
        self.model_path = Path(model_path)
        self.logger = logging.getLogger(__name__)
        
        # Cross-sectional features from successful strategy
        self.features = [
            "cross_rank_ret", "cross_rank_vol", "sector_momentum", "cross_dispersion",
            "market_breadth", "up_down_ratio", "rel_strength_5", "rel_strength_10", 
            "rel_strength_20", "market_ret_5", "market_ret_10"
        ]
        
        # Use simple heuristic-based predictions until models retrained with L2 data
        self.use_heuristics = True
        self.logger.info("Using heuristic-based predictions (models will be retrained with L2 data)")

    def detect_regime(self, market_data: dict[str, Any]) -> str:
        """Detect current market regime."""
        # Simple regime detection based on volatility and momentum
        volatility = market_data.get("volatility", 0.2)
        momentum = market_data.get("price_momentum", 0.0)
        
        if volatility > 0.3:
            return "high_vol"
        elif abs(momentum) > 0.02:
            return "bull" if momentum > 0 else "bear"
        else:
            return "sideways"

    def predict(self, symbol: str, features: dict[str, Any]) -> Optional[float]:
        """Make prediction for symbol using heuristic approach."""
        try:
            # Detect regime
            regime = self.detect_regime(features)
            
            # Extract key signals
            volume = features.get("volume", 1000000)
            volatility = features.get("volatility", 0.2)
            momentum = features.get("price_momentum", 0.0)
            
            # News-driven heuristic scoring (based on successful strategy)
            volume_signal = min(volume / 5_000_000, 1.0)  # Volume expansion
            volatility_signal = min(volatility * 10, 1.0)  # Volatility expansion
            momentum_signal = abs(momentum) * 50  # Price momentum
            
            # Regime-specific logic
            if regime == "bull":
                # In bull markets, favor momentum continuation
                score = 0.5 + (momentum_signal * 0.3) + (volume_signal * 0.2)
            elif regime == "bear":
                # In bear markets, favor contrarian plays
                score = 0.5 - (momentum_signal * 0.2) + (volatility_signal * 0.3)
            elif regime == "high_vol":
                # High volatility: favor mean reversion
                score = 0.5 - (momentum_signal * 0.4) + (volume_signal * 0.1)
            else:  # sideways
                # Sideways: neutral with slight momentum bias
                score = 0.5 + (momentum_signal * 0.1)
            
            # Clamp to valid range
            score = max(0.0, min(1.0, score))
            
            self.logger.debug(f"{symbol} prediction: {score:.3f} (regime: {regime})")
            return score
            
        except Exception as e:
            self.logger.error(f"Prediction failed for {symbol}: {e}")
            return None


class PaperTrader:
    """Paper trading execution via IBKR."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7497):
        self.host = host
        self.port = port
        self.logger = logging.getLogger(__name__)
        self.ib = None
        self.positions = {}

    def connect(self):
        """Connect to IBKR."""
        try:
            from ib_insync import IB
            self.ib = IB()
            self.ib.connect(self.host, self.port, clientId=400, readonly=False)
            self.logger.info("Connected to IBKR for paper trading")
            return True
        except Exception as e:
            self.logger.error(f"IBKR connection failed: {e}")
            return False

    def place_order(self, symbol: str, action: str, quantity: int = 100):
        """Place paper trade order."""
        if not self.ib or not self.ib.isConnected():
            self.logger.error("Not connected to IBKR")
            return False

        try:
            from ib_insync import Stock, MarketOrder
            
            # Create contract
            contract = Stock(symbol, "SMART", "USD")
            
            # Create order
            order = MarketOrder(action, quantity)
            
            # Place order
            trade = self.ib.placeOrder(contract, order)
            
            self.logger.info(f"Paper trade placed: {action} {quantity} {symbol}")
            return True
            
        except Exception as e:
            self.logger.error(f"Order placement failed: {e}")
            return False

    def get_positions(self) -> dict[str, Any]:
        """Get current positions."""
        if not self.ib or not self.ib.isConnected():
            return {}
            
        try:
            positions = self.ib.positions()
            return {pos.contract.symbol: pos.position for pos in positions}
        except Exception as e:
            self.logger.error(f"Failed to get positions: {e}")
            return {}

    def disconnect(self):
        """Disconnect from IBKR."""
        if self.ib:
            self.ib.disconnect()
            self.logger.info("Disconnected from IBKR")
