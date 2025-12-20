"""Context-aware filtering for L2 signals.

Hard gates: Block trades in unfavorable regimes
Soft gates: Tier trades by priority/sizing based on context
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class TradeTier(Enum):
    """Trade priority tiers based on context"""
    BLOCKED = 0      # Hard gate - no trade
    LOW = 1          # Reduced size (50%)
    NORMAL = 2       # Standard size (100%)
    HIGH = 3         # Full size, priority execution


@dataclass
class ContextFeatures:
    """1-minute OHLCV context features for filtering"""
    rel_vol: float = 1.0           # Relative volume vs 20-bar MA
    rsi_14: float = 50.0           # RSI(14)
    vol_expansion: bool = False    # Volatility expanding (vol_5 > 1.5 * vol_20)
    vol_contraction: bool = False  # Volatility contracting (vol_5 < 0.5 * vol_20)
    bb_squeeze: bool = False       # Bollinger squeeze (width < 80% of avg)
    displacement_up: bool = False  # Strong up move (ret > 2 * std)
    displacement_down: bool = False # Strong down move (ret < -2 * std)
    mom_15: float = 0.0            # 15-bar momentum (bps)


@dataclass
class ContextFilterResult:
    """Result of context filtering"""
    tier: TradeTier
    size_multiplier: float  # 0.0 to 1.0
    reasons: list[str] = field(default_factory=list)
    soft_boosts: list[str] = field(default_factory=list)


class ContextFilter:
    """Filter L2 signals based on 1-minute context features"""
    
    def __init__(self, config: dict):
        self.config = config
        gates = config.get("context_gates", {})
        
        # Hard gates (robust + economic)
        hard = gates.get("hard", {})
        self.min_rel_vol = hard.get("min_rel_vol", 2.0)
        self.block_vol_expansion = hard.get("block_vol_expansion", True)
        self.block_bb_squeeze = hard.get("block_bb_squeeze", True)
        self.block_vol_contraction = hard.get("block_vol_contraction", False)
        
        # Soft gates (for sizing/priority)
        soft = gates.get("soft", {})
        self.rsi_boost_threshold = soft.get("rsi_boost_threshold", 70)
        self.use_displacement_boost = soft.get("use_displacement_boost", True)
        self.use_counter_momentum = soft.get("use_counter_momentum", True)
        
        # Sizing multipliers
        sizing = gates.get("sizing", {})
        self.low_tier_mult = sizing.get("low_tier", 0.5)
        self.high_tier_mult = sizing.get("high_tier", 1.0)
        
        logger.info(f"ContextFilter initialized: min_rel_vol={self.min_rel_vol}, "
                   f"block_vol_expansion={self.block_vol_expansion}, "
                   f"block_bb_squeeze={self.block_bb_squeeze}")
    
    def evaluate(self, ctx: ContextFeatures, signal_direction: int) -> ContextFilterResult:
        """
        Evaluate context and return trade tier + sizing.
        
        Args:
            ctx: Context features from 1-min bars
            signal_direction: 1 for long, -1 for short
        
        Returns:
            ContextFilterResult with tier, size multiplier, and reasons
        """
        reasons = []
        soft_boosts = []
        
        # === HARD GATES ===
        
        # 1. Volume filter (critical)
        if ctx.rel_vol < self.min_rel_vol:
            reasons.append(f"rel_vol={ctx.rel_vol:.2f} < {self.min_rel_vol}")
            return ContextFilterResult(
                tier=TradeTier.BLOCKED,
                size_multiplier=0.0,
                reasons=reasons
            )
        
        # 2. Volatility expansion (noisy, L2 signals unreliable)
        if self.block_vol_expansion and ctx.vol_expansion:
            reasons.append("vol_expansion=True")
            return ContextFilterResult(
                tier=TradeTier.BLOCKED,
                size_multiplier=0.0,
                reasons=reasons
            )
        
        # 3. BB squeeze (consolidation, wait for breakout)
        if self.block_bb_squeeze and ctx.bb_squeeze:
            reasons.append("bb_squeeze=True")
            return ContextFilterResult(
                tier=TradeTier.BLOCKED,
                size_multiplier=0.0,
                reasons=reasons
            )
        
        # 4. Volatility contraction (optional)
        if self.block_vol_contraction and ctx.vol_contraction:
            reasons.append("vol_contraction=True")
            return ContextFilterResult(
                tier=TradeTier.BLOCKED,
                size_multiplier=0.0,
                reasons=reasons
            )
        
        # === SOFT GATES (for sizing/priority) ===
        boost_count = 0
        
        # 1. RSI > 70 boost (counter-intuitive but profitable for longs)
        if ctx.rsi_14 > self.rsi_boost_threshold:
            soft_boosts.append(f"rsi={ctx.rsi_14:.1f}>70")
            boost_count += 1
        
        # 2. Displacement boost
        if self.use_displacement_boost:
            if signal_direction > 0 and ctx.displacement_up:
                soft_boosts.append("displacement_up")
                boost_count += 1
            elif signal_direction < 0 and ctx.displacement_down:
                soft_boosts.append("displacement_down")
                boost_count += 1
        
        # 3. Counter-momentum boost (L2 detecting reversal)
        if self.use_counter_momentum:
            is_counter = (signal_direction > 0 and ctx.mom_15 < 0) or \
                        (signal_direction < 0 and ctx.mom_15 > 0)
            if is_counter:
                soft_boosts.append(f"counter_mom={ctx.mom_15:.1f}")
                boost_count += 1
        
        # Determine tier based on boosts
        if boost_count >= 2:
            tier = TradeTier.HIGH
            size_mult = self.high_tier_mult
        elif boost_count == 1:
            tier = TradeTier.NORMAL
            size_mult = 1.0
        else:
            tier = TradeTier.LOW
            size_mult = self.low_tier_mult
        
        return ContextFilterResult(
            tier=tier,
            size_multiplier=size_mult,
            reasons=reasons,
            soft_boosts=soft_boosts
        )


class ContextFeatureComputer:
    """Compute context features from 1-minute OHLCV bars"""
    
    def __init__(self, lookback: int = 30):
        self.lookback = lookback
        self._bars: dict[str, list[dict]] = {}  # symbol -> list of bars
        self._current_bar: dict[str, dict] = {}  # symbol -> current building bar
        self._last_bar_minute: dict[str, int] = {}  # symbol -> last completed minute
    
    def update_from_snapshot(self, symbol: str, mid: float, volume: float, timestamp: float) -> None:
        """Build 1-min bars from L2 snapshots"""
        minute = int(timestamp // 60)
        
        # Check if we need to close current bar and start new one
        if symbol in self._last_bar_minute and minute > self._last_bar_minute[symbol]:
            # Close current bar
            if symbol in self._current_bar:
                self._bars.setdefault(symbol, []).append(self._current_bar[symbol])
                if len(self._bars[symbol]) > self.lookback:
                    self._bars[symbol] = self._bars[symbol][-self.lookback:]
            # Start new bar
            self._current_bar[symbol] = {
                "open": mid, "high": mid, "low": mid, "close": mid,
                "volume": volume, "timestamp": timestamp
            }
        elif symbol not in self._current_bar:
            # First bar for symbol
            self._current_bar[symbol] = {
                "open": mid, "high": mid, "low": mid, "close": mid,
                "volume": volume, "timestamp": timestamp
            }
        else:
            # Update current bar
            bar = self._current_bar[symbol]
            bar["high"] = max(bar["high"], mid)
            bar["low"] = min(bar["low"], mid)
            bar["close"] = mid
            bar["volume"] += volume
        
        self._last_bar_minute[symbol] = minute
    
    def update(self, symbol: str, bar: dict) -> None:
        """Add a new 1-min bar for a symbol (direct bar input)"""
        if symbol not in self._bars:
            self._bars[symbol] = []
        
        self._bars[symbol].append(bar)
        if len(self._bars[symbol]) > self.lookback:
            self._bars[symbol] = self._bars[symbol][-self.lookback:]
    
    def compute(self, symbol: str) -> Optional[ContextFeatures]:
        """Compute context features for a symbol"""
        bars = self._bars.get(symbol, [])
        if len(bars) < 20:  # Need minimum bars
            return None
        
        closes = np.array([b["close"] for b in bars])
        volumes = np.array([b["volume"] for b in bars])
        highs = np.array([b["high"] for b in bars])
        lows = np.array([b["low"] for b in bars])
        
        # Relative volume
        vol_ma_20 = volumes[-20:].mean()
        rel_vol = volumes[-1] / (vol_ma_20 + 1) if vol_ma_20 > 0 else 1.0
        
        # RSI(14)
        rsi_14 = self._compute_rsi(closes, 14)
        
        # Volatility regime
        returns = np.diff(closes) / closes[:-1]
        if len(returns) >= 20:
            vol_5 = returns[-5:].std() if len(returns) >= 5 else 0
            vol_20 = returns[-20:].std()
            vol_ratio = vol_5 / (vol_20 + 1e-8)
            vol_expansion = vol_ratio > 1.5
            vol_contraction = vol_ratio < 0.5
        else:
            vol_expansion = False
            vol_contraction = False
        
        # Bollinger squeeze
        if len(closes) >= 20:
            ma_20 = closes[-20:].mean()
            std_20 = closes[-20:].std()
            bb_width = 4 * std_20 / (ma_20 + 1e-8)
            bb_width_ma = np.mean([
                4 * closes[i:i+20].std() / (closes[i:i+20].mean() + 1e-8)
                for i in range(max(0, len(closes)-40), len(closes)-20)
            ]) if len(closes) >= 40 else bb_width
            bb_squeeze = bb_width < bb_width_ma * 0.8
        else:
            bb_squeeze = False
        
        # Displacement
        if len(returns) >= 20:
            ret_std = returns[-20:].std()
            last_ret = returns[-1] if len(returns) > 0 else 0
            displacement_up = last_ret > 2 * ret_std
            displacement_down = last_ret < -2 * ret_std
        else:
            displacement_up = False
            displacement_down = False
        
        # Momentum (15-bar)
        if len(closes) >= 15:
            mom_15 = (closes[-1] / closes[-15] - 1) * 10000  # bps
        else:
            mom_15 = 0.0
        
        return ContextFeatures(
            rel_vol=rel_vol,
            rsi_14=rsi_14,
            vol_expansion=vol_expansion,
            vol_contraction=vol_contraction,
            bb_squeeze=bb_squeeze,
            displacement_up=displacement_up,
            displacement_down=displacement_down,
            mom_15=mom_15
        )
    
    def _compute_rsi(self, closes: np.ndarray, period: int = 14) -> float:
        """Compute RSI"""
        if len(closes) < period + 1:
            return 50.0
        
        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = gains[-period:].mean()
        avg_loss = losses[-period:].mean()
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
