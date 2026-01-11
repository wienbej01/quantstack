"""L2 Scalping System - Pattern-Based Trading Rules

New rules discovered from L2 pattern analysis (Jan 2026).
These run in parallel with the existing OBI momentum rule.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RuleName(Enum):
    """Trading rule identifiers for attribution."""
    OBI_MOMENTUM = "obi_momentum"           # Original rule
    OBI_DEPTH_COMBO = "obi_depth_combo"     # Rule 1: d_obi_1_30s + high depth
    BID_DEPTH_OBI = "bid_depth_obi"         # Rule 2: depth_bid + d_obi_1_15s
    HIGH_OBI_DEPTH = "high_obi_depth"       # Rule 3: obi_1 + depth_ask


@dataclass
class RuleSignal:
    """Signal from a specific trading rule."""
    rule_name: RuleName
    direction: int  # 1=long, -1=short, 0=none
    strength: float  # 0.0 to 1.0
    confidence: float  # 0.0 to 1.0
    reason: str


@dataclass
class ExtendedL2Snapshot:
    """Extended L2 snapshot with delta features for new rules."""
    symbol: str
    timestamp: float
    mid: float
    spread: float
    obi_1: float
    obi_5: float
    depth_bid: float
    depth_ask: float
    pressure: float
    # Delta features (new)
    d_obi_1_5s: float = 0.0
    d_obi_1_15s: float = 0.0
    d_obi_1_30s: float = 0.0
    d_mid_5s: float = 0.0
    d_mid_30s: float = 0.0


class PatternRules:
    """
    Pattern-based trading rules from L2 analysis.
    
    Rules discovered from 134k L2 snapshots with 5-min forward momentum target:
    - Rule 1: d_obi_1_30s > 0.2 AND depth_ask > 25000 (lift=3.00x)
    - Rule 2: depth_bid > 20000 AND d_obi_1_15s > 0.1 (lift=2.59x)
    - Rule 3: obi_1 > 0.1 AND depth_ask > 30000 (lift=2.29x)
    """
    
    def __init__(self, config: dict):
        self.config = config
        rules_cfg = config.get("pattern_rules", {})
        
        # Rule 1: OBI momentum + depth (strongest signal)
        self.rule1_d_obi_30s_thresh = rules_cfg.get("rule1_d_obi_30s", 0.2)
        self.rule1_depth_ask_thresh = rules_cfg.get("rule1_depth_ask", 25000)
        
        # Rule 2: Bid depth + OBI change
        self.rule2_depth_bid_thresh = rules_cfg.get("rule2_depth_bid", 20000)
        self.rule2_d_obi_15s_thresh = rules_cfg.get("rule2_d_obi_15s", 0.1)
        
        # Rule 3: High OBI + depth
        self.rule3_obi_1_thresh = rules_cfg.get("rule3_obi_1", 0.1)
        self.rule3_depth_ask_thresh = rules_cfg.get("rule3_depth_ask", 30000)
        
        # Enable/disable individual rules
        self.rule1_enabled = rules_cfg.get("rule1_enabled", True)
        self.rule2_enabled = rules_cfg.get("rule2_enabled", True)
        self.rule3_enabled = rules_cfg.get("rule3_enabled", True)
    
    def evaluate_all(self, snapshot: ExtendedL2Snapshot) -> list[RuleSignal]:
        """Evaluate all pattern rules and return triggered signals."""
        signals = []
        
        if self.rule1_enabled:
            sig = self._rule1_obi_depth_combo(snapshot)
            if sig.direction != 0:
                signals.append(sig)
        
        if self.rule2_enabled:
            sig = self._rule2_bid_depth_obi(snapshot)
            if sig.direction != 0:
                signals.append(sig)
        
        if self.rule3_enabled:
            sig = self._rule3_high_obi_depth(snapshot)
            if sig.direction != 0:
                signals.append(sig)
        
        return signals
    
    def _rule1_obi_depth_combo(self, snap: ExtendedL2Snapshot) -> RuleSignal:
        """
        Rule 1: OBI momentum + high depth (lift=3.00x)
        Entry: d_obi_1_30s > 0.2 AND depth_ask > 25000
        """
        if (snap.d_obi_1_30s > self.rule1_d_obi_30s_thresh and 
            snap.depth_ask > self.rule1_depth_ask_thresh):
            
            # Strength based on how far above thresholds
            obi_excess = (snap.d_obi_1_30s - self.rule1_d_obi_30s_thresh) / 0.3
            depth_excess = (snap.depth_ask - self.rule1_depth_ask_thresh) / 25000
            strength = min(1.0, (obi_excess + depth_excess) / 2)
            
            return RuleSignal(
                rule_name=RuleName.OBI_DEPTH_COMBO,
                direction=1,  # Long
                strength=strength,
                confidence=0.75,  # Based on 3.00x lift
                reason=f"d_obi_30s={snap.d_obi_1_30s:.3f}, depth_ask={snap.depth_ask:.0f}"
            )
        
        # Check short signal (inverse)
        if (snap.d_obi_1_30s < -self.rule1_d_obi_30s_thresh and 
            snap.depth_bid > self.rule1_depth_ask_thresh):
            
            obi_excess = (-snap.d_obi_1_30s - self.rule1_d_obi_30s_thresh) / 0.3
            depth_excess = (snap.depth_bid - self.rule1_depth_ask_thresh) / 25000
            strength = min(1.0, (obi_excess + depth_excess) / 2)
            
            return RuleSignal(
                rule_name=RuleName.OBI_DEPTH_COMBO,
                direction=-1,  # Short
                strength=strength,
                confidence=0.75,
                reason=f"d_obi_30s={snap.d_obi_1_30s:.3f}, depth_bid={snap.depth_bid:.0f}"
            )
        
        return RuleSignal(RuleName.OBI_DEPTH_COMBO, 0, 0.0, 0.0, "no_signal")
    
    def _rule2_bid_depth_obi(self, snap: ExtendedL2Snapshot) -> RuleSignal:
        """
        Rule 2: Bid depth + OBI change (lift=2.59x)
        Entry: depth_bid > 20000 AND d_obi_1_15s > 0.1
        """
        if (snap.depth_bid > self.rule2_depth_bid_thresh and 
            snap.d_obi_1_15s > self.rule2_d_obi_15s_thresh):
            
            depth_excess = (snap.depth_bid - self.rule2_depth_bid_thresh) / 20000
            obi_excess = (snap.d_obi_1_15s - self.rule2_d_obi_15s_thresh) / 0.2
            strength = min(1.0, (depth_excess + obi_excess) / 2)
            
            return RuleSignal(
                rule_name=RuleName.BID_DEPTH_OBI,
                direction=1,  # Long
                strength=strength,
                confidence=0.65,  # Based on 2.59x lift
                reason=f"depth_bid={snap.depth_bid:.0f}, d_obi_15s={snap.d_obi_1_15s:.3f}"
            )
        
        # Check short signal (inverse)
        if (snap.depth_ask > self.rule2_depth_bid_thresh and 
            snap.d_obi_1_15s < -self.rule2_d_obi_15s_thresh):
            
            depth_excess = (snap.depth_ask - self.rule2_depth_bid_thresh) / 20000
            obi_excess = (-snap.d_obi_1_15s - self.rule2_d_obi_15s_thresh) / 0.2
            strength = min(1.0, (depth_excess + obi_excess) / 2)
            
            return RuleSignal(
                rule_name=RuleName.BID_DEPTH_OBI,
                direction=-1,  # Short
                strength=strength,
                confidence=0.65,
                reason=f"depth_ask={snap.depth_ask:.0f}, d_obi_15s={snap.d_obi_1_15s:.3f}"
            )
        
        return RuleSignal(RuleName.BID_DEPTH_OBI, 0, 0.0, 0.0, "no_signal")
    
    def _rule3_high_obi_depth(self, snap: ExtendedL2Snapshot) -> RuleSignal:
        """
        Rule 3: High OBI + depth (lift=2.29x)
        Entry: obi_1 > 0.1 AND depth_ask > 30000
        """
        if (snap.obi_1 > self.rule3_obi_1_thresh and 
            snap.depth_ask > self.rule3_depth_ask_thresh):
            
            obi_excess = (snap.obi_1 - self.rule3_obi_1_thresh) / 0.3
            depth_excess = (snap.depth_ask - self.rule3_depth_ask_thresh) / 30000
            strength = min(1.0, (obi_excess + depth_excess) / 2)
            
            return RuleSignal(
                rule_name=RuleName.HIGH_OBI_DEPTH,
                direction=1,  # Long
                strength=strength,
                confidence=0.60,  # Based on 2.29x lift
                reason=f"obi_1={snap.obi_1:.3f}, depth_ask={snap.depth_ask:.0f}"
            )
        
        # Check short signal (inverse)
        if (snap.obi_1 < -self.rule3_obi_1_thresh and 
            snap.depth_bid > self.rule3_depth_ask_thresh):
            
            obi_excess = (-snap.obi_1 - self.rule3_obi_1_thresh) / 0.3
            depth_excess = (snap.depth_bid - self.rule3_depth_ask_thresh) / 30000
            strength = min(1.0, (obi_excess + depth_excess) / 2)
            
            return RuleSignal(
                rule_name=RuleName.HIGH_OBI_DEPTH,
                direction=-1,  # Short
                strength=strength,
                confidence=0.60,
                reason=f"obi_1={snap.obi_1:.3f}, depth_bid={snap.depth_bid:.0f}"
            )
        
        return RuleSignal(RuleName.HIGH_OBI_DEPTH, 0, 0.0, 0.0, "no_signal")


class MultiRuleSignalGenerator:
    """
    Signal generator that combines original OBI rule with new pattern rules.
    Each rule generates independent signals with rule attribution.
    """
    
    def __init__(self, config: dict):
        self.config = config
        self.pattern_rules = PatternRules(config)
        
        # Delta history for computing d_obi features
        self._history: dict[str, list[tuple[float, float, float]]] = {}  # symbol -> [(ts, obi_1, mid)]
        self._history_max = 120  # 2 minutes at 1/sec
    
    def update_history(self, symbol: str, timestamp: float, obi_1: float, mid: float):
        """Update history for delta computation."""
        if symbol not in self._history:
            self._history[symbol] = []
        
        self._history[symbol].append((timestamp, obi_1, mid))
        
        # Trim old history
        cutoff = timestamp - 120
        self._history[symbol] = [
            (ts, obi, m) for ts, obi, m in self._history[symbol] if ts >= cutoff
        ]
    
    def _get_delta(self, symbol: str, timestamp: float, window_sec: int, field: str) -> float:
        """Get delta value for a field over a time window."""
        if symbol not in self._history:
            return 0.0
        
        target_ts = timestamp - window_sec
        hist = self._history[symbol]
        
        # Find closest historical point
        for ts, obi, mid in reversed(hist):
            if ts <= target_ts:
                if field == "obi_1":
                    current_obi = hist[-1][1] if hist else 0.0
                    return current_obi - obi
                elif field == "mid":
                    current_mid = hist[-1][2] if hist else 0.0
                    return current_mid - mid
        
        return 0.0
    
    def create_extended_snapshot(
        self, 
        symbol: str,
        timestamp: float,
        mid: float,
        spread: float,
        obi_1: float,
        obi_5: float,
        depth_bid: float,
        depth_ask: float,
        pressure: float
    ) -> ExtendedL2Snapshot:
        """Create extended snapshot with delta features."""
        
        # Update history
        self.update_history(symbol, timestamp, obi_1, mid)
        
        # Compute deltas
        d_obi_1_5s = self._get_delta(symbol, timestamp, 5, "obi_1")
        d_obi_1_15s = self._get_delta(symbol, timestamp, 15, "obi_1")
        d_obi_1_30s = self._get_delta(symbol, timestamp, 30, "obi_1")
        d_mid_5s = self._get_delta(symbol, timestamp, 5, "mid")
        d_mid_30s = self._get_delta(symbol, timestamp, 30, "mid")
        
        return ExtendedL2Snapshot(
            symbol=symbol,
            timestamp=timestamp,
            mid=mid,
            spread=spread,
            obi_1=obi_1,
            obi_5=obi_5,
            depth_bid=depth_bid,
            depth_ask=depth_ask,
            pressure=pressure,
            d_obi_1_5s=d_obi_1_5s,
            d_obi_1_15s=d_obi_1_15s,
            d_obi_1_30s=d_obi_1_30s,
            d_mid_5s=d_mid_5s,
            d_mid_30s=d_mid_30s
        )
    
    def generate_pattern_signals(self, snapshot: ExtendedL2Snapshot) -> list[RuleSignal]:
        """Generate signals from all pattern rules."""
        return self.pattern_rules.evaluate_all(snapshot)
