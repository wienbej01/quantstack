"""L2 Scalping System - Signal Generation Module

Based on analysis from L2_SCALPING_SYSTEM_FOUNDATION.md
Implements OBI momentum and hidden liquidity signals.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

import numpy as np


class SignalType(Enum):
    LONG = 1
    SHORT = -1
    NONE = 0


class LiquidityType(Enum):
    HIDDEN_BUY = "hidden_buy"
    HIDDEN_SELL = "hidden_sell"
    NONE = "none"


@dataclass
class L2Snapshot:
    """L2 market data snapshot"""

    symbol: str
    timestamp: float
    mid: float
    spread: float
    obi_1: float
    obi_5: float
    depth_bid: float
    depth_ask: float
    pressure: float


@dataclass
class TradingSignal:
    """Trading signal with metadata"""

    symbol: str
    timestamp: float
    signal_type: SignalType
    strength: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    hidden_liquidity: LiquidityType
    execution_window: str
    thin_book_warning: bool


class L2SignalGenerator:
    """Generate trading signals from L2 market data"""

    def __init__(self, config: Dict):
        self.config = config
        self.symbol_stats = self._load_symbol_stats()

    def _load_symbol_stats(self) -> Dict:
        """Load pre-computed symbol statistics"""
        return {
            "HAL": {
                "pressure_mean": -700,
                "pressure_std": 2000,
                "bid_p10": 3200,
                "ask_p10": 4200,
            },
            "PFE": {
                "pressure_mean": -5500,
                "pressure_std": 20000,
                "bid_p10": 31100,
                "ask_p10": 38500,
            },
            "LUV": {
                "pressure_mean": -300,
                "pressure_std": 1700,
                "bid_p10": 2100,
                "ask_p10": 2100,
            },
        }

    def generate_signal(self, snapshot: L2Snapshot) -> TradingSignal:
        """Generate trading signal from L2 snapshot"""

        # Primary OBI momentum signal
        signal_type = self._obi_momentum_signal(snapshot.obi_1)
        strength = self._calculate_signal_strength(snapshot.obi_1)

        # Hidden liquidity detection
        hidden_liquidity = self._detect_hidden_liquidity(snapshot.obi_1, snapshot.obi_5)

        # Execution timing
        execution_window = self._execution_window(
            snapshot.obi_1, snapshot.depth_bid, snapshot.depth_ask
        )

        # Risk filters
        thin_book_warning = self._thin_book_warning(
            snapshot.symbol, snapshot.depth_bid, snapshot.depth_ask
        )

        # Composite confidence score
        confidence = self._calculate_confidence(
            snapshot, hidden_liquidity, thin_book_warning
        )

        return TradingSignal(
            symbol=snapshot.symbol,
            timestamp=snapshot.timestamp,
            signal_type=signal_type,
            strength=strength,
            confidence=confidence,
            hidden_liquidity=hidden_liquidity,
            execution_window=execution_window,
            thin_book_warning=thin_book_warning,
        )

    def _obi_momentum_signal(self, obi_1: float) -> SignalType:
        """Primary OBI momentum signal"""
        entry_threshold = self.config.get("obi_entry_threshold", 0.3)

        if obi_1 > entry_threshold:
            return SignalType.LONG
        elif obi_1 < -entry_threshold:
            return SignalType.SHORT
        return SignalType.NONE

    def _calculate_signal_strength(self, obi_1: float) -> float:
        """Calculate signal strength (0.0 to 1.0)"""
        extreme_threshold = self.config.get("obi_extreme_threshold", 0.6)
        entry_threshold = self.config.get("obi_entry_threshold", 0.3)

        abs_obi = abs(obi_1)
        if abs_obi < entry_threshold:
            return 0.0

        # Linear scaling from entry to extreme threshold
        strength = (abs_obi - entry_threshold) / (extreme_threshold - entry_threshold)
        return min(1.0, strength)

    def _detect_hidden_liquidity(self, obi_1: float, obi_5: float) -> LiquidityType:
        """Detect hidden institutional liquidity"""
        if obi_1 < -0.3 and obi_5 > 0.2:
            return LiquidityType.HIDDEN_BUY
        elif obi_1 > 0.3 and obi_5 < -0.2:
            return LiquidityType.HIDDEN_SELL
        return LiquidityType.NONE

    def _execution_window(
        self, obi_1: float, depth_bid: float, depth_ask: float
    ) -> str:
        """Identify favorable execution windows"""
        if obi_1 < -0.3 and depth_ask > depth_bid * 1.5:
            return "favorable_buy"
        elif obi_1 > 0.3 and depth_bid > depth_ask * 1.5:
            return "favorable_sell"
        return "neutral"

    def _thin_book_warning(
        self, symbol: str, depth_bid: float, depth_ask: float
    ) -> bool:
        """Check for thin book conditions"""
        stats = self.symbol_stats.get(symbol, {"bid_p10": 2000, "ask_p10": 2000})
        return depth_bid < stats["bid_p10"] or depth_ask < stats["ask_p10"]

    def _calculate_confidence(
        self,
        snapshot: L2Snapshot,
        hidden_liquidity: LiquidityType,
        thin_book_warning: bool,
    ) -> float:
        """Calculate composite confidence score"""
        base_confidence = abs(snapshot.obi_1)  # Higher OBI = higher confidence

        # Reduce confidence for hidden liquidity (adverse selection risk)
        if hidden_liquidity != LiquidityType.NONE:
            base_confidence *= 0.7

        # Reduce confidence for thin book
        if thin_book_warning:
            base_confidence *= 0.5

        # Boost confidence for favorable execution window
        if snapshot.obi_1 > 0 and "favorable_buy" in self._execution_window(
            snapshot.obi_1, snapshot.depth_bid, snapshot.depth_ask
        ):
            base_confidence *= 1.2

        return min(1.0, base_confidence)


class SignalValidator:
    """Validate signals before execution"""

    def __init__(self, config: Dict):
        self.config = config
        self.min_confidence = config.get("min_confidence", 0.3)
        self.max_spread_multiple = config.get("max_spread_multiple", 2.0)

    def is_valid_signal(
        self, signal: TradingSignal, snapshot: L2Snapshot
    ) -> Tuple[bool, str]:
        """Validate if signal should be traded"""

        # Check minimum confidence
        if signal.confidence < self.min_confidence:
            return False, f"Low confidence: {signal.confidence:.3f}"

        # Check spread conditions
        symbol_config = self.config.get("symbols", {}).get(signal.symbol, {})
        max_spread = symbol_config.get("max_spread", 0.03)

        if snapshot.spread > max_spread:
            return False, f"Spread too wide: {snapshot.spread:.4f}"

        # Check thin book warning
        if signal.thin_book_warning and not self.config.get("allow_thin_book", False):
            return False, "Thin book detected"

        # All checks passed
        return True, "Valid signal"
