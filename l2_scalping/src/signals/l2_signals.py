"""L2 Scalping System - Signal Generation Module

Based on analysis from L2_SCALPING_SYSTEM_FOUNDATION.md
Implements OBI momentum and hidden liquidity signals.
"""

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Tuple



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
    median_spread: float | None = None
    calibration_points: int = 0


class L2SignalGenerator:
    """Generate trading signals from L2 market data"""

    def __init__(self, config: Dict):
        self.config = config
        self.symbol_stats = self._load_symbol_stats()
        strategy_cfg = self.config.get("strategy", self.config)
        self.calibration_window = strategy_cfg.get("calibration_window_points", 240)
        self.min_calibration_points = strategy_cfg.get("min_calibration_points", 60)
        self._calibration: dict[str, dict[str, deque[float]]] = {}

    def _load_symbol_stats(self) -> Dict:
        """Load default symbol statistics - applied to all SIP symbols dynamically"""
        # Conservative defaults for any symbol from daily SIP
        # Real stats are computed during calibration window
        return {
            "defaults": {
                "pressure_mean": 0,
                "pressure_std": 5000,
                "bid_p10": 2000,
                "ask_p10": 2000,
            },
        }

    def generate_signal(self, snapshot: L2Snapshot) -> TradingSignal:
        """Generate trading signal from L2 snapshot"""
        calibration = self._update_calibration(snapshot)
        median_spread = calibration.get("median_spread")
        calibration_points = calibration.get("points", 0)

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
            snapshot.symbol, snapshot.depth_bid, snapshot.depth_ask, calibration
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
            median_spread=median_spread,
            calibration_points=calibration_points,
        )

    def _obi_momentum_signal(self, obi_1: float) -> SignalType:
        """Primary OBI momentum signal"""
        strategy_cfg = self.config.get("strategy", self.config)
        entry_threshold = strategy_cfg.get("obi_entry_threshold", 0.3)

        if obi_1 > entry_threshold:
            return SignalType.LONG
        elif obi_1 < -entry_threshold:
            return SignalType.SHORT
        return SignalType.NONE

    def _calculate_signal_strength(self, obi_1: float) -> float:
        """Calculate signal strength (0.0 to 1.0)"""
        strategy_cfg = self.config.get("strategy", self.config)
        extreme_threshold = strategy_cfg.get("obi_extreme_threshold", 0.6)
        entry_threshold = strategy_cfg.get("obi_entry_threshold", 0.3)

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
        self,
        symbol: str,
        depth_bid: float,
        depth_ask: float,
        calibration: dict[str, float],
    ) -> bool:
        """Check for thin book conditions"""
        bid_p10 = calibration.get("bid_p10")
        ask_p10 = calibration.get("ask_p10")
        if bid_p10 is None or ask_p10 is None:
            stats = self.symbol_stats.get(symbol, {"bid_p10": 2000, "ask_p10": 2000})
            bid_p10 = stats["bid_p10"]
            ask_p10 = stats["ask_p10"]
        return depth_bid < bid_p10 or depth_ask < ask_p10

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

    def _update_calibration(self, snapshot: L2Snapshot) -> dict[str, float]:
        """Update rolling calibration stats for a symbol"""
        calib = self._calibration.setdefault(
            snapshot.symbol,
            {
                "spread": deque(maxlen=self.calibration_window),
                "depth_bid": deque(maxlen=self.calibration_window),
                "depth_ask": deque(maxlen=self.calibration_window),
                "pressure": deque(maxlen=self.calibration_window),
            },
        )
        calib["spread"].append(snapshot.spread)
        calib["depth_bid"].append(snapshot.depth_bid)
        calib["depth_ask"].append(snapshot.depth_ask)
        calib["pressure"].append(snapshot.pressure)

        points = len(calib["spread"])
        if points < self.min_calibration_points:
            return {"points": points}

        sorted_spread = sorted(calib["spread"])
        sorted_bid = sorted(calib["depth_bid"])
        sorted_ask = sorted(calib["depth_ask"])
        p10_index = max(0, int(points * 0.1) - 1)

        median_spread = sorted_spread[points // 2]
        bid_p10 = sorted_bid[p10_index]
        ask_p10 = sorted_ask[p10_index]

        return {
            "points": points,
            "median_spread": median_spread,
            "bid_p10": bid_p10,
            "ask_p10": ask_p10,
        }


class SignalValidator:
    """Validate signals before execution"""

    def __init__(self, strategy_config: Dict, risk_config: Dict):
        self.strategy_config = strategy_config
        self.risk_config = risk_config
        strategy_cfg = strategy_config.get("strategy", strategy_config)
        self.min_confidence = strategy_cfg.get("min_confidence", 0.3)
        self.max_spread_multiple = strategy_cfg.get("max_spread_multiple", 2.0)
        self.confirm_k = strategy_cfg.get("confirm_k", 2)
        self._regime_history: Dict[str, list[int]] = {}

    def is_valid_signal(
        self, signal: TradingSignal, snapshot: L2Snapshot
    ) -> Tuple[bool, str]:
        """Validate if signal should be traded"""
        strategy_cfg = self.strategy_config.get("strategy", self.strategy_config)
        symbols_cfg = self.strategy_config.get("symbols", {})
        thin_book_cfg = self.risk_config.get("thin_book", {})

        # Check minimum confidence
        if signal.confidence < self.min_confidence:
            return False, f"Low confidence: {signal.confidence:.3f}"

        # Enforce calibration warmup
        min_points = strategy_cfg.get("min_calibration_points", 60)
        if signal.calibration_points < min_points:
            return False, "Calibration warmup"

        # Check spread conditions
        symbol_config = symbols_cfg.get(signal.symbol, {})
        max_spread = symbol_config.get("max_spread")
        median_spread = signal.median_spread or symbol_config.get("median_spread")

        allowed_spread = max_spread if max_spread is not None else None
        if median_spread is not None:
            median_cap = median_spread * self.max_spread_multiple
            allowed_spread = (
                median_cap
                if allowed_spread is None
                else min(allowed_spread, median_cap)
            )

        if allowed_spread is not None and snapshot.spread > allowed_spread:
            return False, f"Spread too wide: {snapshot.spread:.4f}"

        # Check thin book warning
        allow_thin = thin_book_cfg.get("allow_thin_book", False)
        if signal.thin_book_warning and not allow_thin:
            return False, "Thin book detected"

        # Hidden liquidity adverse selection filter
        if signal.signal_type == SignalType.LONG:
            if signal.hidden_liquidity == LiquidityType.HIDDEN_BUY:
                return False, "Hidden liquidity adverse selection (long)"
        if signal.signal_type == SignalType.SHORT:
            if signal.hidden_liquidity == LiquidityType.HIDDEN_SELL:
                return False, "Hidden liquidity adverse selection (short)"

        # Regime confirmation gate
        if signal.signal_type != SignalType.NONE:
            history = self._regime_history.setdefault(signal.symbol, [])
            history.append(signal.signal_type.value)
            history[:] = history[-self.confirm_k :]

            if len(history) < self.confirm_k or len(set(history)) > 1:
                return False, "Regime not confirmed"
        else:
            self._regime_history[signal.symbol] = []

        # All checks passed
        return True, "Valid signal"
