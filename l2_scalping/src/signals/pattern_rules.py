"""L2 Scalping System - Pattern-Based Trading Rules

New rules discovered from L2 pattern analysis (Jan 2026).
These run in parallel with the existing OBI momentum rule.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RuleName(Enum):
    """Trading rule identifiers for attribution."""

    OBI_MOMENTUM = "obi_momentum"  # Original rule
    OBI_DEPTH_COMBO = "obi_depth_combo"  # Rule 1: d_obi_1_30s + high depth
    BID_DEPTH_OBI = "bid_depth_obi"  # Rule 2: depth_bid + d_obi_1_15s
    HIGH_OBI_DEPTH = "high_obi_depth"  # Rule 3: obi_1 + depth_ask
    LARGE_ORDER_SIZE = "large_order_size"  # Rule 4: Large depth signals informed flow
    RESISTANCE_REJECTION = (
        "resistance_rejection"  # Rule 5: Price rejection at resistance levels
    )


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
        if (
            snap.d_obi_1_30s > self.rule1_d_obi_30s_thresh
            and snap.depth_ask > self.rule1_depth_ask_thresh
        ):

            # Strength based on how far above thresholds
            obi_excess = (snap.d_obi_1_30s - self.rule1_d_obi_30s_thresh) / 0.3
            depth_excess = (snap.depth_ask - self.rule1_depth_ask_thresh) / 25000
            strength = min(1.0, (obi_excess + depth_excess) / 2)

            return RuleSignal(
                rule_name=RuleName.OBI_DEPTH_COMBO,
                direction=1,  # Long
                strength=strength,
                confidence=0.75,  # Based on 3.00x lift
                reason=f"d_obi_30s={snap.d_obi_1_30s:.3f}, depth_ask={snap.depth_ask:.0f}",
            )

        # Check short signal (inverse)
        if (
            snap.d_obi_1_30s < -self.rule1_d_obi_30s_thresh
            and snap.depth_bid > self.rule1_depth_ask_thresh
        ):

            obi_excess = (-snap.d_obi_1_30s - self.rule1_d_obi_30s_thresh) / 0.3
            depth_excess = (snap.depth_bid - self.rule1_depth_ask_thresh) / 25000
            strength = min(1.0, (obi_excess + depth_excess) / 2)

            return RuleSignal(
                rule_name=RuleName.OBI_DEPTH_COMBO,
                direction=-1,  # Short
                strength=strength,
                confidence=0.75,
                reason=f"d_obi_30s={snap.d_obi_1_30s:.3f}, depth_bid={snap.depth_bid:.0f}",
            )

        return RuleSignal(RuleName.OBI_DEPTH_COMBO, 0, 0.0, 0.0, "no_signal")

    def _rule2_bid_depth_obi(self, snap: ExtendedL2Snapshot) -> RuleSignal:
        """
        Rule 2: Bid depth + OBI change (lift=2.59x)
        Entry: depth_bid > 20000 AND d_obi_1_15s > 0.1
        """
        if (
            snap.depth_bid > self.rule2_depth_bid_thresh
            and snap.d_obi_1_15s > self.rule2_d_obi_15s_thresh
        ):

            depth_excess = (snap.depth_bid - self.rule2_depth_bid_thresh) / 20000
            obi_excess = (snap.d_obi_1_15s - self.rule2_d_obi_15s_thresh) / 0.2
            strength = min(1.0, (depth_excess + obi_excess) / 2)

            return RuleSignal(
                rule_name=RuleName.BID_DEPTH_OBI,
                direction=1,  # Long
                strength=strength,
                confidence=0.65,  # Based on 2.59x lift
                reason=f"depth_bid={snap.depth_bid:.0f}, d_obi_15s={snap.d_obi_1_15s:.3f}",
            )

        # Check short signal (inverse)
        if (
            snap.depth_ask > self.rule2_depth_bid_thresh
            and snap.d_obi_1_15s < -self.rule2_d_obi_15s_thresh
        ):

            depth_excess = (snap.depth_ask - self.rule2_depth_bid_thresh) / 20000
            obi_excess = (-snap.d_obi_1_15s - self.rule2_d_obi_15s_thresh) / 0.2
            strength = min(1.0, (depth_excess + obi_excess) / 2)

            return RuleSignal(
                rule_name=RuleName.BID_DEPTH_OBI,
                direction=-1,  # Short
                strength=strength,
                confidence=0.65,
                reason=f"depth_ask={snap.depth_ask:.0f}, d_obi_15s={snap.d_obi_1_15s:.3f}",
            )

        return RuleSignal(RuleName.BID_DEPTH_OBI, 0, 0.0, 0.0, "no_signal")

    def _rule3_high_obi_depth(self, snap: ExtendedL2Snapshot) -> RuleSignal:
        """
        Rule 3: High OBI + depth (lift=2.29x)
        Entry: obi_1 > 0.1 AND depth_ask > 30000
        """
        if (
            snap.obi_1 > self.rule3_obi_1_thresh
            and snap.depth_ask > self.rule3_depth_ask_thresh
        ):

            obi_excess = (snap.obi_1 - self.rule3_obi_1_thresh) / 0.3
            depth_excess = (snap.depth_ask - self.rule3_depth_ask_thresh) / 30000
            strength = min(1.0, (obi_excess + depth_excess) / 2)

            return RuleSignal(
                rule_name=RuleName.HIGH_OBI_DEPTH,
                direction=1,  # Long
                strength=strength,
                confidence=0.60,  # Based on 2.29x lift
                reason=f"obi_1={snap.obi_1:.3f}, depth_ask={snap.depth_ask:.0f}",
            )

        # Check short signal (inverse)
        if (
            snap.obi_1 < -self.rule3_obi_1_thresh
            and snap.depth_bid > self.rule3_depth_ask_thresh
        ):

            obi_excess = (-snap.obi_1 - self.rule3_obi_1_thresh) / 0.3
            depth_excess = (snap.depth_bid - self.rule3_depth_ask_thresh) / 30000
            strength = min(1.0, (obi_excess + depth_excess) / 2)

            return RuleSignal(
                rule_name=RuleName.HIGH_OBI_DEPTH,
                direction=-1,  # Short
                strength=strength,
                confidence=0.60,
                reason=f"obi_1={snap.obi_1:.3f}, depth_bid={snap.depth_bid:.0f}",
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
        self._history: dict[str, list[tuple[float, float, float]]] = (
            {}
        )  # symbol -> [(ts, obi_1, mid)]
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

    def _get_delta(
        self, symbol: str, timestamp: float, window_sec: int, field: str
    ) -> float:
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
        pressure: float,
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
            d_mid_30s=d_mid_30s,
        )

    def generate_pattern_signals(
        self, snapshot: ExtendedL2Snapshot
    ) -> list[RuleSignal]:
        """Generate signals from all pattern rules."""
        return self.pattern_rules.evaluate_all(snapshot)


class SizeSignalGenerator:
    """
    Large order size signal generator.

    Detects when depth exceeds dynamic percentile threshold (per-symbol).
    Large bid depth → LONG signal (informed buying)
    Large ask depth → SHORT signal (informed selling)

    Uses rolling percentile to adapt to each symbol's typical depth.
    """

    # Rough depth multiplier by price tier (empirical estimate)
    # Higher priced stocks tend to have larger dollar depth
    PRICE_DEPTH_MULTIPLIER = {
        5: 1.0,  # $0-5: baseline
        10: 1.5,  # $5-10
        25: 2.5,  # $10-25
        50: 4.0,  # $25-50
        100: 6.0,  # $50-100
        float("inf"): 10.0,  # $100+
    }

    def __init__(self, config: dict):
        self.config = config
        size_cfg = config.get("size_signal", {})

        self.enabled = size_cfg.get("enabled", True)
        self.percentile = size_cfg.get("percentile", 90)  # Dynamic threshold
        self.min_depth_k = size_cfg.get("min_depth_k", 10)  # Minimum $10k absolute
        self.warmup_depth_k = size_cfg.get(
            "warmup_depth_k", 25
        )  # Warmup threshold $25k
        self.lookback = size_cfg.get("lookback", 300)  # 5 min rolling window
        self.cooldown_sec = size_cfg.get("cooldown_sec", 30)  # Min time between signals
        self.warmup_samples = size_cfg.get("warmup_samples", 120)  # ~2 min warmup

        # Per-symbol rolling depth history: symbol -> list[(ts, depth_bid, depth_ask)]
        self._depth_history: dict[str, list[tuple[float, float, float]]] = {}
        # Per-symbol last signal time
        self._last_signal: dict[str, float] = {}
        # Per-symbol last known price (for warmup estimation)
        self._last_price: dict[str, float] = {}

    def _update_history(
        self, symbol: str, ts: float, depth_bid: float, depth_ask: float
    ):
        """Update rolling depth history."""
        if symbol not in self._depth_history:
            self._depth_history[symbol] = []

        self._depth_history[symbol].append((ts, depth_bid, depth_ask))

        # Trim to lookback window
        cutoff = ts - self.lookback
        self._depth_history[symbol] = [
            (t, db, da) for t, db, da in self._depth_history[symbol] if t >= cutoff
        ]

    def _get_price_multiplier(self, price: float) -> float:
        """Get depth multiplier based on price tier."""
        for tier, mult in self.PRICE_DEPTH_MULTIPLIER.items():
            if price <= tier:
                return mult
        return 10.0

    def _get_warmup_threshold(self, symbol: str) -> float:
        """Get threshold during warmup period based on price estimate."""
        price = self._last_price.get(symbol, 10.0)  # Default $10 if unknown
        multiplier = self._get_price_multiplier(price)
        return self.warmup_depth_k * 1000 * multiplier

    def _is_in_warmup(self, symbol: str) -> bool:
        """Check if symbol is still in warmup period."""
        return (
            symbol not in self._depth_history
            or len(self._depth_history[symbol]) < self.warmup_samples
        )

    def _get_percentile_threshold(self, symbol: str, side: str) -> float | None:
        """Get dynamic percentile threshold for symbol. Returns None if in warmup."""
        if self._is_in_warmup(symbol):
            return None

        idx = 1 if side == "bid" else 2
        depths = [h[idx] for h in self._depth_history[symbol]]
        return float(sorted(depths)[int(len(depths) * self.percentile / 100)])

    def generate_signal(
        self,
        symbol: str,
        timestamp: float,
        depth_bid: float,
        depth_ask: float,
        mid_price: float = None,
    ) -> Optional[RuleSignal]:
        """
        Generate size signal if depth exceeds dynamic threshold.

        Args:
            symbol: Ticker symbol
            timestamp: Current timestamp
            depth_bid: Total bid depth in dollars
            depth_ask: Total ask depth in dollars
            mid_price: Current mid price (for warmup estimation)

        Returns RuleSignal or None.
        """
        if not self.enabled:
            return None

        # Track price for warmup estimation
        if mid_price is not None:
            self._last_price[symbol] = mid_price

        # Update history
        self._update_history(symbol, timestamp, depth_bid, depth_ask)

        # Check cooldown
        last = self._last_signal.get(symbol, 0)
        if timestamp - last < self.cooldown_sec:
            return None

        # Determine thresholds based on warmup state
        in_warmup = self._is_in_warmup(symbol)

        if in_warmup:
            # During warmup: use price-adjusted absolute threshold
            warmup_thresh = self._get_warmup_threshold(symbol)
            bid_thresh = max(warmup_thresh, self.min_depth_k * 1000)
            ask_thresh = bid_thresh
            thresh_desc = f"warmup ${bid_thresh/1000:.0f}k"
        else:
            # After warmup: use dynamic percentile
            bid_thresh = self._get_percentile_threshold(symbol, "bid")
            ask_thresh = self._get_percentile_threshold(symbol, "ask")
            # Apply minimum absolute threshold
            min_thresh = self.min_depth_k * 1000
            bid_thresh = max(bid_thresh, min_thresh)
            ask_thresh = max(ask_thresh, min_thresh)
            thresh_desc = f"{self.percentile}th pct"

        # Check for large bid (LONG signal)
        if depth_bid >= bid_thresh:
            self._last_signal[symbol] = timestamp
            excess = (depth_bid - bid_thresh) / bid_thresh
            strength = min(1.0, 0.5 + excess)
            # Lower confidence during warmup
            confidence = 0.55 if in_warmup else 0.70
            return RuleSignal(
                rule_name=RuleName.LARGE_ORDER_SIZE,
                direction=1,
                strength=strength,
                confidence=confidence,
                reason=f"large_bid={depth_bid/1000:.1f}k >= {bid_thresh/1000:.1f}k ({thresh_desc})",
            )

        # Check for large ask (SHORT signal)
        if depth_ask >= ask_thresh:
            self._last_signal[symbol] = timestamp
            excess = (depth_ask - ask_thresh) / ask_thresh
            strength = min(1.0, 0.5 + excess)
            confidence = 0.55 if in_warmup else 0.70
            return RuleSignal(
                rule_name=RuleName.LARGE_ORDER_SIZE,
                direction=-1,
                strength=strength,
                confidence=confidence,
                reason=f"large_ask={depth_ask/1000:.1f}k >= {ask_thresh/1000:.1f}k ({thresh_desc})",
            )

        return None


@dataclass
class Touch:
    """Record of price touching a level."""

    timestamp: float
    price: float
    depth_ask: float
    had_large_order: bool


@dataclass
class ResistanceLevel:
    """Qualified resistance level with institutional activity."""

    price: float
    touches: list[Touch]
    large_order_ratio: float
    last_touch_time: float
    last_signal_time: float = 0.0

    def is_hot(self, current_time: float, window_sec: int = 3600) -> bool:
        """Check if level has recent activity."""
        recent = [t for t in self.touches if current_time - t.timestamp < window_sec]
        return len(recent) >= 3


class ResistanceSignalGenerator:
    """
    Resistance rejection signal generator.

    Detects institutional distribution zones where price consistently
    rejects with large ask orders. SHORT only (support levels don't work).

    Expected: +12 bps @ 300s, 5-20 signals/day (AAA quality)
    """

    def __init__(self, config: dict):
        self.config = config
        res_cfg = config.get("resistance_signal", {})

        self.enabled = res_cfg.get("enabled", False)
        self.min_touches = res_cfg.get("min_touches", 20)
        self.min_large_order_ratio = res_cfg.get("min_large_order_ratio", 0.5)
        self.min_recent_touches = res_cfg.get("min_recent_touches", 3)
        self.price_tolerance = res_cfg.get("price_tolerance", 0.005)
        self.approach_tolerance = res_cfg.get("approach_tolerance", 0.002)
        self.min_imbalance = res_cfg.get("min_imbalance", -0.2)
        self.cooldown_sec = res_cfg.get("cooldown_sec", 300)
        self.tod_filter = res_cfg.get("tod_filter", "closing")
        self.lookback_hours = res_cfg.get("lookback_hours", 4)

        # Per-symbol price history: symbol -> list[Touch]
        self._price_history: dict[str, list[Touch]] = {}
        # Per-symbol detected levels: symbol -> list[ResistanceLevel]
        self._levels: dict[str, list[ResistanceLevel]] = {}
        # Last level detection time
        self._last_detection: dict[str, float] = {}

    def _update_history(
        self,
        symbol: str,
        timestamp: float,
        price: float,
        depth_ask: float,
        large_order_threshold: float,
    ):
        """Update price history with new touch."""
        if symbol not in self._price_history:
            self._price_history[symbol] = []

        touch = Touch(
            timestamp=timestamp,
            price=price,
            depth_ask=depth_ask,
            had_large_order=(depth_ask >= large_order_threshold),
        )
        self._price_history[symbol].append(touch)

        # Trim to lookback window
        cutoff = timestamp - (self.lookback_hours * 3600)
        self._price_history[symbol] = [
            t for t in self._price_history[symbol] if t.timestamp >= cutoff
        ]

    def _detect_levels(self, symbol: str, current_time: float) -> list[ResistanceLevel]:
        """Detect qualified resistance levels from price history."""
        if symbol not in self._price_history:
            return []

        history = self._price_history[symbol]
        if len(history) < self.min_touches:
            return []

        # Cluster prices into levels
        levels = []
        used = set()

        for i, touch in enumerate(history):
            if i in used:
                continue

            # Find all touches within tolerance of this price
            cluster = [touch]
            used.add(i)

            for j, other in enumerate(history):
                if j in used:
                    continue
                if abs(other.price - touch.price) / touch.price <= self.price_tolerance:
                    cluster.append(other)
                    used.add(j)

            # Check if cluster qualifies as resistance level
            if len(cluster) >= self.min_touches:
                large_orders = sum(1 for t in cluster if t.had_large_order)
                ratio = large_orders / len(cluster)

                if ratio >= self.min_large_order_ratio:
                    avg_price = sum(t.price for t in cluster) / len(cluster)
                    level = ResistanceLevel(
                        price=avg_price,
                        touches=cluster,
                        large_order_ratio=ratio,
                        last_touch_time=max(t.timestamp for t in cluster),
                    )

                    # Check if level is "hot" (recent activity)
                    if level.is_hot(current_time, window_sec=3600):
                        levels.append(level)

        return levels

    def _is_closing_session(self, timestamp: float) -> bool:
        """Check if current time is in closing session (15:30-16:00 ET)."""
        from datetime import datetime
        from zoneinfo import ZoneInfo

        dt = datetime.fromtimestamp(timestamp, tz=ZoneInfo("America/New_York"))
        hour = dt.hour + dt.minute / 60.0
        return 15.5 <= hour < 16.0

    def generate_signal(
        self,
        symbol: str,
        timestamp: float,
        price: float,
        depth_ask: float,
        depth_imbalance: float,
        large_order_threshold: float,
    ) -> Optional[RuleSignal]:
        """
        Generate resistance rejection signal.

        Returns signal only if ALL AAA criteria met.
        """
        if not self.enabled:
            return None

        # Update history
        self._update_history(symbol, timestamp, price, depth_ask, large_order_threshold)

        # Detect levels periodically (every 60 seconds)
        last_detect = self._last_detection.get(symbol, 0)
        if timestamp - last_detect >= 60:
            self._levels[symbol] = self._detect_levels(symbol, timestamp)
            self._last_detection[symbol] = timestamp

        # Get current levels
        levels = self._levels.get(symbol, [])
        if not levels:
            return None

        # Check time-of-day filter
        if self.tod_filter == "closing" and not self._is_closing_session(timestamp):
            return None

        # Find level being approached (within tolerance below)
        approaching_level = None
        for level in levels:
            distance = (level.price - price) / price
            if 0 < distance <= self.approach_tolerance:  # Approaching from below
                approaching_level = level
                break

        if not approaching_level:
            return None

        # Check cooldown
        if timestamp - approaching_level.last_signal_time < self.cooldown_sec:
            return None

        # Check large order present NOW
        if depth_ask < large_order_threshold:
            return None

        # Check imbalance confirmation (ask-heavy)
        if depth_imbalance >= self.min_imbalance:
            return None

        # All AAA criteria met
        approaching_level.last_signal_time = timestamp

        return RuleSignal(
            rule_name=RuleName.RESISTANCE_REJECTION,
            direction=-1,  # SHORT only
            strength=1.0,
            confidence=0.90,  # AAA quality
            reason=f"resistance@{approaching_level.price:.2f} ({len(approaching_level.touches)} touches, {approaching_level.large_order_ratio:.0%} large orders)",
        )
