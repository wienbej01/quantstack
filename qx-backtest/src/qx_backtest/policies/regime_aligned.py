"""Regime-aligned trading policies with enhanced features.

This module implements the four main regime-aligned strategies:
1. AVWAP Momentum - FVG continuation and pullback reclaim
2. AVWAP Pullback - Deep pullbacks to session AVWAP with reclamation
3. Value Rotation - Value area rotation and liquidity sweep reversions
4. Stress Micro-Scalp - Optional high-risk scalp during stress contractions
"""

from dataclasses import dataclass
from typing import Any

import pandas as pd

from qx_core.schemas import RegimeType

from ..order import MarketOrder, OrderSide, OrderType
from ..risk import ATRStopManager
from .base import Policy


@dataclass
class PolicyParameters:
    """Base parameters for regime-aligned policies."""

    # Risk parameters
    atr_stop_multiple: float = 1.0
    atr_target_multiple: float = 1.5  # increase target multiple from 0.8
    atr_trailing_multiple: float = 1.0
    max_position_size: float = 1.0
    timeout_bars: int = 60

    # Entry thresholds
    min_risk_reward: float = 0.5  # lower from 1.5 to allow ~0.5 RR trades
    min_atr_value: float = 0.005  # lower from 0.01 so low-volatility bars pass

    # Regime gating
    enabled_regimes: list[RegimeType] = None

    def __post_init__(self):
        if self.enabled_regimes is None:
            self.enabled_regimes = [RegimeType.BULL, RegimeType.BEAR]


@dataclass
class MomentumParameters(PolicyParameters):
    """Parameters for AVWAP Momentum strategy."""

    # Regime thresholds
    bull_vr_min: float = 1.2
    bull_adx_min: float = 25.0
    bull_vol_range: tuple[float, float] = (0.8, 1.6)
    bear_vr_max: float = 0.8
    bear_adx_min: float = 25.0
    bear_vol_range: tuple[float, float] = (0.8, 1.6)

    # Entry conditions
    avwap_bias_threshold: float = 0.0035  # 0.35% AVWAP bias
    avwap_tolerance: float = (
        0.001  # tolerance for AVWAP deviation (0 = no extra tolerance)
    )
    discount_pd_range: tuple[float, float] = (0.62, 0.79)  # Discount PD array
    premium_pd_range: tuple[float, float] = (0.62, 0.79)  # Premium PD array
    fvg_max_distance: float = 5.0  # Max ATR distance to FVG (loosened from 0.5)

    # Confirmation requirements
    require_absorption: bool = False
    require_displacement: bool = False
    require_fvg: bool = False  # Make FVG checks optional
    ofi_trend_min: float = 0.0  # no positivity/negativity requirement

    def __post_init__(self):
        super().__post_init__()
        self.enabled_regimes = [RegimeType.BULL, RegimeType.BEAR]


class AVWAPMomentumPolicy(Policy):
    """AVWAP Momentum strategy with FVG continuation and pullback reclaim setups.

    BULL Regime:
    - Price above session & first-hour AVWAP
    - Bullish displacement leg active
    - Pullback tags active bullish FVG within discount PD (62-79%)
    - OFI trend positive, no bearish sweep overhang
    - Optional absorption confirmation

    BEAR Regime:
    - Mirror of BULL conditions with bearish setups
    """

    def __init__(self, params: MomentumParameters | None = None):
        super().__init__("AVWAP_Momentum")
        self.params = params or MomentumParameters()
        self.atr_stop_manager = ATRStopManager()
        self.stop_manager = self.atr_stop_manager

        # Trade tracking
        self.active_orders: dict[str, dict] = {}
        self.trade_log: list[dict] = []

        # DEBUG: Gate rejection tracking
        self._rejection_counts = {
            "regime_gating": 0,
            "warmup": 0,
            "avwap_position": 0,
            "fvg_setup": 0,
            "ofi_trend": 0,
            "sweep_overhang": 0,
            "absorption": 0,
            "displacement": 0,
            "atr_too_low": 0,
            "risk_reward": 0,
            "total_entry_checks": 0,
        }
        self._total_bars_processed = 0

    def process_bar(self, bar: dict[str, Any]) -> None:
        """Process bar and generate trading signals."""
        try:
            self._total_bars_processed += 1

            # Check regime gating
            if not self._check_regime_gating(bar):
                return

            # Check warmup
            if not self._check_warmup(bar):
                return

            current_regime = bar.get("f__regime__current", RegimeType.OFF)

            # Get position
            position = self.get_position(bar["symbol"])

            # INTRADAY RULE: Force close all positions at market close (15:55 ET)
            if self._is_market_close(bar) and position and position.quantity != 0:
                self._close_position(bar, position, "End of day")
                return

            # Exit logic for existing positions
            if position and position.quantity != 0:
                self._manage_position(bar, position)
                return

            # If position is closed, remove from active_orders before checking for new entries.
            if bar["symbol"] in self.active_orders:
                del self.active_orders[bar["symbol"]]

            # Entry logic
            if current_regime == RegimeType.BULL:
                self._check_bull_entry(bar)
            elif current_regime == RegimeType.BEAR:
                self._check_bear_entry(bar)
        except Exception as e:
            print(f"[DEBUG] AVWAPMomentumPolicy.process_bar Exception: {e}")
            print(f"[DEBUG] Problematic bar: {bar}")
            raise e

    def _check_regime_gating(self, bar: dict[str, Any]) -> bool:
        """Check if strategy is allowed under current regime."""
        if not self.is_allowed():
            self._rejection_counts["regime_gating"] += 1
            return False

        current_regime = bar.get("f__regime__current", RegimeType.OFF)
        if current_regime not in self.params.enabled_regimes:
            self._rejection_counts["regime_gating"] += 1
            return False
        return True

    def _check_warmup(self, bar: dict[str, Any]) -> bool:
        """Check if features are warmed up."""
        warmup_ok = bar.get("f__warmup_ok", False)
        if not warmup_ok:
            self._rejection_counts["warmup"] += 1
        return warmup_ok

    def _is_market_close(self, bar: dict[str, Any]) -> bool:
        """Check if current bar is at or near market close (15:55 ET)."""
        import pandas as pd

        ts = bar["ts"]
        # Convert to ET timezone
        dt_et = pd.Timestamp(ts, unit="ns", tz="UTC").tz_convert("America/New_York")
        is_close = dt_et.hour == 15 and dt_et.minute >= 55
        return is_close

    def _check_bull_entry(self, bar: dict[str, Any]) -> None:
        """Check for BULL regime entry conditions."""
        self._rejection_counts["total_entry_checks"] += 1

        # Must be above key AVWAP levels (with tolerance band)
        tolerance = (
            self.params.avwap_tolerance
        )  # use parameter instead of hardcoded 0.001
        session_avwap = bar.get("f__anchor__session_avwap", 0)
        first_hour_avwap = bar.get("f__anchor__first_hour_avwap", 0)

        session_ok = (
            (bar["close"] - session_avwap) / bar["close"] > tolerance
            if session_avwap > 0
            else True
        )
        first_hour_ok = (
            (bar["close"] - first_hour_avwap) / bar["close"] > tolerance
            if first_hour_avwap > 0
            else True
        )

        if not (session_ok and first_hour_ok):
            self._rejection_counts["avwap_position"] += 1
            return

        # NOTE: Regime strength validation removed - trust regime detector's classification
        # The regime detector already validated VR, ADX, and volatility before classifying as BULL

        # NOTE: ICT discount zone check made optional
        # The f__ict__in_discount feature is often False due to missing session highs/lows

        # Active bullish FVG within acceptable distance (now optional - check returns True if FVG not present)
        if not self._check_bull_fvg_setup(bar):
            self._rejection_counts["fvg_setup"] += 1
            return

        # OFI trend confirmation (disabled - no positivity requirement)
        # ofi_trend = bar.get("f__flow__ofi_trend", 0.0)
        # if ofi_trend < self.params.ofi_trend_min:
        #     self._rejection_counts["ofi_trend"] += 1
        #     return

        # No bearish sweep overhang
        if bar.get("f__ict__liq_sweep_high", False):
            self._rejection_counts["sweep_overhang"] += 1
            return

        # Optional absorption confirmation
        if self.params.require_absorption and not bar.get("f__vpa__absorption", False):
            self._rejection_counts["absorption"] += 1
            return

        # Displacement leg confirmation
        if self.params.require_displacement:
            disp_high = bar.get("f__ict__disp_high", 0.0)
            if disp_high == 0.0 or bar["high"] < disp_high:
                self._rejection_counts["displacement"] += 1
                return

        # Calculate position size and risk
        atr = bar.get("f__vol__atr_30", 0.0)
        if atr < self.params.min_atr_value:
            self._rejection_counts["atr_too_low"] += 1
            return

        # Entry signal confirmed
        self._enter_long(bar, atr)

    def _check_bear_entry(self, bar: dict[str, Any]) -> None:
        """Check for BEAR regime entry conditions."""

        # Must be below key AVWAP levels (with tolerance band)
        tolerance = (
            self.params.avwap_tolerance
        )  # use parameter instead of hardcoded 0.001
        session_avwap = bar.get("f__anchor__session_avwap", float("inf"))
        first_hour_avwap = bar.get("f__anchor__first_hour_avwap", float("inf"))

        session_ok = (
            (session_avwap - bar["close"]) / bar["close"] > tolerance
            if session_avwap != float("inf")
            else True
        )
        first_hour_ok = (
            (first_hour_avwap - bar["close"]) / bar["close"] > tolerance
            if first_hour_avwap != float("inf")
            else True
        )

        if not (session_ok and first_hour_ok):
            return

        # NOTE: Regime strength validation removed - trust regime detector's classification
        # Log regime metrics for monitoring but don't gate on them
        vr = bar.get("f__regime__var_ratio_10_60", 1.0)
        adx = bar.get("f__regime__adx_proxy_14", 0.0)
        vol = bar.get("f__regime__mod_vol_30", 1.0)

        # NOTE: ICT premium zone check made optional (same reasoning as discount zone)

        # Active bearish FVG within acceptable distance (now optional - check returns True if FVG not present)
        if not self._check_bear_fvg_setup(bar):
            return

        # OFI trend confirmation (negative for bearish) - disabled
        # ofi_trend = bar.get("f__flow__ofi_trend", 0.0)
        # if ofi_trend > -self.params.ofi_trend_min:
        #     return

        # No bullish sweep overhang
        if bar.get("f__ict__liq_sweep_low", False):
            return

        # Optional absorption confirmation
        if self.params.require_absorption and not bar.get("f__vpa__absorption", False):
            return

        # Displacement leg confirmation
        if self.params.require_displacement:
            disp_low = bar.get("f__ict__disp_low", float("inf"))
            if disp_low == float("inf") or bar["low"] > disp_low:
                return

        # Calculate position size and risk
        atr = bar.get("f__vol__atr_30", 0.0)
        if atr < self.params.min_atr_value:
            return

        # Entry signal confirmed
        self._enter_short(bar, atr)

    def _check_bull_fvg_setup(self, bar: dict[str, Any]) -> bool:
        """Check for valid bullish FVG setup."""
        fvg_active = bar.get("f__ict__fvg_bull_active", False)
        if not fvg_active:
            return True  # Return True (pass) if FVG not active - make it optional

        fvg_upper = bar.get("f__ict__fvg_bull_upper", 0.0)
        if fvg_upper == 0.0:
            return True  # Return True (pass) if no FVG level - make it optional

        # Check distance to FVG
        atr = bar.get("f__vol__atr_30", 0.0)
        if atr <= 0:
            return True  # Return True (pass) if no ATR - make it optional

        distance = abs(bar["close"] - fvg_upper)

        # Loosened threshold: 5.0 ATR instead of 0.5
        return distance <= 5.0 * atr

    def _check_bear_fvg_setup(self, bar: dict[str, Any]) -> bool:
        """Check for valid bearish FVG setup."""
        fvg_active = bar.get("f__ict__fvg_bear_active", False)
        if not fvg_active:
            return True  # Return True (pass) if FVG not active - make it optional

        fvg_lower = bar.get("f__ict__fvg_bear_lower", 0.0)
        if fvg_lower == 0.0:
            return True  # Return True (pass) if no FVG level - make it optional

        # Check distance to FVG
        atr = bar.get("f__vol__atr_30", 0.0)
        if atr <= 0:
            return True  # Return True (pass) if no ATR - make it optional

        distance = abs(fvg_lower - bar["close"])

        # Loosened threshold: 5.0 ATR instead of 0.5
        return distance <= 5.0 * atr

    def _enter_long(self, bar: dict[str, Any], atr: float) -> None:
        """Enter long position with risk management."""
        symbol = bar["symbol"]

        # Calculate stop loss
        fvg_upper = bar.get("f__ict__fvg_bull_upper")
        if fvg_upper is None or pd.isna(fvg_upper):
            fvg_upper = bar["low"]
        swing_low = bar.get("f__anchor__prev_low_avwap", bar["low"] * 0.999)

        stop_level = max(fvg_upper, swing_low) * (1 - 0.001)  # 0.1% buffer
        stop_level = max(stop_level, bar["low"] - self.params.atr_stop_multiple * atr)

        # Calculate target
        target_level = bar["close"] + self.params.atr_target_multiple * atr

        # Risk/reward check
        risk = bar["close"] - stop_level
        reward = target_level - bar["close"]

        if reward / risk < self.params.min_risk_reward:
            return

        # Calculate position size (simplified - could be enhanced with proper sizing)
        position_size = self.params.max_position_size

        # Create market order (t+1 execution) using create method
        order = MarketOrder.create(
            symbol=symbol,
            quantity=int(position_size),
            side=OrderSide.BUY,
            ts_submitted=bar["ts"],
            strategy_id=self.name,
        )

        # Track trade
        trade_info = {
            "entry_bar": bar,
            "stop_level": stop_level,
            "target_level": target_level,
            "atr": atr,
            "entry_time": bar["ts"],
            "bars_held": 0,
        }

        self.active_orders[symbol] = trade_info

        # Submit order
        self.submit_order(order)

        # Log entry
        self._log_entry(
            bar, "LONG", position_size, stop_level, target_level, risk, reward
        )

    def _enter_short(self, bar: dict[str, Any], atr: float) -> None:
        """Enter short position with risk management."""
        symbol = bar["symbol"]

        # Calculate stop loss
        fvg_lower = bar.get("f__ict__fvg_bear_lower")
        if fvg_lower is None or pd.isna(fvg_lower):
            fvg_lower = bar["high"]
        swing_high = bar.get("f__anchor__prev_high_avwap", bar["high"] * 1.001)

        stop_level = min(fvg_lower, swing_high) * (1 + 0.001)  # 0.1% buffer
        stop_level = min(stop_level, bar["high"] + self.params.atr_stop_multiple * atr)

        # Calculate target
        target_level = bar["close"] - self.params.atr_target_multiple * atr

        # Risk/reward check
        risk = stop_level - bar["close"]
        reward = bar["close"] - target_level

        if reward / risk < self.params.min_risk_reward:
            return

        # Calculate position size
        position_size = self.params.max_position_size

        # Create market order
        order = MarketOrder.create(
            symbol=symbol,
            quantity=int(position_size),
            side=OrderSide.SELL,
            ts_submitted=bar["ts"],
            strategy_id=self.name,
        )

        # Track trade
        trade_info = {
            "entry_bar": bar,
            "stop_level": stop_level,
            "target_level": target_level,
            "atr": atr,
            "entry_time": bar["ts"],
            "bars_held": 0,
        }

        self.active_orders[symbol] = trade_info

        # Submit order
        self.submit_order(order)

        # Log entry
        self._log_entry(
            bar, "SHORT", position_size, stop_level, target_level, risk, reward
        )

    def _manage_position(self, bar: dict[str, Any], position) -> None:
        """Manage existing position with trailing stops and targets."""
        symbol = bar["symbol"]

        if symbol not in self.active_orders:
            return

        trade_info = self.active_orders[symbol]
        trade_info["bars_held"] += 1

        # Check timeout
        if trade_info["bars_held"] >= self.params.timeout_bars:
            self._close_position(bar, position, "Timeout")
            return

        # Check if target reached
        if position.quantity > 0:  # Long position
            if bar["high"] >= trade_info["target_level"]:
                self._close_position(bar, position, "Target reached")
                return
        elif bar["low"] <= trade_info["target_level"]:
            self._close_position(bar, position, "Target reached")
            return

        # Update trailing stop
        atr = trade_info["atr"]
        current_stop = trade_info["stop_level"]

        if position.quantity > 0:  # Long
            # Calculate new trailing stop level
            mfe = (
                bar["high"] - trade_info["entry_bar"]["close"]
            )  # Maximum favorable excursion
            if mfe >= self.params.atr_trailing_multiple * atr:
                # Start trailing
                new_stop = bar["high"] - self.params.atr_trailing_multiple * atr
                trade_info["stop_level"] = max(current_stop, new_stop)
        else:  # Short
            mfe = trade_info["entry_bar"]["close"] - bar["low"]
            if mfe >= self.params.atr_trailing_multiple * atr:
                new_stop = bar["low"] + self.params.atr_trailing_multiple * atr
                trade_info["stop_level"] = min(current_stop, new_stop)

        # Check stop hit
        if position.quantity > 0:  # Long
            if bar["low"] <= trade_info["stop_level"]:
                self._close_position(bar, position, "Stop loss")
        elif bar["high"] >= trade_info["stop_level"]:
            self._close_position(bar, position, "Stop loss")

    def _close_position(self, bar: dict[str, Any], position, reason: str) -> None:
        """Close position and log trade."""
        symbol = bar["symbol"]

        # Determine order side
        side = "SELL" if position.quantity > 0 else "BUY"

        # Create market order
        order = MarketOrder(
            symbol=symbol,
            order_type=OrderType.MARKET,
            quantity=abs(position.quantity),
            side=side,
            ts_submitted=bar["ts"],
            strategy_id=self.name,
        )

        # Submit order
        self.submit_order(order)

        # Log exit
        self._log_exit(bar, position, reason)

    def _log_entry(
        self,
        bar: dict[str, Any],
        side: str,
        size: float,
        stop: float,
        target: float,
        risk: float,
        reward: float,
    ) -> None:
        """Log trade entry with feature snapshot."""
        entry_log = {
            "timestamp": bar["ts"],
            "symbol": bar["symbol"],
            "action": "ENTRY",
            "side": side,
            "size": size,
            "price": bar["close"],
            "stop": stop,
            "target": target,
            "risk": risk,
            "reward": reward,
            "rr_ratio": reward / risk if risk != 0 else 0.0,
            "regime": bar.get("f__regime__current", "UNKNOWN"),
            "features": {
                "vr": bar.get("f__regime__var_ratio_10_60", 0),
                "adx": bar.get("f__regime__adx_proxy_14", 0),
                "vol": bar.get("f__regime__mod_vol_30", 0),
                "session_avwap": bar.get("f__anchor__session_avwap", 0),
                "profile_poc": bar.get("f__profile__poc"),
                "ofi_trend": bar.get("f__flow__ofi_trend", 0),
                "ofi": bar.get("f__flow__ofi"),
                "in_discount": bar.get("f__ict__in_discount", False),
                "in_premium": bar.get("f__ict__in_premium", False),
                "fvg_bull_active": bar.get("f__ict__fvg_bull_active", False),
                "fvg_bear_active": bar.get("f__ict__fvg_bear_active", False),
                "absorption": bar.get("f__vpa__absorption", False),
                "sweep_high": bar.get("f__ict__liq_sweep_high", False),
                "sweep_low": bar.get("f__ict__liq_sweep_low", False),
            },
        }
        self.trade_log.append(entry_log)

    def _log_exit(self, bar: dict[str, Any], position, reason: str) -> None:
        """Log trade exit."""
        symbol = bar["symbol"]

        # Find the most recent entry for this symbol
        entry_log = None
        for log in reversed(self.trade_log):
            if log.get("action") == "ENTRY" and log.get("symbol") == symbol:
                entry_log = log
                break

        if not entry_log:
            # No entry found - skip logging this exit (prevents corruption)
            return

        exit_log = {
            "timestamp": bar["ts"],
            "symbol": symbol,
            "action": "EXIT",
            "side": "SELL" if position.quantity > 0 else "BUY",
            "size": abs(position.quantity),
            "price": bar["close"],
            "reason": reason,
            "bars_held": self.active_orders.get(symbol, {}).get("bars_held", 0),
            "pnl": self._calculate_pnl(entry_log, bar, position),
        }

        self.trade_log.append(exit_log)

    def _calculate_pnl(self, entry_log: dict, bar: dict, position) -> float:
        """Calculate realized P&L."""
        if not entry_log:
            return 0.0

        entry_price = entry_log.get("price", 0.0)
        exit_price = bar["close"]
        size = abs(position.quantity)

        if position.quantity > 0:  # Long
            return (exit_price - entry_price) * size
        else:  # Short
            return (entry_price - exit_price) * size

    def get_trade_log(self) -> list[dict]:
        """Get complete trade log."""
        return self.trade_log.copy()

    def on_end(self) -> None:
        """Called when backtest ends."""
        # Print rejection gate analysis
        print(f"\n{'='*60}")
        print(f"{self.name} - Entry Gate Analysis")
        print(f"{'='*60}")
        print(f"Total bars processed: {self._total_bars_processed}")
        print(f"Passed regime+warmup: {self._rejection_counts['total_entry_checks']}")

        # Count trade log entries vs exits
        entry_actions = len([log for log in self.trade_log if log["action"] == "ENTRY"])
        exit_actions = len([log for log in self.trade_log if log["action"] == "EXIT"])

        print(f"\nPolicy trade log:")
        print(f"  ENTRY actions logged: {entry_actions}")
        print(f"  EXIT actions logged: {exit_actions}")
        print(f"  Unclosed positions: {entry_actions - exit_actions}")

        print(f"\nEntry check rejections (% of checks that passed regime+warmup):")
        entry_gates = [
            "avwap_position",
            "fvg_setup",
            "ofi_trend",
            "sweep_overhang",
            "absorption",
            "displacement",
            "atr_too_low",
            "risk_reward",
        ]
        for gate in entry_gates:
            count = self._rejection_counts.get(gate, 0)
            if count > 0:
                pct = (
                    count / max(self._rejection_counts["total_entry_checks"], 1)
                ) * 100
                print(f"  {gate:20s}: {count:6d} ({pct:5.1f}%)")

        # Log final statistics
        if self.trade_log:
            total_trades = len(
                [log for log in self.trade_log if log["action"] == "EXIT"]
            )
            profitable_trades = len(
                [
                    log
                    for log in self.trade_log
                    if log["action"] == "EXIT" and log.get("pnl", 0) > 0
                ]
            )

            print(f"\n{self.name} Trade Statistics (from policy trade_log):")
            print(f"  Round-trip trades: {total_trades}")
            print(f"  Profitable: {profitable_trades}")
            print(
                f"  Win rate: {profitable_trades/total_trades:.1%}"
                if total_trades > 0
                else "N/A"
            )

            # Log P&L summary
            total_pnl = sum(
                [log.get("pnl", 0) for log in self.trade_log if log["action"] == "EXIT"]
            )
            print(f"  Total P&L: ${total_pnl:.2f}")

            # Enhanced telemetry output
            self._log_enhanced_metrics()
        else:
            print(f"\n{self.name}: NO TRADES EXECUTED")

    def _analyze_entry_signals(
        self, bar: dict[str, Any], regime: str, entry_reason: str
    ) -> dict[str, Any]:
        """Analyze and attribute entry signals to specific features."""
        signals = {
            "primary_driver": "unknown",
            "contributing_factors": [],
            "signal_strength": 0.0,
            "feature_scores": {},
        }

        # AVWAP-based signals
        avwap_signals = []
        price = bar.get("close", 0)
        session_avwap = bar.get("f__anchor__session_avwap", 0)

        if session_avwap > 0:
            avwap_deviation = (price - session_avwap) / session_avwap
            if abs(avwap_deviation) > 0.002:  # 20 bps deviation
                avwap_signals.append(
                    f"session_avwap_deviation_{avwap_deviation*10000:.0f}bps"
                )

        # Volume profile signals
        poc = bar.get("f__profile__poc", 0)
        vah = bar.get("f__profile__vah", 0)
        val = bar.get("f__profile__val", 0)

        if poc > 0 and vah > 0 and val > 0:
            if val <= price <= vah:
                signals["contributing_factors"].append("value_area_inside")
            elif price > vah:
                signals["contributing_factors"].append("value_area_above")
            else:
                signals["contributing_factors"].append("value_area_below")

        # ICT structure signals
        if bar.get("f__ict__fvg_bull_active", False):
            signals["contributing_factors"].append("fvg_bull_active")
        if bar.get("f__ict__fvg_bear_active", False):
            signals["contributing_factors"].append("fvg_bear_active")
        if bar.get("f__ict__liq_sweep_high", False):
            signals["contributing_factors"].append("liquidity_sweep_high")
        if bar.get("f__ict__liq_sweep_low", False):
            signals["contributing_factors"].append("liquidity_sweep_low")

        # Order flow signals
        ofi = bar.get("f__flow__ofi", 0)
        ofi_trend = bar.get("f__flow__ofi_trend", "neutral")
        if abs(ofi) > 1000:  # Significant order flow imbalance
            signals["contributing_factors"].append(f"ofi_{ofi_trend}_strong")
        elif abs(ofi) > 500:
            signals["contributing_factors"].append(f"ofi_{ofi_trend}_moderate")

        # VPA signals
        if bar.get("f__vpa__absorption", False):
            signals["contributing_factors"].append("absorption_pattern")
        if bar.get("f__vpa__climax", False):
            signals["contributing_factors"].append("climax_pattern")

        # Determine primary driver based on strategy and reason
        if "momentum" in self.name.lower():
            if "breakout" in entry_reason.lower():
                signals["primary_driver"] = "avwap_breakout"
            elif "continuation" in entry_reason.lower():
                signals["primary_driver"] = "trend_continuation"
        elif "pullback" in self.name.lower():
            signals["primary_driver"] = "avwap_pullback"
        elif "rotation" in self.name.lower():
            signals["primary_driver"] = "value_area_rotation"
        elif "sweep" in self.name.lower():
            signals["primary_driver"] = "liquidity_sweep"

        # Calculate signal strength based on number of contributing factors
        signals["signal_strength"] = min(
            len(signals["contributing_factors"]) / 5.0, 1.0
        )

        return signals

    def _get_regime_metrics(self, bar: dict[str, Any], regime: str) -> dict[str, Any]:
        """Get regime-specific metrics and conditions."""
        return {
            "regime": regime,
            "regime_strength": self._calculate_regime_strength(bar),
            "regime_alignment_score": self._calculate_regime_alignment(bar, regime),
            "transition_risk": self._assess_transition_risk(bar, regime),
            "volatility_regime": self._classify_volatility_regime(bar),
        }

    def _calculate_regime_strength(self, bar: dict[str, Any]) -> float:
        """Calculate how strongly the current bar exhibits regime characteristics."""
        vr = bar.get("f__regime__var_ratio_10_60", 1.0)
        adx = bar.get("f__regime__adx_proxy_14", 0)
        vol = bar.get("f__regime__mod_vol_30", 1.0)

        # Normalize and combine features
        vr_score = min(abs(vr - 1.0) * 2, 1.0)  # Deviation from random walk
        adx_score = min(adx / 50.0, 1.0)  # Normalize ADX
        vol_score = min(abs(vol - 1.0) * 2, 1.0)  # Deviation from normal volatility

        return (vr_score + adx_score + vol_score) / 3.0

    def _calculate_regime_alignment(self, bar: dict[str, Any], regime: str) -> float:
        """Calculate how well current conditions align with expected regime behavior."""
        score = 0.5  # Base score

        # Trend alignment for BULL/BEAR regimes
        if regime in ["BULL", "BEAR"]:
            adx = bar.get("f__regime__adx_proxy_14", 0)
            if adx > 30:
                score += 0.3
            elif adx > 20:
                score += 0.15

        # Volatility alignment for STRESS regime
        if regime == "STRESS":
            vol = bar.get("f__regime__mod_vol_30", 1.0)
            if vol > 2.0:
                score += 0.4
            elif vol > 1.5:
                score += 0.2

        # Range-bound alignment for SIDEWAYS regime
        if regime == "SIDEWAYS":
            vr = bar.get("f__regime__var_ratio_10_60", 1.0)
            if 0.9 < vr < 1.1:
                score += 0.3

        return min(score, 1.0)

    def _assess_transition_risk(self, bar: dict[str, Any], regime: str) -> float:
        """Assess risk of regime transition based on current conditions."""
        risk = 0.1  # Base risk

        # High volatility increases transition risk
        vol = bar.get("f__regime__mod_vol_30", 1.0)
        if vol > 2.0:
            risk += 0.3
        elif vol > 1.5:
            risk += 0.15

        # Contradictory signals increase transition risk
        vr = bar.get("f__regime__var_ratio_10_60", 1.0)
        adx = bar.get("f__regime__adx_proxy_14", 0)

        if (
            regime == "BULL"
            and (vr < 1.0 or adx < 20)
            or regime == "BEAR"
            and (vr > 1.0 or adx < 20)
        ):
            risk += 0.2
        elif regime == "SIDEWAYS" and adx > 30:
            risk += 0.25

        return min(risk, 1.0)

    def _classify_volatility_regime(self, bar: dict[str, Any]) -> str:
        """Classify current volatility regime."""
        vol = bar.get("f__regime__mod_vol_30", 1.0)

        if vol > 2.5:
            return "extreme"
        elif vol > 1.8:
            return "high"
        elif vol > 1.3:
            return "elevated"
        elif vol > 0.8:
            return "normal"
        else:
            return "low"

    def _log_enhanced_metrics(self) -> None:
        """Log enhanced performance metrics and attribution."""
        if not self.trade_log:
            return

        # Basic metrics
        exit_logs = [log for log in self.trade_log if log["action"] == "EXIT"]
        if not exit_logs:
            return

        total_trades = len(exit_logs)
        profitable_trades = len([log for log in exit_logs if log.get("pnl", 0) > 0])

        # Regime attribution
        regime_performance = self._calculate_regime_attribution(exit_logs)

        # Feature attribution
        feature_attribution = self._calculate_feature_attribution(exit_logs)

        # Risk metrics
        risk_metrics = self._calculate_risk_metrics(exit_logs)

        # Time-based metrics
        time_metrics = self._calculate_time_metrics(exit_logs)

        # Create comprehensive telemetry payload
        telemetry = {
            "strategy": self.name,
            "timestamp": pd.Timestamp.now().isoformat(),
            "performance": {
                "total_trades": total_trades,
                "profitable_trades": profitable_trades,
                "win_rate": profitable_trades / total_trades if total_trades > 0 else 0,
                "total_pnl": sum([log.get("pnl", 0) for log in exit_logs]),
                "avg_trade": (
                    sum([log.get("pnl", 0) for log in exit_logs]) / total_trades
                    if total_trades > 0
                    else 0
                ),
                "best_trade": (
                    max([log.get("pnl", 0) for log in exit_logs]) if exit_logs else 0
                ),
                "worst_trade": (
                    min([log.get("pnl", 0) for log in exit_logs]) if exit_logs else 0
                ),
            },
            "regime_attribution": regime_performance,
            "feature_attribution": feature_attribution,
            "risk_metrics": risk_metrics,
            "time_metrics": time_metrics,
        }

        # Save telemetry to file for dashboard consumption
        import json
        import os

        telemetry_dir = "runs/telemetry"
        os.makedirs(telemetry_dir, exist_ok=True)

        telemetry_file = os.path.join(telemetry_dir, f"{self.name}_telemetry.json")
        with open(telemetry_file, "w") as f:
            json.dump(telemetry, f, indent=2)

        print(f"\nEnhanced telemetry saved to: {telemetry_file}")

    def _calculate_regime_attribution(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate performance attribution by regime."""
        regime_stats = {}

        for log in exit_logs:
            regime = log.get("regime", "UNKNOWN")
            pnl = log.get("pnl", 0)

            if regime not in regime_stats:
                regime_stats[regime] = {
                    "trades": 0,
                    "profitable": 0,
                    "total_pnl": 0,
                    "win_rate": 0,
                    "avg_trade": 0,
                }

            regime_stats[regime]["trades"] += 1
            if pnl > 0:
                regime_stats[regime]["profitable"] += 1
            regime_stats[regime]["total_pnl"] += pnl

        # Calculate derived metrics
        for _regime, stats in regime_stats.items():
            if stats["trades"] > 0:
                stats["win_rate"] = stats["profitable"] / stats["trades"]
                stats["avg_trade"] = stats["total_pnl"] / stats["trades"]

        return regime_stats

    def _calculate_feature_attribution(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate performance attribution by feature category."""
        feature_stats = {
            "avwap_features": {"trades": 0, "pnl": 0},
            "volume_profile": {"trades": 0, "pnl": 0},
            "ict_structures": {"trades": 0, "pnl": 0},
            "order_flow": {"trades": 0, "pnl": 0},
            "vpa_patterns": {"trades": 0, "pnl": 0},
        }

        for log in exit_logs:
            pnl = log.get("pnl", 0)
            features = log.get("features", {})

            # Check feature presence and attribute
            if features.get("session_avwap", 0) > 0:
                feature_stats["avwap_features"]["trades"] += 1
                feature_stats["avwap_features"]["pnl"] += pnl

            if features.get("profile_poc", 0) > 0:
                feature_stats["volume_profile"]["trades"] += 1
                feature_stats["volume_profile"]["pnl"] += pnl

            if features.get("fvg_bull_active", False) or features.get(
                "fvg_bear_active", False
            ):
                feature_stats["ict_structures"]["trades"] += 1
                feature_stats["ict_structures"]["pnl"] += pnl

            if features.get("ofi", 0) != 0:
                feature_stats["order_flow"]["trades"] += 1
                feature_stats["order_flow"]["pnl"] += pnl

            if features.get("absorption", False) or features.get("climax", False):
                feature_stats["vpa_patterns"]["trades"] += 1
                feature_stats["vpa_patterns"]["pnl"] += pnl

        # Calculate contribution percentages
        total_trades = len(exit_logs)
        for _feature, stats in feature_stats.items():
            if stats["trades"] > 0:
                stats["participation_rate"] = stats["trades"] / total_trades
                stats["avg_pnl"] = stats["pnl"] / stats["trades"]
            else:
                stats["participation_rate"] = 0
                stats["avg_pnl"] = 0

        return feature_stats

    def _calculate_risk_metrics(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate risk-related metrics."""
        pnls = [log.get("pnl", 0) for log in exit_logs]

        if not pnls:
            return {}

        # Calculate risk metrics
        positive_pnls = [pnl for pnl in pnls if pnl > 0]
        negative_pnls = [pnl for pnl in pnls if pnl < 0]

        return {
            "max_drawdown": min(pnls) if pnls else 0,
            "profit_factor": (
                sum(positive_pnls) / abs(sum(negative_pnls))
                if negative_pnls
                else float("inf")
            ),
            "avg_win": sum(positive_pnls) / len(positive_pnls) if positive_pnls else 0,
            "avg_loss": sum(negative_pnls) / len(negative_pnls) if negative_pnls else 0,
            "largest_win": max(pnls) if pnls else 0,
            "largest_loss": min(pnls) if pnls else 0,
            "sharpe_ratio": self._calculate_sharpe_ratio(pnls),
        }

    def _calculate_time_metrics(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate time-based performance metrics."""
        hold_times = [
            log.get("bars_held", 0) for log in exit_logs if "bars_held" in log
        ]

        if not hold_times:
            return {}

        return {
            "avg_hold_time": sum(hold_times) / len(hold_times),
            "max_hold_time": max(hold_times),
            "min_hold_time": min(hold_times),
            "trades_under_30min": len([t for t in hold_times if t < 30]),
            "trades_over_2hr": len([t for t in hold_times if t > 120]),
        }

    def _calculate_sharpe_ratio(self, pnls: list[float]) -> float:
        """Calculate Sharpe ratio for P&L series."""
        if len(pnls) < 2:
            return 0

        avg_pnl = sum(pnls) / len(pnls)
        variance = sum([(pnl - avg_pnl) ** 2 for pnl in pnls]) / (len(pnls) - 1)
        std_dev = variance**0.5

        return avg_pnl / std_dev if std_dev > 0 else 0


@dataclass
class ValueRotationParameters(PolicyParameters):
    """Parameters for Value Rotation strategy."""

    # Regime thresholds
    sideways_vr_range: tuple[float, float] = (0.9, 1.1)  # Variance ratio near 1.0
    sideways_adx_max: float = 22.0  # Low ADX for sideways markets
    sideways_vol_range: tuple[float, float] = (0.7, 1.4)
    stress_required: bool = False  # Must be no stress

    # Entry conditions
    max_below_val_distance: float = 0.8  # up from 0.25 (allows shallower deviations)
    max_above_vah_distance: float = 0.8
    require_value_acceptance: bool = False
    require_absorption_or_sweep: bool = False

    # AVWAP proximity
    max_avwap_distance: float = 0.015  # Max 0.5 ATR from session AVWAP
    require_avwap_context: bool = False

    # Risk management
    atr_stop_multiple: float = 1.0
    target_multiple: float = 0.8  # Target at POC or VAH/VAL
    timeout_bars: int = 45  # Shorter timeout for sideways markets

    def __post_init__(self):
        super().__post_init__()
        self.enabled_regimes = [RegimeType.SIDEWAYS]


class ValueRotationPolicy(Policy):
    """Value Rotation strategy for sideways markets using volume profile dynamics.

    SIDEWAYS Regime Entry (Long):
    - Price trades ≤0.25 ATR below VAL and closes back inside value area
    - VPA absorption or liquidity sweep low confirmation
    - Close within 0.5 ATR of session AVWAP (optional context)
    - Target at POC (optionally VAH), stop 0.25 ATR outside VAL

    SIDEWAYS Regime Entry (Short):
    - Mirror of long conditions at VAH with sweep high confirmation
    """

    def __init__(self, params: ValueRotationParameters | None = None):
        super().__init__("Value_Rotation")
        self.params = params or ValueRotationParameters()

        # Trade tracking
        self.active_orders: dict[str, dict] = {}
        self.trade_log: list[dict] = []

        # Value area tracking
        self.value_area_state: dict[str, dict] = {}

        # DEBUG: Gate rejection tracking
        self._rejection_counts = {
            "regime_gating": 0,
            "warmup": 0,
            "rotation_state": 0,
            "poc_levels": 0,
            "atr_too_low": 0,
            "risk_reward": 0,
            "total_entry_checks": 0,
        }
        self._total_bars_processed = 0

    def process_bar(self, bar: dict[str, Any]) -> None:
        """Process bar and generate trading signals."""
        self._total_bars_processed += 1

        # Check regime gating
        if not self._check_regime_gating(bar):
            self._rejection_counts["regime_gating"] += 1
            return

        # Check warmup
        if not self._check_warmup(bar):
            self._rejection_counts["warmup"] += 1
            return

        # Update value area state
        self._update_value_area_state(bar)

        # Get position
        position = self.get_position(bar["symbol"])

        # INTRADAY RULE: Force close all positions at market close (15:55 ET)
        if self._is_market_close(bar) and position and position.quantity != 0:
            self._close_position(bar, position, "End of day")
            return

        current_regime = bar.get("f__regime__current", RegimeType.OFF)

        # Exit logic for existing positions
        if position and position.quantity != 0:
            self._manage_position(bar, position)
            return

        # If position is closed, remove from active_orders before checking for new entries.
        if bar["symbol"] in self.active_orders:
            del self.active_orders[bar["symbol"]]

        # Entry logic only for SIDEWAYS regime
        self._rejection_counts["total_entry_checks"] += 1
        if current_regime == RegimeType.SIDEWAYS:
            self._check_value_rotation_entry(bar)

    def _is_market_close(self, bar: dict[str, Any]) -> bool:
        """Check if current bar is at or near market close (15:55 ET)."""
        import pandas as pd

        ts = bar["ts"]
        dt_et = pd.Timestamp(ts, unit="ns", tz="UTC").tz_convert("America/New_York")
        return dt_et.hour == 15 and dt_et.minute >= 55

    def _check_regime_gating(self, bar: dict[str, Any]) -> bool:
        """Check if strategy is allowed under current regime."""
        if not self.is_allowed():
            return False

        current_regime = bar.get("f__regime__current", RegimeType.OFF)
        return current_regime in self.params.enabled_regimes

    def _check_warmup(self, bar: dict[str, Any]) -> bool:
        """Check if features are warmed up."""
        return bar.get("f__warmup_ok", False)

    def _update_value_area_state(self, bar: dict[str, Any]) -> None:
        """Track value area state for entry timing."""
        symbol = bar["symbol"]

        if symbol not in self.value_area_state:
            self.value_area_state[symbol] = {
                "was_outside_value": False,
                "outside_direction": None,  # 'above' or 'below'
                "outside_start_bar": None,
                "last_acceptance_bar": None,
            }

        state = self.value_area_state[symbol]
        above_value = bar.get("f__profile__above_value", False)
        below_value = bar.get("f__profile__below_value", False)
        value_acceptance = bar.get("f__profile__value_acceptance", False)

        # Track outside value area state
        currently_outside = above_value or below_value
        currently_direction = (
            "above" if above_value else ("below" if below_value else None)
        )

        if currently_outside and not state["was_outside_value"]:
            # Just moved outside value area
            state["was_outside_value"] = True
            state["outside_direction"] = currently_direction
            state["outside_start_bar"] = bar
        elif not currently_outside and state["was_outside_value"]:
            # Just moved back inside value area
            state["was_outside_value"] = False
            if value_acceptance:
                state["last_acceptance_bar"] = bar

    def _check_value_rotation_entry(self, bar: dict[str, Any]) -> None:
        """Check for value rotation entry conditions."""
        symbol = bar["symbol"]
        state = self.value_area_state.get(symbol, {})

        # Check sideways regime strength
        vr = bar.get("f__regime__var_ratio_10_60", 1.0)
        adx = bar.get("f__regime__adx_proxy_14", 0.0)
        vol = bar.get("f__regime__mod_vol_30", 1.0)

        if not (
            self.params.sideways_vr_range[0] <= vr <= self.params.sideways_vr_range[1]
            and adx <= self.params.sideways_adx_max
            and self.params.sideways_vol_range[0]
            <= vol
            <= self.params.sideways_vol_range[1]
        ):
            return

        # Check stress condition
        stress = bar.get("f__regime__stress_10_10", 0.0)
        if self.params.stress_required and stress >= 1.0:
            return

        # Get volume profile levels
        poc = bar.get("f__profile__poc", 0.0)
        vah = bar.get("f__profile__vah", 0.0)
        val = bar.get("f__profile__val", 0.0)

        if poc == 0.0 or vah == 0.0 or val == 0.0:
            return

        atr = bar.get("f__vol__atr_30", 0.0)
        if atr < self.params.min_atr_value:
            return

        # Check for long entry (rotation from below value)
        if self._check_long_rotation_entry(bar, state, poc, vah, val, atr):
            return

        # Check for short entry (rotation from above value)
        if self._check_short_rotation_entry(bar, state, poc, vah, val, atr):
            return

    def _check_long_rotation_entry(
        self,
        bar: dict[str, Any],
        state: dict,
        poc: float,
        vah: float,
        val: float,
        atr: float,
    ) -> bool:
        """Check for long rotation entry from below value area."""
        # Must have been below value area and recently accepted back in
        if not (
            state.get("outside_direction") == "below"
            and state.get("last_acceptance_bar") is not None
        ):
            return False

        # Current bar must be inside value area
        if bar.get("f__profile__below_value", False):
            return False

        # Check distance from VAL (was sufficiently below)
        distance_below_val = (val - bar["low"]) / atr if atr > 0 else 0
        if distance_below_val < self.params.max_below_val_distance:
            return False

        # Need confirmation: absorption or sweep
        if self.params.require_absorption_or_sweep:
            has_absorption = bar.get("f__vpa__absorption", False)
            has_sweep_low = bar.get("f__ict__liq_sweep_low", False)

            if not (has_absorption or has_sweep_low):
                return False

        # Optional AVWAP context
        if self.params.require_avwap_context:
            session_avwap = bar.get("f__anchor__session_avwap", 0.0)
            if session_avwap == 0.0:
                return False

            avwap_distance = abs(bar["close"] - session_avwap) / atr
            if avwap_distance > self.params.max_avwap_distance:
                return False

        # Entry conditions met
        self._enter_long_rotation(bar, atr, poc, vah, val)
        return True

    def _check_short_rotation_entry(
        self,
        bar: dict[str, Any],
        state: dict,
        poc: float,
        vah: float,
        val: float,
        atr: float,
    ) -> bool:
        """Check for short rotation entry from above value area."""
        # Must have been above value area and recently accepted back in
        if not (
            state.get("outside_direction") == "above"
            and state.get("last_acceptance_bar") is not None
        ):
            return False

        # Current bar must be inside value area
        if bar.get("f__profile__above_value", False):
            return False

        # Check distance from VAH (was sufficiently above)
        distance_above_vah = (bar["high"] - vah) / atr if atr > 0 else 0
        if distance_above_vah < self.params.max_above_vah_distance:
            return False

        # Need confirmation: absorption or sweep
        if self.params.require_absorption_or_sweep:
            has_absorption = bar.get("f__vpa__absorption", False)
            has_sweep_high = bar.get("f__ict__liq_sweep_high", False)

            if not (has_absorption or has_sweep_high):
                return False

        # Optional AVWAP context
        if self.params.require_avwap_context:
            session_avwap = bar.get("f__anchor__session_avwap", 0.0)
            if session_avwap == 0.0:
                return False

            avwap_distance = abs(bar["close"] - session_avwap) / atr
            if avwap_distance > self.params.max_avwap_distance:
                return False

        # Entry conditions met
        self._enter_short_rotation(bar, atr, poc, vah, val)
        return True

    def _enter_long_rotation(
        self, bar: dict[str, Any], atr: float, poc: float, vah: float, val: float
    ) -> None:
        """Enter long position on value rotation from below."""
        symbol = bar["symbol"]

        # Calculate stop loss (outside VAL)
        stop_level = val - self.params.atr_stop_multiple * atr

        # Calculate target (POC or VAH)
        target_level = poc  # Primary target at POC

        # Risk/reward check
        risk = bar["close"] - stop_level
        reward = target_level - bar["close"]

        if reward / risk < self.params.min_risk_reward:
            return

        # Calculate position size
        position_size = self.params.max_position_size

        # Create market order
        order = MarketOrder(
            symbol=symbol,
            order_type=OrderType.MARKET,
            quantity=position_size,
            side="BUY",
            ts_submitted=bar["ts"],
            strategy_id=self.name,
        )

        # Log entry and get the entry log
        entry_log = self._log_entry(
            bar, "LONG", position_size, stop_level, target_level, risk, reward
        )

        # Track trade
        trade_info = {
            "entry_bar": bar,
            "stop_level": stop_level,
            "target_level": target_level,
            "secondary_target": vah,  # VAH as secondary target
            "atr": atr,
            "poc": poc,
            "vah": vah,
            "val": val,
            "entry_time": bar["ts"],
            "bars_held": 0,
            "entry_log": entry_log,
        }

        self.active_orders[symbol] = trade_info

        # Submit order
        self.submit_order(order)

    def _enter_short_rotation(
        self, bar: dict[str, Any], atr: float, poc: float, vah: float, val: float
    ) -> None:
        """Enter short position on value rotation from above."""
        symbol = bar["symbol"]

        # Calculate stop loss (outside VAH)
        stop_level = vah + self.params.atr_stop_multiple * atr

        # Calculate target (POC or VAL)
        target_level = poc  # Primary target at POC

        # Risk/reward check
        risk = stop_level - bar["close"]
        reward = bar["close"] - target_level

        if reward / risk < self.params.min_risk_reward:
            return

        # Calculate position size
        position_size = self.params.max_position_size

        # Create market order
        order = MarketOrder(
            symbol=symbol,
            order_type=OrderType.MARKET,
            quantity=position_size,
            side="SELL",
            ts_submitted=bar["ts"],
            strategy_id=self.name,
        )

        # Log entry and get the entry log
        entry_log = self._log_entry(
            bar, "SHORT", position_size, stop_level, target_level, risk, reward
        )

        # Track trade
        trade_info = {
            "entry_bar": bar,
            "stop_level": stop_level,
            "target_level": target_level,
            "secondary_target": val,  # VAL as secondary target
            "atr": atr,
            "poc": poc,
            "vah": vah,
            "val": val,
            "entry_time": bar["ts"],
            "bars_held": 0,
            "entry_log": entry_log,
        }

        self.active_orders[symbol] = trade_info

        # Submit order
        self.submit_order(order)

    def _manage_position(self, bar: dict[str, Any], position) -> None:
        """Manage existing position with targets and stops."""
        symbol = bar["symbol"]

        if symbol not in self.active_orders:
            return

        # INTRADAY RULE: Close at end of day (15:55 ET) - takes priority
        if self._is_market_close(bar):
            self._close_position(bar, position, "End of day")
            return

        trade_info = self.active_orders[symbol]
        trade_info["bars_held"] += 1

        # Check timeout
        if trade_info["bars_held"] >= self.params.timeout_bars:
            self._close_position(bar, position, "Timeout")
            return

        # Check if primary target reached (POC)
        if position.quantity > 0:  # Long position
            if bar["high"] >= trade_info["target_level"]:
                # Could consider scaling out or moving to secondary target
                self._close_position(bar, position, "Primary target reached")
                return
        elif bar["low"] <= trade_info["target_level"]:
            self._close_position(bar, position, "Primary target reached")
            return

        # Check stop hit
        if position.quantity > 0:  # Long
            if bar["low"] <= trade_info["stop_level"]:
                self._close_position(bar, position, "Stop loss")
        elif bar["high"] >= trade_info["stop_level"]:
            self._close_position(bar, position, "Stop loss")

    def _close_position(self, bar: dict[str, Any], position, reason: str) -> None:
        """Close position and log trade."""
        symbol = bar["symbol"]

        # Determine order side
        side = "SELL" if position.quantity > 0 else "BUY"

        # Create market order
        order = MarketOrder(
            symbol=symbol,
            order_type=OrderType.MARKET,
            quantity=abs(position.quantity),
            side=side,
            ts_submitted=bar["ts"],
            strategy_id=self.name,
        )

        # Submit order
        self.submit_order(order)

        # Log exit
        self._log_exit(bar, position, reason)

    def _log_entry(
        self,
        bar: dict[str, Any],
        side: str,
        size: float,
        stop: float,
        target: float,
        risk: float,
        reward: float,
    ) -> dict:
        """Log trade entry with feature snapshot."""
        entry_log = {
            "timestamp": bar["ts"],
            "symbol": bar["symbol"],
            "action": "ENTRY",
            "side": side,
            "size": size,
            "price": bar["close"],
            "stop": stop,
            "target": target,
            "risk": risk,
            "reward": reward,
            "rr_ratio": reward / risk,
            "regime": bar.get("f__regime__current", "UNKNOWN"),
            "strategy_type": "value_rotation",
            "features": {
                "vr": bar.get("f__regime__var_ratio_10_60", 0),
                "adx": bar.get("f__regime__adx_proxy_14", 0),
                "vol": bar.get("f__regime__mod_vol_30", 0),
                "poc": bar.get("f__profile__poc", 0),
                "vah": bar.get("f__profile__vah", 0),
                "val": bar.get("f__profile__val", 0),
                "above_value": bar.get("f__profile__above_value", False),
                "below_value": bar.get("f__profile__below_value", False),
                "value_acceptance": bar.get("f__profile__value_acceptance", False),
                "absorption": bar.get("f__vpa__absorption", False),
                "sweep_low": bar.get("f__ict__liq_sweep_low", False),
                "sweep_high": bar.get("f__ict__liq_sweep_high", False),
                "session_avwap": bar.get("f__anchor__session_avwap", 0),
                "ofi_trend": bar.get("f__flow__ofi_trend", 0),
                "ofi": bar.get("f__flow__ofi"),
            },
        }

        self.trade_log.append(entry_log)
        return entry_log

    def _calculate_pnl(self, entry_log: dict, bar: dict, position) -> float:
        """Calculate realized P&L."""
        if not entry_log:
            return 0.0

        entry_price = entry_log.get("price", 0.0)
        exit_price = bar["close"]
        size = abs(position.quantity)

        if position.quantity > 0:  # Long
            return (exit_price - entry_price) * size
        else:  # Short
            return (entry_price - exit_price) * size

    def get_trade_log(self) -> list[dict]:
        """Get complete trade log."""
        return self.trade_log.copy()

    def on_end(self) -> None:
        """Called when backtest ends."""
        # Print diagnostics
        print(f"\n{'='*60}")
        print(f"{self.name} - Entry Gate Analysis")
        print(f"{'='*60}")
        print(f"Total bars processed: {self._total_bars_processed}")
        print(f"Passed regime+warmup: {self._rejection_counts['total_entry_checks']}")

        entry_actions = len([log for log in self.trade_log if log["action"] == "ENTRY"])
        exit_actions = len([log for log in self.trade_log if log["action"] == "EXIT"])

        print(f"\nPolicy trade log:")
        print(f"  ENTRY actions: {entry_actions}")
        print(f"  EXIT actions: {exit_actions}")
        print(f"  Unclosed: {entry_actions - exit_actions}")

        # Log final statistics
        if self.trade_log:
            total_trades = len(
                [log for log in self.trade_log if log["action"] == "EXIT"]
            )
            profitable_trades = len(
                [
                    log
                    for log in self.trade_log
                    if log["action"] == "EXIT" and log.get("pnl", 0) > 0
                ]
            )

            print(f"\n{self.name} Policy Results:")
            print(f"Total trades: {total_trades}")
            print(f"Profitable trades: {profitable_trades}")
            print(
                f"Win rate: {profitable_trades/total_trades:.1%}"
                if total_trades > 0
                else "N/A"
            )

            # Log P&L summary
            total_pnl = sum(
                [log.get("pnl", 0) for log in self.trade_log if log["action"] == "EXIT"]
            )
            print(f"Total P&L: {total_pnl:.2f}")

            # Enhanced telemetry output
            self._log_enhanced_metrics()
        else:
            print(f"\n{self.name}: NO TRADES")

    def _analyze_entry_signals(
        self, bar: dict[str, Any], regime: str, entry_reason: str
    ) -> dict[str, Any]:
        """Analyze and attribute entry signals to specific features."""
        signals = {
            "primary_driver": "unknown",
            "contributing_factors": [],
            "signal_strength": 0.0,
            "feature_scores": {},
        }

        # AVWAP-based signals
        avwap_signals = []
        price = bar.get("close", 0)
        session_avwap = bar.get("f__anchor__session_avwap", 0)

        if session_avwap > 0:
            avwap_deviation = (price - session_avwap) / session_avwap
            if abs(avwap_deviation) > 0.002:  # 20 bps deviation
                avwap_signals.append(
                    f"session_avwap_deviation_{avwap_deviation*10000:.0f}bps"
                )

        # Volume profile signals
        poc = bar.get("f__profile__poc", 0)
        vah = bar.get("f__profile__vah", 0)
        val = bar.get("f__profile__val", 0)

        if poc > 0 and vah > 0 and val > 0:
            if val <= price <= vah:
                signals["contributing_factors"].append("value_area_inside")
            elif price > vah:
                signals["contributing_factors"].append("value_area_above")
            else:
                signals["contributing_factors"].append("value_area_below")

        # ICT structure signals
        if bar.get("f__ict__fvg_bull_active", False):
            signals["contributing_factors"].append("fvg_bull_active")
        if bar.get("f__ict__fvg_bear_active", False):
            signals["contributing_factors"].append("fvg_bear_active")
        if bar.get("f__ict__liq_sweep_high", False):
            signals["contributing_factors"].append("liquidity_sweep_high")
        if bar.get("f__ict__liq_sweep_low", False):
            signals["contributing_factors"].append("liquidity_sweep_low")

        # Order flow signals
        ofi = bar.get("f__flow__ofi", 0)
        ofi_trend = bar.get("f__flow__ofi_trend", "neutral")
        if abs(ofi) > 1000:  # Significant order flow imbalance
            signals["contributing_factors"].append(f"ofi_{ofi_trend}_strong")
        elif abs(ofi) > 500:
            signals["contributing_factors"].append(f"ofi_{ofi_trend}_moderate")

        # VPA signals
        if bar.get("f__vpa__absorption", False):
            signals["contributing_factors"].append("absorption_pattern")
        if bar.get("f__vpa__climax", False):
            signals["contributing_factors"].append("climax_pattern")

        # Determine primary driver based on strategy and reason
        if "momentum" in self.name.lower():
            if "breakout" in entry_reason.lower():
                signals["primary_driver"] = "avwap_breakout"
            elif "continuation" in entry_reason.lower():
                signals["primary_driver"] = "trend_continuation"
        elif "pullback" in self.name.lower():
            signals["primary_driver"] = "avwap_pullback"
        elif "rotation" in self.name.lower():
            signals["primary_driver"] = "value_area_rotation"
        elif "sweep" in self.name.lower():
            signals["primary_driver"] = "liquidity_sweep"

        # Calculate signal strength based on number of contributing factors
        signals["signal_strength"] = min(
            len(signals["contributing_factors"]) / 5.0, 1.0
        )

        return signals

    def _get_regime_metrics(self, bar: dict[str, Any], regime: str) -> dict[str, Any]:
        """Get regime-specific metrics and conditions."""
        return {
            "regime": regime,
            "regime_strength": self._calculate_regime_strength(bar),
            "regime_alignment_score": self._calculate_regime_alignment(bar, regime),
            "transition_risk": self._assess_transition_risk(bar, regime),
            "volatility_regime": self._classify_volatility_regime(bar),
        }

    def _calculate_regime_strength(self, bar: dict[str, Any]) -> float:
        """Calculate how strongly the current bar exhibits regime characteristics."""
        vr = bar.get("f__regime__var_ratio_10_60", 1.0)
        adx = bar.get("f__regime__adx_proxy_14", 0)
        vol = bar.get("f__regime__mod_vol_30", 1.0)

        # Normalize and combine features
        vr_score = min(abs(vr - 1.0) * 2, 1.0)  # Deviation from random walk
        adx_score = min(adx / 50.0, 1.0)  # Normalize ADX
        vol_score = min(abs(vol - 1.0) * 2, 1.0)  # Deviation from normal volatility

        return (vr_score + adx_score + vol_score) / 3.0

    def _calculate_regime_alignment(self, bar: dict[str, Any], regime: str) -> float:
        """Calculate how well current conditions align with expected regime behavior."""
        score = 0.5  # Base score

        # Trend alignment for BULL/BEAR regimes
        if regime in ["BULL", "BEAR"]:
            adx = bar.get("f__regime__adx_proxy_14", 0)
            if adx > 30:
                score += 0.3
            elif adx > 20:
                score += 0.15

        # Volatility alignment for STRESS regime
        if regime == "STRESS":
            vol = bar.get("f__regime__mod_vol_30", 1.0)
            if vol > 2.0:
                score += 0.4
            elif vol > 1.5:
                score += 0.2

        # Range-bound alignment for SIDEWAYS regime
        if regime == "SIDEWAYS":
            vr = bar.get("f__regime__var_ratio_10_60", 1.0)
            if 0.9 < vr < 1.1:
                score += 0.3

        return min(score, 1.0)

    def _assess_transition_risk(self, bar: dict[str, Any], regime: str) -> float:
        """Assess risk of regime transition based on current conditions."""
        risk = 0.1  # Base risk

        # High volatility increases transition risk
        vol = bar.get("f__regime__mod_vol_30", 1.0)
        if vol > 2.0:
            risk += 0.3
        elif vol > 1.5:
            risk += 0.15

        # Contradictory signals increase transition risk
        vr = bar.get("f__regime__var_ratio_10_60", 1.0)
        adx = bar.get("f__regime__adx_proxy_14", 0)

        if (
            regime == "BULL"
            and (vr < 1.0 or adx < 20)
            or regime == "BEAR"
            and (vr > 1.0 or adx < 20)
        ):
            risk += 0.2
        elif regime == "SIDEWAYS" and adx > 30:
            risk += 0.25

        return min(risk, 1.0)

    def _classify_volatility_regime(self, bar: dict[str, Any]) -> str:
        """Classify current volatility regime."""
        vol = bar.get("f__regime__mod_vol_30", 1.0)

        if vol > 2.5:
            return "extreme"
        elif vol > 1.8:
            return "high"
        elif vol > 1.3:
            return "elevated"
        elif vol > 0.8:
            return "normal"
        else:
            return "low"

    def _log_enhanced_metrics(self) -> None:
        """Log enhanced performance metrics and attribution."""
        if not self.trade_log:
            return

        # Basic metrics
        exit_logs = [log for log in self.trade_log if log["action"] == "EXIT"]
        if not exit_logs:
            return

        total_trades = len(exit_logs)
        profitable_trades = len([log for log in exit_logs if log.get("pnl", 0) > 0])

        # Regime attribution
        regime_performance = self._calculate_regime_attribution(exit_logs)

        # Feature attribution
        feature_attribution = self._calculate_feature_attribution(exit_logs)

        # Risk metrics
        risk_metrics = self._calculate_risk_metrics(exit_logs)

        # Time-based metrics
        time_metrics = self._calculate_time_metrics(exit_logs)

        # Create comprehensive telemetry payload
        telemetry = {
            "strategy": self.name,
            "timestamp": pd.Timestamp.now().isoformat(),
            "performance": {
                "total_trades": total_trades,
                "profitable_trades": profitable_trades,
                "win_rate": profitable_trades / total_trades if total_trades > 0 else 0,
                "total_pnl": sum([log.get("pnl", 0) for log in exit_logs]),
                "avg_trade": (
                    sum([log.get("pnl", 0) for log in exit_logs]) / total_trades
                    if total_trades > 0
                    else 0
                ),
                "best_trade": (
                    max([log.get("pnl", 0) for log in exit_logs]) if exit_logs else 0
                ),
                "worst_trade": (
                    min([log.get("pnl", 0) for log in exit_logs]) if exit_logs else 0
                ),
            },
            "regime_attribution": regime_performance,
            "feature_attribution": feature_attribution,
            "risk_metrics": risk_metrics,
            "time_metrics": time_metrics,
        }

        # Save telemetry to file for dashboard consumption
        import json
        import os

        telemetry_dir = "runs/telemetry"
        os.makedirs(telemetry_dir, exist_ok=True)

        telemetry_file = os.path.join(telemetry_dir, f"{self.name}_telemetry.json")
        with open(telemetry_file, "w") as f:
            json.dump(telemetry, f, indent=2)

        print(f"\nEnhanced telemetry saved to: {telemetry_file}")

    def _calculate_regime_attribution(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate performance attribution by regime."""
        regime_stats = {}

        for log in exit_logs:
            regime = log.get("regime", "UNKNOWN")
            pnl = log.get("pnl", 0)

            if regime not in regime_stats:
                regime_stats[regime] = {
                    "trades": 0,
                    "profitable": 0,
                    "total_pnl": 0,
                    "win_rate": 0,
                    "avg_trade": 0,
                }

            regime_stats[regime]["trades"] += 1
            if pnl > 0:
                regime_stats[regime]["profitable"] += 1
            regime_stats[regime]["total_pnl"] += pnl

        # Calculate derived metrics
        for _regime, stats in regime_stats.items():
            if stats["trades"] > 0:
                stats["win_rate"] = stats["profitable"] / stats["trades"]
                stats["avg_trade"] = stats["total_pnl"] / stats["trades"]

        return regime_stats

    def _calculate_feature_attribution(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate performance attribution by feature category."""
        feature_stats = {
            "avwap_features": {"trades": 0, "pnl": 0},
            "volume_profile": {"trades": 0, "pnl": 0},
            "ict_structures": {"trades": 0, "pnl": 0},
            "order_flow": {"trades": 0, "pnl": 0},
            "vpa_patterns": {"trades": 0, "pnl": 0},
        }

        for log in exit_logs:
            pnl = log.get("pnl", 0)
            features = log.get("features", {})

            # Check feature presence and attribute
            if features.get("session_avwap", 0) > 0:
                feature_stats["avwap_features"]["trades"] += 1
                feature_stats["avwap_features"]["pnl"] += pnl

            if features.get("profile_poc", 0) > 0:
                feature_stats["volume_profile"]["trades"] += 1
                feature_stats["volume_profile"]["pnl"] += pnl

            if features.get("fvg_bull_active", False) or features.get(
                "fvg_bear_active", False
            ):
                feature_stats["ict_structures"]["trades"] += 1
                feature_stats["ict_structures"]["pnl"] += pnl

            if features.get("ofi", 0) != 0:
                feature_stats["order_flow"]["trades"] += 1
                feature_stats["order_flow"]["pnl"] += pnl

            if features.get("absorption", False) or features.get("climax", False):
                feature_stats["vpa_patterns"]["trades"] += 1
                feature_stats["vpa_patterns"]["pnl"] += pnl

        # Calculate contribution percentages
        total_trades = len(exit_logs)
        for _feature, stats in feature_stats.items():
            if stats["trades"] > 0:
                stats["participation_rate"] = stats["trades"] / total_trades
                stats["avg_pnl"] = stats["pnl"] / stats["trades"]
            else:
                stats["participation_rate"] = 0
                stats["avg_pnl"] = 0

        return feature_stats

    def _calculate_risk_metrics(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate risk-related metrics."""
        pnls = [log.get("pnl", 0) for log in exit_logs]

        if not pnls:
            return {}

        # Calculate risk metrics
        positive_pnls = [pnl for pnl in pnls if pnl > 0]
        negative_pnls = [pnl for pnl in pnls if pnl < 0]

        return {
            "max_drawdown": min(pnls) if pnls else 0,
            "profit_factor": (
                sum(positive_pnls) / abs(sum(negative_pnls))
                if negative_pnls
                else float("inf")
            ),
            "avg_win": sum(positive_pnls) / len(positive_pnls) if positive_pnls else 0,
            "avg_loss": sum(negative_pnls) / len(negative_pnls) if negative_pnls else 0,
            "largest_win": max(pnls) if pnls else 0,
            "largest_loss": min(pnls) if pnls else 0,
            "sharpe_ratio": self._calculate_sharpe_ratio(pnls),
        }

    def _calculate_time_metrics(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate time-based performance metrics."""
        hold_times = [
            log.get("bars_held", 0) for log in exit_logs if "bars_held" in log
        ]

        if not hold_times:
            return {}

        return {
            "avg_hold_time": sum(hold_times) / len(hold_times),
            "max_hold_time": max(hold_times),
            "min_hold_time": min(hold_times),
            "trades_under_30min": len([t for t in hold_times if t < 30]),
            "trades_over_2hr": len([t for t in hold_times if t > 120]),
        }

    def _calculate_sharpe_ratio(self, pnls: list[float]) -> float:
        """Calculate Sharpe ratio for P&L series."""
        if len(pnls) < 2:
            return 0

        avg_pnl = sum(pnls) / len(pnls)
        variance = sum([(pnl - avg_pnl) ** 2 for pnl in pnls]) / (len(pnls) - 1)
        std_dev = variance**0.5

        return avg_pnl / std_dev if std_dev > 0 else 0


@dataclass
class SweepReversionParameters(PolicyParameters):
    """Parameters for Liquidity Sweep Reversion strategy."""

    # Regime thresholds
    sideways_vr_range: tuple[float, float] = (0.9, 1.1)  # Variance ratio near 1.0
    sideways_adx_max: float = 22.0  # Low ADX for sideways markets
    sideways_vol_range: tuple[float, float] = (0.7, 1.4)
    stress_required: bool = False  # Must be no stress

    # Entry conditions
    require_sweep_confirmation: bool = False
    require_band_position: bool = False
    min_sweep_distance: float = 0.0
    max_sweep_distance: float = 2.0

    # OFI confirmation
    require_ofi_trend: bool = False
    ofi_trend_threshold: float = 0.1  # Minimum OFI trend magnitude

    # Risk management
    atr_stop_multiple: float = 1.0  # Stop beyond sweep wick
    target_multiple: float = 0.8  # Target at AVWAP or POC (nearest)
    timeout_bars: int = 45  # Shorter timeout for mean reversion

    # Early exit conditions
    exit_on_climax_reversal: bool = True  # Exit early if VPA climax reverses

    def __post_init__(self):
        super().__post_init__()
        self.enabled_regimes = [RegimeType.SIDEWAYS]


class LiquiditySweepReversionPolicy(Policy):
    """Liquidity Sweep Reversion strategy for sideways markets.

    SIDEWAYS Regime Entry (Long):
    - f__ict__liq_sweep_low == True with low ADX and no stress
    - Band position < 0 (below mean) indicating mean reversion setup
    - Close above sweep level yet ≤ session AVWAP
    - OFI trend turning positive
    - Target at session AVWAP or POC (nearest), stop beyond sweep wick

    SIDEWAYS Regime Entry (Short):
    - Mirror of long conditions for sweep highs with band position > 0
    """

    def __init__(self, params: SweepReversionParameters | None = None):
        super().__init__("Sweep_Reversion")
        self.params = params or SweepReversionParameters()

        # Trade tracking
        self.active_orders: dict[str, dict] = {}
        self.trade_log: list[dict] = []

        # Sweep detection state
        self.sweep_state: dict[str, dict] = {}

    def process_bar(self, bar: dict[str, Any]) -> None:
        """Process bar and generate trading signals."""
        # Check regime gating
        if not self._check_regime_gating(bar):
            return

        # Check warmup
        if not self._check_warmup(bar):
            return

        # Update sweep state
        self._update_sweep_state(bar)

        # Get position
        position = self.get_position(bar["symbol"])
        current_regime = bar.get("f__regime__current", RegimeType.OFF)

        # Exit logic for existing positions
        if position and position.quantity != 0:
            self._manage_position(bar, position)
            return

        # If position is closed, remove from active_orders before checking for new entries.
        if bar["symbol"] in self.active_orders:
            del self.active_orders[bar["symbol"]]

        # Entry logic only for SIDEWAYS regime
        if current_regime == RegimeType.SIDEWAYS:
            self._check_sweep_reversion_entry(bar)

    def _check_regime_gating(self, bar: dict[str, Any]) -> bool:
        """Check if strategy is allowed under current regime."""
        if not self.is_allowed():
            return False

        current_regime = bar.get("f__regime__current", RegimeType.OFF)
        return current_regime in self.params.enabled_regimes

    def _check_warmup(self, bar: dict[str, Any]) -> bool:
        """Check if features are warmed up."""
        return bar.get("f__warmup_ok", False)

    def _update_sweep_state(self, bar: dict[str, Any]) -> None:
        """Track sweep patterns for entry timing."""
        symbol = bar["symbol"]

        if symbol not in self.sweep_state:
            self.sweep_state[symbol] = {
                "last_sweep_low": None,
                "last_sweep_high": None,
                "sweep_low_level": 0.0,
                "sweep_high_level": 0.0,
                "sweep_low_bar": None,
                "sweep_high_bar": None,
            }

        state = self.sweep_state[symbol]

        # Track sweep lows
        if bar.get("f__ict__liq_sweep_low", False):
            state["last_sweep_low"] = bar
            state["sweep_low_level"] = bar.get("f__ict__liq_sweep_low_level", 0.0)
            state["sweep_low_bar"] = bar

        # Track sweep highs
        if bar.get("f__ict__liq_sweep_high", False):
            state["last_sweep_high"] = bar
            state["sweep_high_level"] = bar.get("f__ict__liq_sweep_high_level", 0.0)
            state["sweep_high_bar"] = bar

    def _check_sweep_reversion_entry(self, bar: dict[str, Any]) -> None:
        """Check for sweep reversion entry conditions."""
        symbol = bar["symbol"]
        state = self.sweep_state.get(symbol, {})

        # Check sideways regime strength
        vr = bar.get("f__regime__var_ratio_10_60", 1.0)
        adx = bar.get("f__regime__adx_proxy_14", 0.0)
        vol = bar.get("f__regime__mod_vol_30", 1.0)

        if not (
            self.params.sideways_vr_range[0] <= vr <= self.params.sideways_vr_range[1]
            and adx <= self.params.sideways_adx_max
            and self.params.sideways_vol_range[0]
            <= vol
            <= self.params.sideways_vol_range[1]
        ):
            return

        # Check stress condition
        stress = bar.get("f__regime__stress_10_10", 0.0)
        if self.params.stress_required and stress >= 1.0:
            return

        atr = bar.get("f__vol__atr_30", 0.0)
        if atr < self.params.min_atr_value:
            return

        # Check for long entry (sweep low reversion)
        if self._check_sweep_long_entry(bar, state, atr):
            return

        # Check for short entry (sweep high reversion)
        if self._check_sweep_short_entry(bar, state, atr):
            return

    def _check_sweep_long_entry(
        self, bar: dict[str, Any], state: dict, atr: float
    ) -> bool:
        """Check for long entry after sweep low."""
        # Need recent sweep low
        if state.get("sweep_low_level") == 0.0 or state.get("sweep_low_bar") is None:
            return False

        sweep_level = state["sweep_low_level"]
        sweep_bar = state["sweep_low_bar"]

        # Check distance from sweep level
        distance_from_sweep = (bar["close"] - sweep_level) / atr if atr > 0 else 0
        if not (
            self.params.min_sweep_distance
            <= distance_from_sweep
            <= self.params.max_sweep_distance
        ):
            return False

        # Must be above sweep level
        if bar["close"] <= sweep_level:
            return False

        # Must be below or near session AVWAP
        session_avwap = bar.get("f__anchor__session_avwap", 0.0)
        if session_avwap == 0.0 or bar["close"] > session_avwap:
            return False

        # Band position must indicate mean reversion (below mean)
        if self.params.require_band_position:
            band_pos = bar.get("f__regime__band_pos_20_2.0", 0.5)
            if band_pos >= 0:  # Above or at mean
                return False

        # OFI trend confirmation
        if self.params.require_ofi_trend:
            ofi_trend = bar.get("f__flow__ofi_trend", 0.0)
            if ofi_trend < self.params.ofi_trend_threshold:
                return False

        # Entry conditions met
        self._enter_long_sweep_reversion(bar, atr, sweep_level)
        return True

    def _check_sweep_short_entry(
        self, bar: dict[str, Any], state: dict, atr: float
    ) -> bool:
        """Check for short entry after sweep high."""
        # Need recent sweep high
        if state.get("sweep_high_level") == 0.0 or state.get("sweep_high_bar") is None:
            return False

        sweep_level = state["sweep_high_level"]
        sweep_bar = state["sweep_high_bar"]

        # Check distance from sweep level
        distance_from_sweep = (sweep_level - bar["close"]) / atr if atr > 0 else 0
        if not (
            self.params.min_sweep_distance
            <= distance_from_sweep
            <= self.params.max_sweep_distance
        ):
            return False

        # Must be below sweep level
        if bar["close"] >= sweep_level:
            return False

        # Must be above or near session AVWAP
        session_avwap = bar.get("f__anchor__session_avwap", float("inf"))
        if session_avwap == float("inf") or bar["close"] < session_avwap:
            return False

        # Band position must indicate mean reversion (above mean)
        if self.params.require_band_position:
            band_pos = bar.get("f__regime__band_pos_20_2.0", 0.5)
            if band_pos <= 0:  # Below or at mean
                return False

        # OFI trend confirmation (negative for short)
        if self.params.require_ofi_trend:
            ofi_trend = bar.get("f__flow__ofi_trend", 0.0)
            if ofi_trend > -self.params.ofi_trend_threshold:
                return False

        # Entry conditions met
        self._enter_short_sweep_reversion(bar, atr, sweep_level)
        return True

    def _enter_long_sweep_reversion(
        self, bar: dict[str, Any], atr: float, sweep_level: float
    ) -> None:
        """Enter long position after sweep low reversion."""
        symbol = bar["symbol"]

        # Calculate stop loss (beyond sweep wick)
        stop_level = sweep_level - self.params.atr_stop_multiple * atr

        # Calculate target (nearest of AVWAP or POC)
        session_avwap = bar.get("f__anchor__session_avwap", 0.0)
        poc = bar.get("f__profile__poc", 0.0)

        target_level = session_avwap
        if poc > 0 and poc < session_avwap:  # POC is closer
            target_level = poc

        # Risk/reward check
        risk = bar["close"] - stop_level
        reward = target_level - bar["close"]

        if reward / risk < self.params.min_risk_reward:
            return

        # Calculate position size
        position_size = self.params.max_position_size

        # Create market order
        order = MarketOrder(
            symbol=symbol,
            order_type=OrderType.MARKET,
            quantity=position_size,
            side="BUY",
            ts_submitted=bar["ts"],
            strategy_id=self.name,
        )

        # Track trade
        trade_info = {
            "entry_bar": bar,
            "stop_level": stop_level,
            "target_level": target_level,
            "sweep_level": sweep_level,
            "atr": atr,
            "entry_time": bar["ts"],
            "bars_held": 0,
            "sweep_type": "low",
        }

        self.active_orders[symbol] = trade_info

        # Submit order
        self.submit_order(order)

        # Log entry
        self._log_entry(
            bar, "LONG", position_size, stop_level, target_level, risk, reward
        )

    def _enter_short_sweep_reversion(
        self, bar: dict[str, Any], atr: float, sweep_level: float
    ) -> None:
        """Enter short position after sweep high reversion."""
        symbol = bar["symbol"]

        # Calculate stop loss (beyond sweep wick)
        stop_level = sweep_level + self.params.atr_stop_multiple * atr

        # Calculate target (nearest of AVWAP or POC)
        session_avwap = bar.get("f__anchor__session_avwap", float("inf"))
        poc = bar.get("f__profile__poc", 0.0)

        target_level = session_avwap
        if poc > 0 and poc > session_avwap:  # POC is closer (above AVWAP)
            target_level = poc

        # Risk/reward check
        risk = stop_level - bar["close"]
        reward = bar["close"] - target_level

        if reward / risk < self.params.min_risk_reward:
            return

        # Calculate position size
        position_size = self.params.max_position_size

        # Create market order
        order = MarketOrder(
            symbol=symbol,
            order_type=OrderType.MARKET,
            quantity=position_size,
            side="SELL",
            ts_submitted=bar["ts"],
            strategy_id=self.name,
        )

        # Track trade
        trade_info = {
            "entry_bar": bar,
            "stop_level": stop_level,
            "target_level": target_level,
            "sweep_level": sweep_level,
            "atr": atr,
            "entry_time": bar["ts"],
            "bars_held": 0,
            "sweep_type": "high",
        }

        self.active_orders[symbol] = trade_info

        # Submit order
        self.submit_order(order)

        # Log entry
        self._log_entry(
            bar, "SHORT", position_size, stop_level, target_level, risk, reward
        )

    def _manage_position(self, bar: dict[str, Any], position) -> None:
        """Manage existing position with targets and stops."""
        symbol = bar["symbol"]

        if symbol not in self.active_orders:
            return

        trade_info = self.active_orders[symbol]
        trade_info["bars_held"] += 1

        # Check for early exit on climax reversal
        if self.params.exit_on_climax_reversal:
            if self._check_climax_reversal(bar, position):
                self._close_position(bar, position, "Climax reversal")
                return

        # Check timeout
        if trade_info["bars_held"] >= self.params.timeout_bars:
            self._close_position(bar, position, "Timeout")
            return

        # Check if target reached
        if position.quantity > 0:  # Long position
            if bar["high"] >= trade_info["target_level"]:
                self._close_position(bar, position, "Target reached")
                return
        elif bar["low"] <= trade_info["target_level"]:
            self._close_position(bar, position, "Target reached")
            return

        # Check stop hit
        if position.quantity > 0:  # Long
            if bar["low"] <= trade_info["stop_level"]:
                self._close_position(bar, position, "Stop loss")
        elif bar["high"] >= trade_info["stop_level"]:
            self._close_position(bar, position, "Stop loss")

    def _check_climax_reversal(self, bar: dict[str, Any], position) -> bool:
        """Check for VPA climax reversal that would trigger early exit."""
        # For long positions, look for bearish climax reversal
        if position.quantity > 0:
            # Previous bar had climax, current bar shows reversal
            # This is simplified - in practice would track previous bars
            climax_reversal = (
                bar.get("f__vpa__downthrust", False)  # Bearish thrust
                and bar.get("f__flow__ofi_trend", 0.0) < -0.1  # Negative OFI trend
            )
            return climax_reversal
        else:
            # For short positions, look for bullish climax reversal
            climax_reversal = (
                bar.get("f__vpa__upthrust", False)  # Bullish thrust
                and bar.get("f__flow__ofi_trend", 0.0) > 0.1  # Positive OFI trend
            )
            return climax_reversal

    def _close_position(self, bar: dict[str, Any], position, reason: str) -> None:
        """Close position and log trade."""
        symbol = bar["symbol"]

        # Determine order side
        side = "SELL" if position.quantity > 0 else "BUY"

        # Create market order
        order = MarketOrder(
            symbol=symbol,
            order_type=OrderType.MARKET,
            quantity=abs(position.quantity),
            side=side,
            ts_submitted=bar["ts"],
            strategy_id=self.name,
        )

        # Submit order
        self.submit_order(order)

        # Log exit
        self._log_exit(bar, position, reason)

    def _log_entry(
        self,
        bar: dict[str, Any],
        side: str,
        size: float,
        stop: float,
        target: float,
        risk: float,
        reward: float,
    ) -> None:
        """Log trade entry with feature snapshot."""
        entry_log = {
            "timestamp": bar["ts"],
            "symbol": bar["symbol"],
            "action": "ENTRY",
            "side": side,
            "size": size,
            "price": bar["close"],
            "stop": stop,
            "target": target,
            "risk": risk,
            "reward": reward,
            "rr_ratio": reward / risk,
            "regime": bar.get("f__regime__current", "UNKNOWN"),
            "strategy_type": "sweep_reversion",
            "features": {
                "vr": bar.get("f__regime__var_ratio_10_60", 0),
                "adx": bar.get("f__regime__adx_proxy_14", 0),
                "vol": bar.get("f__regime__mod_vol_30", 0),
                "band_pos": bar.get("f__regime__band_pos_20_2.0", 0),
                "sweep_low": bar.get("f__ict__liq_sweep_low", False),
                "sweep_high": bar.get("f__ict__liq_sweep_high", False),
                "sweep_low_level": bar.get("f__ict__liq_sweep_low_level", 0),
                "sweep_high_level": bar.get("f__ict__liq_sweep_high_level", 0),
                "ofi_trend": bar.get("f__flow__ofi_trend", 0),
                "session_avwap": bar.get("f__anchor__session_avwap", 0),
                "poc": bar.get("f__profile__poc", 0),
                "upthrust": bar.get("f__vpa__upthrust", False),
                "downthrust": bar.get("f__vpa__downthrust", False),
            },
        }

        self.trade_log.append(entry_log)

    def _log_exit(self, bar: dict[str, Any], position, reason: str) -> None:
        """Log trade exit."""
        symbol = bar["symbol"]

        # Find the most recent entry for this symbol that hasn't been exited
        entry_log = None
        for log in reversed(self.trade_log):
            if log.get("action") == "ENTRY" and log.get("symbol") == symbol:
                # Check if this entry already has a matching exit
                has_exit = any(
                    exit_log.get("action") == "EXIT"
                    and exit_log.get("symbol") == symbol
                    and exit_log.get("timestamp", 0) > log.get("timestamp", 0)
                    for exit_log in self.trade_log[self.trade_log.index(log) + 1 :]
                )
                if not has_exit:
                    entry_log = log
                    break

        if not entry_log:
            # No unmatched entry found - skip logging (prevents corruption from repeated closes)
            return

        exit_log = {
            "timestamp": bar["ts"],
            "symbol": symbol,
            "action": "EXIT",
            "side": "SELL" if position.quantity > 0 else "BUY",
            "size": abs(position.quantity),
            "price": bar["close"],
            "reason": reason,
            "bars_held": self.active_orders.get(symbol, {}).get("bars_held", 0),
            "pnl": self._calculate_pnl(entry_log, bar, position),
        }

        self.trade_log.append(exit_log)

    def _calculate_pnl(self, entry_log: dict, bar: dict, position) -> float:
        """Calculate realized P&L."""
        if not entry_log:
            return 0.0

        entry_price = entry_log.get("price", 0.0)
        exit_price = bar["close"]
        size = abs(position.quantity)

        if position.quantity > 0:  # Long
            return (exit_price - entry_price) * size
        else:  # Short
            return (entry_price - exit_price) * size

    def get_trade_log(self) -> list[dict]:
        """Get complete trade log."""
        return self.trade_log.copy()

    def on_end(self) -> None:
        """Called when backtest ends."""
        # Log final statistics
        if self.trade_log:
            total_trades = len(
                [log for log in self.trade_log if log["action"] == "EXIT"]
            )
            profitable_trades = len(
                [
                    log
                    for log in self.trade_log
                    if log["action"] == "EXIT" and log.get("pnl", 0) > 0
                ]
            )

            print(f"\n{self.name} Policy Results:")
            print(f"Total trades: {total_trades}")
            print(f"Profitable trades: {profitable_trades}")
            print(
                f"Win rate: {profitable_trades/total_trades:.1%}"
                if total_trades > 0
                else "N/A"
            )

            # Log P&L summary
            total_pnl = sum(
                [log.get("pnl", 0) for log in self.trade_log if log["action"] == "EXIT"]
            )
            print(f"Total P&L: {total_pnl:.2f}")

            # Enhanced telemetry output
            self._log_enhanced_metrics()

    def _analyze_entry_signals(
        self, bar: dict[str, Any], regime: str, entry_reason: str
    ) -> dict[str, Any]:
        """Analyze and attribute entry signals to specific features."""
        signals = {
            "primary_driver": "unknown",
            "contributing_factors": [],
            "signal_strength": 0.0,
            "feature_scores": {},
        }

        # AVWAP-based signals
        avwap_signals = []
        price = bar.get("close", 0)
        session_avwap = bar.get("f__anchor__session_avwap", 0)

        if session_avwap > 0:
            avwap_deviation = (price - session_avwap) / session_avwap
            if abs(avwap_deviation) > 0.002:  # 20 bps deviation
                avwap_signals.append(
                    f"session_avwap_deviation_{avwap_deviation*10000:.0f}bps"
                )

        # Volume profile signals
        poc = bar.get("f__profile__poc", 0)
        vah = bar.get("f__profile__vah", 0)
        val = bar.get("f__profile__val", 0)

        if poc > 0 and vah > 0 and val > 0:
            if val <= price <= vah:
                signals["contributing_factors"].append("value_area_inside")
            elif price > vah:
                signals["contributing_factors"].append("value_area_above")
            else:
                signals["contributing_factors"].append("value_area_below")

        # ICT structure signals
        if bar.get("f__ict__fvg_bull_active", False):
            signals["contributing_factors"].append("fvg_bull_active")
        if bar.get("f__ict__fvg_bear_active", False):
            signals["contributing_factors"].append("fvg_bear_active")
        if bar.get("f__ict__liq_sweep_high", False):
            signals["contributing_factors"].append("liquidity_sweep_high")
        if bar.get("f__ict__liq_sweep_low", False):
            signals["contributing_factors"].append("liquidity_sweep_low")

        # Order flow signals
        ofi = bar.get("f__flow__ofi", 0)
        ofi_trend = bar.get("f__flow__ofi_trend", "neutral")
        if abs(ofi) > 1000:  # Significant order flow imbalance
            signals["contributing_factors"].append(f"ofi_{ofi_trend}_strong")
        elif abs(ofi) > 500:
            signals["contributing_factors"].append(f"ofi_{ofi_trend}_moderate")

        # VPA signals
        if bar.get("f__vpa__absorption", False):
            signals["contributing_factors"].append("absorption_pattern")
        if bar.get("f__vpa__climax", False):
            signals["contributing_factors"].append("climax_pattern")

        # Determine primary driver based on strategy and reason
        if "momentum" in self.name.lower():
            if "breakout" in entry_reason.lower():
                signals["primary_driver"] = "avwap_breakout"
            elif "continuation" in entry_reason.lower():
                signals["primary_driver"] = "trend_continuation"
        elif "pullback" in self.name.lower():
            signals["primary_driver"] = "avwap_pullback"
        elif "rotation" in self.name.lower():
            signals["primary_driver"] = "value_area_rotation"
        elif "sweep" in self.name.lower():
            signals["primary_driver"] = "liquidity_sweep"

        # Calculate signal strength based on number of contributing factors
        signals["signal_strength"] = min(
            len(signals["contributing_factors"]) / 5.0, 1.0
        )

        return signals

    def _get_regime_metrics(self, bar: dict[str, Any], regime: str) -> dict[str, Any]:
        """Get regime-specific metrics and conditions."""
        return {
            "regime": regime,
            "regime_strength": self._calculate_regime_strength(bar),
            "regime_alignment_score": self._calculate_regime_alignment(bar, regime),
            "transition_risk": self._assess_transition_risk(bar, regime),
            "volatility_regime": self._classify_volatility_regime(bar),
        }

    def _calculate_regime_strength(self, bar: dict[str, Any]) -> float:
        """Calculate how strongly the current bar exhibits regime characteristics."""
        vr = bar.get("f__regime__var_ratio_10_60", 1.0)
        adx = bar.get("f__regime__adx_proxy_14", 0)
        vol = bar.get("f__regime__mod_vol_30", 1.0)

        # Normalize and combine features
        vr_score = min(abs(vr - 1.0) * 2, 1.0)  # Deviation from random walk
        adx_score = min(adx / 50.0, 1.0)  # Normalize ADX
        vol_score = min(abs(vol - 1.0) * 2, 1.0)  # Deviation from normal volatility

        return (vr_score + adx_score + vol_score) / 3.0

    def _calculate_regime_alignment(self, bar: dict[str, Any], regime: str) -> float:
        """Calculate how well current conditions align with expected regime behavior."""
        score = 0.5  # Base score

        # Trend alignment for BULL/BEAR regimes
        if regime in ["BULL", "BEAR"]:
            adx = bar.get("f__regime__adx_proxy_14", 0)
            if adx > 30:
                score += 0.3
            elif adx > 20:
                score += 0.15

        # Volatility alignment for STRESS regime
        if regime == "STRESS":
            vol = bar.get("f__regime__mod_vol_30", 1.0)
            if vol > 2.0:
                score += 0.4
            elif vol > 1.5:
                score += 0.2

        # Range-bound alignment for SIDEWAYS regime
        if regime == "SIDEWAYS":
            vr = bar.get("f__regime__var_ratio_10_60", 1.0)
            if 0.9 < vr < 1.1:
                score += 0.3

        return min(score, 1.0)

    def _assess_transition_risk(self, bar: dict[str, Any], regime: str) -> float:
        """Assess risk of regime transition based on current conditions."""
        risk = 0.1  # Base risk

        # High volatility increases transition risk
        vol = bar.get("f__regime__mod_vol_30", 1.0)
        if vol > 2.0:
            risk += 0.3
        elif vol > 1.5:
            risk += 0.15

        # Contradictory signals increase transition risk
        vr = bar.get("f__regime__var_ratio_10_60", 1.0)
        adx = bar.get("f__regime__adx_proxy_14", 0)

        if (
            regime == "BULL"
            and (vr < 1.0 or adx < 20)
            or regime == "BEAR"
            and (vr > 1.0 or adx < 20)
        ):
            risk += 0.2
        elif regime == "SIDEWAYS" and adx > 30:
            risk += 0.25

        return min(risk, 1.0)

    def _classify_volatility_regime(self, bar: dict[str, Any]) -> str:
        """Classify current volatility regime."""
        vol = bar.get("f__regime__mod_vol_30", 1.0)

        if vol > 2.5:
            return "extreme"
        elif vol > 1.8:
            return "high"
        elif vol > 1.3:
            return "elevated"
        elif vol > 0.8:
            return "normal"
        else:
            return "low"

    def _log_enhanced_metrics(self) -> None:
        """Log enhanced performance metrics and attribution."""
        if not self.trade_log:
            return

        # Basic metrics
        exit_logs = [log for log in self.trade_log if log["action"] == "EXIT"]
        if not exit_logs:
            return

        total_trades = len(exit_logs)
        profitable_trades = len([log for log in exit_logs if log.get("pnl", 0) > 0])

        # Regime attribution
        regime_performance = self._calculate_regime_attribution(exit_logs)

        # Feature attribution
        feature_attribution = self._calculate_feature_attribution(exit_logs)

        # Risk metrics
        risk_metrics = self._calculate_risk_metrics(exit_logs)

        # Time-based metrics
        time_metrics = self._calculate_time_metrics(exit_logs)

        # Create comprehensive telemetry payload
        telemetry = {
            "strategy": self.name,
            "timestamp": pd.Timestamp.now().isoformat(),
            "performance": {
                "total_trades": total_trades,
                "profitable_trades": profitable_trades,
                "win_rate": profitable_trades / total_trades if total_trades > 0 else 0,
                "total_pnl": sum([log.get("pnl", 0) for log in exit_logs]),
                "avg_trade": (
                    sum([log.get("pnl", 0) for log in exit_logs]) / total_trades
                    if total_trades > 0
                    else 0
                ),
                "best_trade": (
                    max([log.get("pnl", 0) for log in exit_logs]) if exit_logs else 0
                ),
                "worst_trade": (
                    min([log.get("pnl", 0) for log in exit_logs]) if exit_logs else 0
                ),
            },
            "regime_attribution": regime_performance,
            "feature_attribution": feature_attribution,
            "risk_metrics": risk_metrics,
            "time_metrics": time_metrics,
        }

        # Save telemetry to file for dashboard consumption
        import json
        import os

        telemetry_dir = "runs/telemetry"
        os.makedirs(telemetry_dir, exist_ok=True)

        telemetry_file = os.path.join(telemetry_dir, f"{self.name}_telemetry.json")
        with open(telemetry_file, "w") as f:
            json.dump(telemetry, f, indent=2)

        print(f"\nEnhanced telemetry saved to: {telemetry_file}")

    def _calculate_regime_attribution(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate performance attribution by regime."""
        regime_stats = {}

        for log in exit_logs:
            regime = log.get("regime", "UNKNOWN")
            pnl = log.get("pnl", 0)

            if regime not in regime_stats:
                regime_stats[regime] = {
                    "trades": 0,
                    "profitable": 0,
                    "total_pnl": 0,
                    "win_rate": 0,
                    "avg_trade": 0,
                }

            regime_stats[regime]["trades"] += 1
            if pnl > 0:
                regime_stats[regime]["profitable"] += 1
            regime_stats[regime]["total_pnl"] += pnl

        # Calculate derived metrics
        for _regime, stats in regime_stats.items():
            if stats["trades"] > 0:
                stats["win_rate"] = stats["profitable"] / stats["trades"]
                stats["avg_trade"] = stats["total_pnl"] / stats["trades"]

        return regime_stats

    def _calculate_feature_attribution(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate performance attribution by feature category."""
        feature_stats = {
            "avwap_features": {"trades": 0, "pnl": 0},
            "volume_profile": {"trades": 0, "pnl": 0},
            "ict_structures": {"trades": 0, "pnl": 0},
            "order_flow": {"trades": 0, "pnl": 0},
            "vpa_patterns": {"trades": 0, "pnl": 0},
        }

        for log in exit_logs:
            pnl = log.get("pnl", 0)
            features = log.get("features", {})

            # Check feature presence and attribute
            if features.get("session_avwap", 0) > 0:
                feature_stats["avwap_features"]["trades"] += 1
                feature_stats["avwap_features"]["pnl"] += pnl

            if features.get("profile_poc", 0) > 0:
                feature_stats["volume_profile"]["trades"] += 1
                feature_stats["volume_profile"]["pnl"] += pnl

            if features.get("fvg_bull_active", False) or features.get(
                "fvg_bear_active", False
            ):
                feature_stats["ict_structures"]["trades"] += 1
                feature_stats["ict_structures"]["pnl"] += pnl

            if features.get("ofi", 0) != 0:
                feature_stats["order_flow"]["trades"] += 1
                feature_stats["order_flow"]["pnl"] += pnl

            if features.get("absorption", False) or features.get("climax", False):
                feature_stats["vpa_patterns"]["trades"] += 1
                feature_stats["vpa_patterns"]["pnl"] += pnl

        # Calculate contribution percentages
        total_trades = len(exit_logs)
        for _feature, stats in feature_stats.items():
            if stats["trades"] > 0:
                stats["participation_rate"] = stats["trades"] / total_trades
                stats["avg_pnl"] = stats["pnl"] / stats["trades"]
            else:
                stats["participation_rate"] = 0
                stats["avg_pnl"] = 0

        return feature_stats

    def _calculate_risk_metrics(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate risk-related metrics."""
        pnls = [log.get("pnl", 0) for log in exit_logs]

        if not pnls:
            return {}

        # Calculate risk metrics
        positive_pnls = [pnl for pnl in pnls if pnl > 0]
        negative_pnls = [pnl for pnl in pnls if pnl < 0]

        return {
            "max_drawdown": min(pnls) if pnls else 0,
            "profit_factor": (
                sum(positive_pnls) / abs(sum(negative_pnls))
                if negative_pnls
                else float("inf")
            ),
            "avg_win": sum(positive_pnls) / len(positive_pnls) if positive_pnls else 0,
            "avg_loss": sum(negative_pnls) / len(negative_pnls) if negative_pnls else 0,
            "largest_win": max(pnls) if pnls else 0,
            "largest_loss": min(pnls) if pnls else 0,
            "sharpe_ratio": self._calculate_sharpe_ratio(pnls),
        }

    def _calculate_time_metrics(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate time-based performance metrics."""
        hold_times = [
            log.get("bars_held", 0) for log in exit_logs if "bars_held" in log
        ]

        if not hold_times:
            return {}

        return {
            "avg_hold_time": sum(hold_times) / len(hold_times),
            "max_hold_time": max(hold_times),
            "min_hold_time": min(hold_times),
            "trades_under_30min": len([t for t in hold_times if t < 30]),
            "trades_over_2hr": len([t for t in hold_times if t > 120]),
        }

    def _calculate_sharpe_ratio(self, pnls: list[float]) -> float:
        """Calculate Sharpe ratio for P&L series."""
        if len(pnls) < 2:
            return 0

        avg_pnl = sum(pnls) / len(pnls)
        variance = sum([(pnl - avg_pnl) ** 2 for pnl in pnls]) / (len(pnls) - 1)
        std_dev = variance**0.5

        return avg_pnl / std_dev if std_dev > 0 else 0


@dataclass
class PullbackParameters(PolicyParameters):
    """Parameters for AVWAP Pullback strategy."""

    # Regime thresholds
    bull_vr_min: float = 1.2
    bull_adx_min: float = 25.0
    bull_vol_range: tuple[float, float] = (0.8, 1.6)
    bear_vr_max: float = 0.8
    bear_adx_min: float = 25.0
    bear_vol_range: tuple[float, float] = (0.8, 1.6)

    # Pullback entry conditions
    max_avwap_distance: float = 0.015  # allow 1.5 % deviation from AVWAP (was 0.6 %)
    pullback_window_bars: int = 5  # Lookback for pullback identification
    reclaim_confirmation: bool = True  # Require close back above AVWAP

    # Risk management
    stop_buffer_atr: float = 1.0  # ATR buffer below swing low
    target_multiple: float = 1.2  # target 1.2× ATR to improve reward
    trailing_trigger_multiple: float = 1.0  # Start trailing after 1x ATR MFE

    # Feature filters
    require_discount_zone: bool = False
    max_bearish_fvg_distance: float = (
        5.0  # Max ATR distance to bearish FVG overhead (loosened from 0.5)
    )
    require_absorption: bool = False  # Optional absorption confirmation
    require_fvg: bool = False  # Make FVG checks optional

    def __post_init__(self):
        super().__post_init__()
        self.enabled_regimes = [RegimeType.BULL, RegimeType.BEAR]


class AVWAPPullbackPolicy(Policy):
    """AVWAP Pullback strategy for deep pullbacks to key anchored levels.

    BULL Regime Entry (Long):
    - Within last 5 bars, low ≤ session AVWAP × (1 - max(0.35%, 0.6×ATR%))
    - Current bar closes back above session AVWAP
    - Price remains in discount PD array
    - No active bearish FVG ≤ 0.5 ATR overhead
    - Optional absorption confirmation

    BEAR Regime Entry (Short):
    - Mirror of BULL conditions with bearish setups
    """

    def __init__(self, params: PullbackParameters | None = None):
        super().__init__("AVWAP_Pullback")
        self.params = params or PullbackParameters()
        self.atr_stop_manager = ATRStopManager()
        self.stop_manager = self.atr_stop_manager

        # Trade tracking
        self.active_orders: dict[str, dict] = {}
        self.trade_log: list[dict] = []

        # Pullback detection
        self.price_history: dict[str, list[dict]] = {}

        # DEBUG: Gate rejection tracking
        self._rejection_counts = {
            "regime_gating": 0,
            "warmup": 0,
            "avwap_position": 0,
            "pullback_detected": 0,
            "overhead_fvg": 0,
            "absorption": 0,
            "atr_too_low": 0,
            "risk_reward": 0,
            "total_entry_checks": 0,
        }
        self._total_bars_processed = 0

    def _is_market_close(self, bar: dict[str, Any]) -> bool:
        """Check if current bar is at or near market close (15:55 ET)."""
        import pandas as pd

        ts = bar["ts"]
        dt_et = pd.Timestamp(ts, unit="ns", tz="UTC").tz_convert("America/New_York")
        return dt_et.hour == 15 and dt_et.minute >= 55

    def process_bar(self, bar: dict[str, Any]) -> None:
        """Process bar and generate trading signals."""
        # Check regime gating
        if not self._check_regime_gating(bar):
            return

        # Check warmup
        if not self._check_warmup(bar):
            return

        # Update price history
        self._update_price_history(bar)

        current_regime = bar.get("f__regime__current", RegimeType.OFF)

        # Get position
        position = self.get_position(bar["symbol"])

        # Exit logic for existing positions (includes intraday close at 15:55 ET)
        if position and position.quantity != 0:
            self._manage_position(bar, position)
            return

        # If position is closed, remove from active_orders before checking for new entries.
        if bar["symbol"] in self.active_orders:
            del self.active_orders[bar["symbol"]]

        # Entry logic
        if current_regime == RegimeType.BULL:
            self._check_bull_pullback_entry(bar)
        elif current_regime == RegimeType.BEAR:
            self._check_bear_pullback_entry(bar)

    def _check_regime_gating(self, bar: dict[str, Any]) -> bool:
        """Check if strategy is allowed under current regime."""
        if not self.is_allowed():
            return False

        current_regime = bar.get("f__regime__current", RegimeType.OFF)
        return current_regime in self.params.enabled_regimes

    def _check_warmup(self, bar: dict[str, Any]) -> bool:
        """Check if features are warmed up."""
        return bar.get("f__warmup_ok", False)

    def _update_price_history(self, bar: dict[str, Any]) -> None:
        """Update rolling price history for pullback detection."""
        symbol = bar["symbol"]
        if symbol not in self.price_history:
            self.price_history[symbol] = []

        # Add current bar
        self.price_history[symbol].append(bar.copy())

        # Keep only required window
        max_window = max(self.params.pullback_window_bars, 20)  # Extra for calculations
        if len(self.price_history[symbol]) > max_window:
            self.price_history[symbol] = self.price_history[symbol][-max_window:]

    def _check_bull_pullback_entry(self, bar: dict[str, Any]) -> None:
        """Check for BULL pullback entry conditions."""
        symbol = bar["symbol"]

        # Need sufficient history
        if (
            symbol not in self.price_history
            or len(self.price_history[symbol]) < self.params.pullback_window_bars
        ):
            return

        history = self.price_history[symbol]
        session_avwap = bar.get("f__anchor__session_avwap", 0.0)
        if session_avwap == 0.0:
            return

        # NOTE: Regime strength validation removed - trust regime detector

        # Check if currently above AVWAP (reclaim condition)
        if not (bar["close"] > session_avwap):
            return

        # NOTE: ICT discount zone check made optional

        # Look for pullback in recent history
        pullback_detected = False
        swing_low = bar["low"]

        for i in range(-self.params.pullback_window_bars, 0):
            if i + len(history) < 0:
                continue

            hist_bar = history[i]
            avwap_at_time = hist_bar.get("f__anchor__session_avwap", session_avwap)
            atr_at_time = hist_bar.get("f__vol__atr_30", 0.0)

            if atr_at_time == 0.0:
                continue

            # Calculate pullback threshold
            pullback_threshold = max(
                0.0035, 0.006 * atr_at_time / avwap_at_time
            )  # Max of 0.35% or 0.6×ATR%

            # Check if this bar breached AVWAP by sufficient amount
            if hist_bar["low"] <= avwap_at_time * (1 - pullback_threshold):
                pullback_detected = True
                swing_low = min(swing_low, hist_bar["low"])
                break

        if not pullback_detected:
            return

        # Check for overhead bearish FVG (now optional)
        if self.params.require_fvg and self._check_overhead_bearish_fvg(bar):
            return

        # Optional absorption confirmation
        if self.params.require_absorption and not bar.get("f__vpa__absorption", False):
            return

        # Calculate position size and risk
        atr = bar.get("f__vol__atr_30", 0.0)
        if atr < self.params.min_atr_value:
            return

        # Entry signal confirmed
        self._enter_long_pullback(bar, atr, swing_low)

    def _check_bear_pullback_entry(self, bar: dict[str, Any]) -> None:
        """Check for BEAR pullback entry conditions."""
        symbol = bar["symbol"]

        # Need sufficient history
        if (
            symbol not in self.price_history
            or len(self.price_history[symbol]) < self.params.pullback_window_bars
        ):
            return

        history = self.price_history[symbol]
        session_avwap = bar.get("f__anchor__session_avwap", float("inf"))
        if session_avwap == float("inf"):
            return

        # NOTE: Regime strength validation removed - trust regime detector

        # Check if currently below AVWAP (reclaim condition)
        if not (bar["close"] < session_avwap):
            return

        # NOTE: ICT premium zone check made optional

        # Look for pullback in recent history
        pullback_detected = False
        swing_high = bar["high"]

        for i in range(-self.params.pullback_window_bars, 0):
            if i + len(history) < 0:
                continue

            hist_bar = history[i]
            avwap_at_time = hist_bar.get("f__anchor__session_avwap", session_avwap)
            atr_at_time = hist_bar.get("f__vol__atr_30", 0.0)

            if atr_at_time == 0.0:
                continue

            # Calculate pullback threshold
            pullback_threshold = max(0.0035, 0.006 * atr_at_time / avwap_at_time)

            # Check if this bar breached AVWAP by sufficient amount
            if hist_bar["high"] >= avwap_at_time * (1 + pullback_threshold):
                pullback_detected = True
                swing_high = max(swing_high, hist_bar["high"])
                break

        if not pullback_detected:
            return

        # Check for overhead bullish FVG (now optional)
        if self.params.require_fvg and self._check_overhead_bullish_fvg(bar):
            return

        # Optional absorption confirmation
        if self.params.require_absorption and not bar.get("f__vpa__absorption", False):
            return

        # Calculate position size and risk
        atr = bar.get("f__vol__atr_30", 0.0)
        if atr < self.params.min_atr_value:
            return

        # Entry signal confirmed
        self._enter_short_pullback(bar, atr, swing_high)

    def _check_overhead_bearish_fvg(self, bar: dict[str, Any]) -> bool:
        """Check for bearish FVG overhead that would block long entry."""
        fvg_lower = bar.get("f__ict__fvg_bear_lower", 0.0)
        if fvg_lower == 0.0:
            return False

        atr = bar.get("f__vol__atr_30", 0.0)
        if atr == 0.0:
            return False

        # Calculate distance to FVG
        distance = abs(fvg_lower - bar["close"])

        return distance <= self.params.max_bearish_fvg_distance * atr

    def _check_overhead_bullish_fvg(self, bar: dict[str, Any]) -> bool:
        """Check for bullish FVG overhead that would block short entry."""
        fvg_upper = bar.get("f__ict__fvg_bull_upper", 0.0)
        if fvg_upper == 0.0:
            return False

        atr = bar.get("f__vol__atr_30", 0.0)
        if atr == 0.0:
            return False

        # Calculate distance to FVG
        distance = abs(bar["close"] - fvg_upper)

        return distance <= self.params.max_bearish_fvg_distance * atr

    def _enter_long_pullback(
        self, bar: dict[str, Any], atr: float, swing_low: float
    ) -> None:
        """Enter long position on pullback reclaim."""
        symbol = bar["symbol"]
        session_avwap = bar.get("f__anchor__session_avwap", 0.0)

        # Calculate stop loss
        stop_buffer = self.params.stop_buffer_atr * atr
        stop_level = min(
            swing_low - stop_buffer, session_avwap - self.params.atr_stop_multiple * atr
        )

        # Calculate target
        target_level = bar["close"] + self.params.target_multiple * atr

        # Risk/reward check
        risk = bar["close"] - stop_level
        reward = target_level - bar["close"]

        if reward / risk < self.params.min_risk_reward:
            return

        # Calculate position size
        position_size = self.params.max_position_size

        # Create market order
        order = MarketOrder(
            symbol=symbol,
            order_type=OrderType.MARKET,
            quantity=position_size,
            side="BUY",
            ts_submitted=bar["ts"],
            strategy_id=self.name,
        )

        # Log entry and get the entry log
        entry_log = self._log_entry(
            bar, "LONG", position_size, stop_level, target_level, risk, reward
        )

        # Track trade
        trade_info = {
            "entry_bar": bar,
            "stop_level": stop_level,
            "target_level": target_level,
            "atr": atr,
            "swing_low": swing_low,
            "entry_time": bar["ts"],
            "bars_held": 0,
            "max_favorable_excursion": 0.0,
            "trailing_stop": stop_level,
            "entry_log": entry_log,
        }

        self.active_orders[symbol] = trade_info

        # Submit order
        self.submit_order(order)

    def _enter_short_pullback(
        self, bar: dict[str, Any], atr: float, swing_high: float
    ) -> None:
        """Enter short position on pullback reclaim."""
        symbol = bar["symbol"]
        session_avwap = bar.get("f__anchor__session_avwap", float("inf"))

        # Calculate stop loss
        stop_buffer = self.params.stop_buffer_atr * atr
        stop_level = max(
            swing_high + stop_buffer,
            session_avwap + self.params.atr_stop_multiple * atr,
        )

        # Calculate target
        target_level = bar["close"] - self.params.target_multiple * atr

        # Risk/reward check
        risk = stop_level - bar["close"]
        reward = bar["close"] - target_level

        if reward / risk < self.params.min_risk_reward:
            return

        # Calculate position size
        position_size = self.params.max_position_size

        # Create market order
        order = MarketOrder(
            symbol=symbol,
            order_type=OrderType.MARKET,
            quantity=position_size,
            side="SELL",
            ts_submitted=bar["ts"],
            strategy_id=self.name,
        )

        # Log entry and get the entry log
        entry_log = self._log_entry(
            bar, "SHORT", position_size, stop_level, target_level, risk, reward
        )

        # Track trade
        trade_info = {
            "entry_bar": bar,
            "stop_level": stop_level,
            "target_level": target_level,
            "atr": atr,
            "swing_high": swing_high,
            "entry_time": bar["ts"],
            "bars_held": 0,
            "max_favorable_excursion": 0.0,
            "trailing_stop": stop_level,
            "entry_log": entry_log,
        }

        self.active_orders[symbol] = trade_info

        # Submit order
        self.submit_order(order)

    def _manage_position(self, bar: dict[str, Any], position) -> None:
        """Manage existing position with trailing stops and targets."""
        symbol = bar["symbol"]

        if symbol not in self.active_orders:
            return

        trade_info = self.active_orders[symbol]
        trade_info["bars_held"] += 1

        # Update MFE
        if position.quantity > 0:  # Long
            mfe = bar["high"] - trade_info["entry_bar"]["close"]
            trade_info["max_favorable_excursion"] = max(
                trade_info["max_favorable_excursion"], mfe
            )
        else:  # Short
            mfe = trade_info["entry_bar"]["close"] - bar["low"]
            trade_info["max_favorable_excursion"] = max(
                trade_info["max_favorable_excursion"], mfe
            )

        # Check timeout
        if trade_info["bars_held"] >= self.params.timeout_bars:
            self._close_position(bar, position, "Timeout")
            return

        # Check if target reached
        if position.quantity > 0:  # Long position
            if bar["high"] >= trade_info["target_level"]:
                self._close_position(bar, position, "Target reached")
                return
        elif bar["low"] <= trade_info["target_level"]:
            self._close_position(bar, position, "Target reached")
            return

        # Update trailing stop after sufficient MFE
        if (
            trade_info["max_favorable_excursion"]
            >= self.params.trailing_trigger_multiple * trade_info["atr"]
        ):
            if position.quantity > 0:  # Long
                new_trailing_stop = (
                    bar["high"] - self.params.atr_trailing_multiple * trade_info["atr"]
                )
                trade_info["trailing_stop"] = max(
                    trade_info["trailing_stop"], new_trailing_stop
                )
            else:  # Short
                new_trailing_stop = (
                    bar["low"] + self.params.atr_trailing_multiple * trade_info["atr"]
                )
                trade_info["trailing_stop"] = min(
                    trade_info["trailing_stop"], new_trailing_stop
                )

        # Use trailing stop if active, otherwise use initial stop
        stop_level = trade_info["trailing_stop"]

        # Check stop hit
        if position.quantity > 0:  # Long
            if bar["low"] <= stop_level:
                self._close_position(bar, position, "Trailing stop")
        elif bar["high"] >= stop_level:
            self._close_position(bar, position, "Trailing stop")

    def _close_position(self, bar: dict[str, Any], position, reason: str) -> None:
        """Close position and log trade."""
        symbol = bar["symbol"]

        # Determine order side
        side = "SELL" if position.quantity > 0 else "BUY"

        # Create market order
        order = MarketOrder(
            symbol=symbol,
            order_type=OrderType.MARKET,
            quantity=abs(position.quantity),
            side=side,
            ts_submitted=bar["ts"],
            strategy_id=self.name,
        )

        # Submit order
        self.submit_order(order)

        # Log exit
        self._log_exit(bar, position, reason)

    def _log_entry(
        self,
        bar: dict[str, Any],
        side: str,
        size: float,
        stop: float,
        target: float,
        risk: float,
        reward: float,
    ) -> dict:
        """Log trade entry with feature snapshot."""
        entry_log = {
            "timestamp": bar["ts"],
            "symbol": bar["symbol"],
            "action": "ENTRY",
            "side": side,
            "size": size,
            "price": bar["close"],
            "stop": stop,
            "target": target,
            "risk": risk,
            "reward": reward,
            "rr_ratio": reward / risk if risk != 0 else 0,
            "regime": bar.get("f__regime__current", "UNKNOWN"),
            "strategy_type": "pullback",
            "features": {
                "vr": bar.get("f__regime__var_ratio_10_60", 0),
                "adx": bar.get("f__regime__adx_proxy_14", 0),
                "vol": bar.get("f__regime__mod_vol_30", 0),
                "session_avwap": bar.get("f__anchor__session_avwap", 0),
                "avwap_distance": (
                    bar["close"] - bar.get("f__anchor__session_avwap", 0)
                )
                / bar.get("f__anchor__session_avwap", 1),
                "in_discount": bar.get("f__ict__in_discount", False),
                "in_premium": bar.get("f__ict__in_premium", False),
                "fvg_bear_active": bar.get("f__ict__fvg_bear_active", False),
                "fvg_bull_active": bar.get("f__ict__fvg_bull_active", False),
                "absorption": bar.get("f__vpa__absorption", False),
            },
        }

        self.trade_log.append(entry_log)
        return entry_log

    def _log_exit(self, bar: dict[str, Any], position, reason: str) -> None:
        """Log trade exit."""
        symbol = bar["symbol"]

        # Find the most recent entry for this symbol that hasn't been exited
        entry_log = None
        for log in reversed(self.trade_log):
            if log.get("action") == "ENTRY" and log.get("symbol") == symbol:
                # Check if this entry already has a matching exit
                has_exit = any(
                    exit_log.get("action") == "EXIT"
                    and exit_log.get("symbol") == symbol
                    and exit_log.get("timestamp", 0) > log.get("timestamp", 0)
                    for exit_log in self.trade_log[self.trade_log.index(log) + 1 :]
                )
                if not has_exit:
                    entry_log = log
                    break

        if not entry_log:
            # No unmatched entry found - skip logging (prevents corruption from repeated closes)
            return

        exit_log = {
            "timestamp": bar["ts"],
            "symbol": symbol,
            "action": "EXIT",
            "side": "SELL" if position.quantity > 0 else "BUY",
            "size": abs(position.quantity),
            "price": bar["close"],
            "reason": reason,
            "bars_held": self.active_orders.get(symbol, {}).get("bars_held", 0),
            "pnl": self._calculate_pnl(entry_log, bar, position),
            "max_favorable_excursion": self.active_orders.get(symbol, {}).get(
                "max_favorable_excursion", 0.0
            ),
        }

        self.trade_log.append(exit_log)

    def _calculate_pnl(self, entry_log: dict, bar: dict, position) -> float:
        """Calculate realized P&L."""
        if not entry_log:
            return 0.0

        entry_price = entry_log.get("price", 0.0)
        exit_price = bar["close"]
        size = abs(position.quantity)

        if position.quantity > 0:  # Long
            return (exit_price - entry_price) * size
        else:  # Short
            return (entry_price - exit_price) * size

    def get_trade_log(self) -> list[dict]:
        """Get complete trade log."""
        return self.trade_log.copy()

    def on_end(self) -> None:
        """Called when backtest ends."""
        # Log final statistics
        if self.trade_log:
            total_trades = len(
                [log for log in self.trade_log if log["action"] == "EXIT"]
            )
            profitable_trades = len(
                [
                    log
                    for log in self.trade_log
                    if log["action"] == "EXIT" and log.get("pnl", 0) > 0
                ]
            )

            print(f"\n{self.name} Policy Results:")
            print(f"Total trades: {total_trades}")
            print(f"Profitable trades: {profitable_trades}")
            print(
                f"Win rate: {profitable_trades/total_trades:.1%}"
                if total_trades > 0
                else "N/A"
            )

            # Log P&L summary
            total_pnl = sum(
                [log.get("pnl", 0) for log in self.trade_log if log["action"] == "EXIT"]
            )
            print(f"Total P&L: {total_pnl:.2f}")

            # Enhanced telemetry output
            self._log_enhanced_metrics()

    def _analyze_entry_signals(
        self, bar: dict[str, Any], regime: str, entry_reason: str
    ) -> dict[str, Any]:
        """Analyze and attribute entry signals to specific features."""
        signals = {
            "primary_driver": "unknown",
            "contributing_factors": [],
            "signal_strength": 0.0,
            "feature_scores": {},
        }

        # AVWAP-based signals
        avwap_signals = []
        price = bar.get("close", 0)
        session_avwap = bar.get("f__anchor__session_avwap", 0)

        if session_avwap > 0:
            avwap_deviation = (price - session_avwap) / session_avwap
            if abs(avwap_deviation) > 0.002:  # 20 bps deviation
                avwap_signals.append(
                    f"session_avwap_deviation_{avwap_deviation*10000:.0f}bps"
                )

        # Volume profile signals
        poc = bar.get("f__profile__poc", 0)
        vah = bar.get("f__profile__vah", 0)
        val = bar.get("f__profile__val", 0)

        if poc > 0 and vah > 0 and val > 0:
            if val <= price <= vah:
                signals["contributing_factors"].append("value_area_inside")
            elif price > vah:
                signals["contributing_factors"].append("value_area_above")
            else:
                signals["contributing_factors"].append("value_area_below")

        # ICT structure signals
        if bar.get("f__ict__fvg_bull_active", False):
            signals["contributing_factors"].append("fvg_bull_active")
        if bar.get("f__ict__fvg_bear_active", False):
            signals["contributing_factors"].append("fvg_bear_active")
        if bar.get("f__ict__liq_sweep_high", False):
            signals["contributing_factors"].append("liquidity_sweep_high")
        if bar.get("f__ict__liq_sweep_low", False):
            signals["contributing_factors"].append("liquidity_sweep_low")

        # Order flow signals
        ofi = bar.get("f__flow__ofi", 0)
        ofi_trend = bar.get("f__flow__ofi_trend", "neutral")
        if abs(ofi) > 1000:  # Significant order flow imbalance
            signals["contributing_factors"].append(f"ofi_{ofi_trend}_strong")
        elif abs(ofi) > 500:
            signals["contributing_factors"].append(f"ofi_{ofi_trend}_moderate")

        # VPA signals
        if bar.get("f__vpa__absorption", False):
            signals["contributing_factors"].append("absorption_pattern")
        if bar.get("f__vpa__climax", False):
            signals["contributing_factors"].append("climax_pattern")

        # Determine primary driver based on strategy and reason
        if "momentum" in self.name.lower():
            if "breakout" in entry_reason.lower():
                signals["primary_driver"] = "avwap_breakout"
            elif "continuation" in entry_reason.lower():
                signals["primary_driver"] = "trend_continuation"
        elif "pullback" in self.name.lower():
            signals["primary_driver"] = "avwap_pullback"
        elif "rotation" in self.name.lower():
            signals["primary_driver"] = "value_area_rotation"
        elif "sweep" in self.name.lower():
            signals["primary_driver"] = "liquidity_sweep"

        # Calculate signal strength based on number of contributing factors
        signals["signal_strength"] = min(
            len(signals["contributing_factors"]) / 5.0, 1.0
        )

        return signals

    def _get_regime_metrics(self, bar: dict[str, Any], regime: str) -> dict[str, Any]:
        """Get regime-specific metrics and conditions."""
        return {
            "regime": regime,
            "regime_strength": self._calculate_regime_strength(bar),
            "regime_alignment_score": self._calculate_regime_alignment(bar, regime),
            "transition_risk": self._assess_transition_risk(bar, regime),
            "volatility_regime": self._classify_volatility_regime(bar),
        }

    def _calculate_regime_strength(self, bar: dict[str, Any]) -> float:
        """Calculate how strongly the current bar exhibits regime characteristics."""
        vr = bar.get("f__regime__var_ratio_10_60", 1.0)
        adx = bar.get("f__regime__adx_proxy_14", 0)
        vol = bar.get("f__regime__mod_vol_30", 1.0)

        # Normalize and combine features
        vr_score = min(abs(vr - 1.0) * 2, 1.0)  # Deviation from random walk
        adx_score = min(adx / 50.0, 1.0)  # Normalize ADX
        vol_score = min(abs(vol - 1.0) * 2, 1.0)  # Deviation from normal volatility

        return (vr_score + adx_score + vol_score) / 3.0

    def _calculate_regime_alignment(self, bar: dict[str, Any], regime: str) -> float:
        """Calculate how well current conditions align with expected regime behavior."""
        score = 0.5  # Base score

        # Trend alignment for BULL/BEAR regimes
        if regime in ["BULL", "BEAR"]:
            adx = bar.get("f__regime__adx_proxy_14", 0)
            if adx > 30:
                score += 0.3
            elif adx > 20:
                score += 0.15

        # Volatility alignment for STRESS regime
        if regime == "STRESS":
            vol = bar.get("f__regime__mod_vol_30", 1.0)
            if vol > 2.0:
                score += 0.4
            elif vol > 1.5:
                score += 0.2

        # Range-bound alignment for SIDEWAYS regime
        if regime == "SIDEWAYS":
            vr = bar.get("f__regime__var_ratio_10_60", 1.0)
            if 0.9 < vr < 1.1:
                score += 0.3

        return min(score, 1.0)

    def _assess_transition_risk(self, bar: dict[str, Any], regime: str) -> float:
        """Assess risk of regime transition based on current conditions."""
        risk = 0.1  # Base risk

        # High volatility increases transition risk
        vol = bar.get("f__regime__mod_vol_30", 1.0)
        if vol > 2.0:
            risk += 0.3
        elif vol > 1.5:
            risk += 0.15

        # Contradictory signals increase transition risk
        vr = bar.get("f__regime__var_ratio_10_60", 1.0)
        adx = bar.get("f__regime__adx_proxy_14", 0)

        if (
            regime == "BULL"
            and (vr < 1.0 or adx < 20)
            or regime == "BEAR"
            and (vr > 1.0 or adx < 20)
        ):
            risk += 0.2
        elif regime == "SIDEWAYS" and adx > 30:
            risk += 0.25

        return min(risk, 1.0)

    def _classify_volatility_regime(self, bar: dict[str, Any]) -> str:
        """Classify current volatility regime."""
        vol = bar.get("f__regime__mod_vol_30", 1.0)

        if vol > 2.5:
            return "extreme"
        elif vol > 1.8:
            return "high"
        elif vol > 1.3:
            return "elevated"
        elif vol > 0.8:
            return "normal"
        else:
            return "low"

    def _log_enhanced_metrics(self) -> None:
        """Log enhanced performance metrics and attribution."""
        if not self.trade_log:
            return

        # Basic metrics
        exit_logs = [log for log in self.trade_log if log["action"] == "EXIT"]
        if not exit_logs:
            return

        total_trades = len(exit_logs)
        profitable_trades = len([log for log in exit_logs if log.get("pnl", 0) > 0])

        # Regime attribution
        regime_performance = self._calculate_regime_attribution(exit_logs)

        # Feature attribution
        feature_attribution = self._calculate_feature_attribution(exit_logs)

        # Risk metrics
        risk_metrics = self._calculate_risk_metrics(exit_logs)

        # Time-based metrics
        time_metrics = self._calculate_time_metrics(exit_logs)

        # Create comprehensive telemetry payload
        telemetry = {
            "strategy": self.name,
            "timestamp": pd.Timestamp.now().isoformat(),
            "performance": {
                "total_trades": total_trades,
                "profitable_trades": profitable_trades,
                "win_rate": profitable_trades / total_trades if total_trades > 0 else 0,
                "total_pnl": sum([log.get("pnl", 0) for log in exit_logs]),
                "avg_trade": (
                    sum([log.get("pnl", 0) for log in exit_logs]) / total_trades
                    if total_trades > 0
                    else 0
                ),
                "best_trade": (
                    max([log.get("pnl", 0) for log in exit_logs]) if exit_logs else 0
                ),
                "worst_trade": (
                    min([log.get("pnl", 0) for log in exit_logs]) if exit_logs else 0
                ),
            },
            "regime_attribution": regime_performance,
            "feature_attribution": feature_attribution,
            "risk_metrics": risk_metrics,
            "time_metrics": time_metrics,
        }

        # Save telemetry to file for dashboard consumption
        import json
        import os

        telemetry_dir = "runs/telemetry"
        os.makedirs(telemetry_dir, exist_ok=True)

        telemetry_file = os.path.join(telemetry_dir, f"{self.name}_telemetry.json")
        with open(telemetry_file, "w") as f:
            json.dump(telemetry, f, indent=2)

        print(f"\nEnhanced telemetry saved to: {telemetry_file}")

    def _calculate_regime_attribution(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate performance attribution by regime."""
        regime_stats = {}

        for log in exit_logs:
            regime = log.get("regime", "UNKNOWN")
            pnl = log.get("pnl", 0)

            if regime not in regime_stats:
                regime_stats[regime] = {
                    "trades": 0,
                    "profitable": 0,
                    "total_pnl": 0,
                    "win_rate": 0,
                    "avg_trade": 0,
                }

            regime_stats[regime]["trades"] += 1
            if pnl > 0:
                regime_stats[regime]["profitable"] += 1
            regime_stats[regime]["total_pnl"] += pnl

        # Calculate derived metrics
        for _regime, stats in regime_stats.items():
            if stats["trades"] > 0:
                stats["win_rate"] = stats["profitable"] / stats["trades"]
                stats["avg_trade"] = stats["total_pnl"] / stats["trades"]

        return regime_stats

    def _calculate_feature_attribution(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate performance attribution by feature category."""
        feature_stats = {
            "avwap_features": {"trades": 0, "pnl": 0},
            "volume_profile": {"trades": 0, "pnl": 0},
            "ict_structures": {"trades": 0, "pnl": 0},
            "order_flow": {"trades": 0, "pnl": 0},
            "vpa_patterns": {"trades": 0, "pnl": 0},
        }

        for log in exit_logs:
            pnl = log.get("pnl", 0)
            features = log.get("features", {})

            # Check feature presence and attribute
            if features.get("session_avwap", 0) > 0:
                feature_stats["avwap_features"]["trades"] += 1
                feature_stats["avwap_features"]["pnl"] += pnl

            if features.get("profile_poc", 0) > 0:
                feature_stats["volume_profile"]["trades"] += 1
                feature_stats["volume_profile"]["pnl"] += pnl

            if features.get("fvg_bull_active", False) or features.get(
                "fvg_bear_active", False
            ):
                feature_stats["ict_structures"]["trades"] += 1
                feature_stats["ict_structures"]["pnl"] += pnl

            if features.get("ofi", 0) != 0:
                feature_stats["order_flow"]["trades"] += 1
                feature_stats["order_flow"]["pnl"] += pnl

            if features.get("absorption", False) or features.get("climax", False):
                feature_stats["vpa_patterns"]["trades"] += 1
                feature_stats["vpa_patterns"]["pnl"] += pnl

        # Calculate contribution percentages
        total_trades = len(exit_logs)
        for _feature, stats in feature_stats.items():
            if stats["trades"] > 0:
                stats["participation_rate"] = stats["trades"] / total_trades
                stats["avg_pnl"] = stats["pnl"] / stats["trades"]
            else:
                stats["participation_rate"] = 0
                stats["avg_pnl"] = 0

        return feature_stats

    def _calculate_risk_metrics(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate risk-related metrics."""
        pnls = [log.get("pnl", 0) for log in exit_logs]

        if not pnls:
            return {}

        # Calculate risk metrics
        positive_pnls = [pnl for pnl in pnls if pnl > 0]
        negative_pnls = [pnl for pnl in pnls if pnl < 0]

        return {
            "max_drawdown": min(pnls) if pnls else 0,
            "profit_factor": (
                sum(positive_pnls) / abs(sum(negative_pnls))
                if negative_pnls
                else float("inf")
            ),
            "avg_win": sum(positive_pnls) / len(positive_pnls) if positive_pnls else 0,
            "avg_loss": sum(negative_pnls) / len(negative_pnls) if negative_pnls else 0,
            "largest_win": max(pnls) if pnls else 0,
            "largest_loss": min(pnls) if pnls else 0,
            "sharpe_ratio": self._calculate_sharpe_ratio(pnls),
        }

    def _calculate_time_metrics(self, exit_logs: list[dict]) -> dict[str, Any]:
        """Calculate time-based performance metrics."""
        hold_times = [
            log.get("bars_held", 0) for log in exit_logs if "bars_held" in log
        ]

        if not hold_times:
            return {}

        return {
            "avg_hold_time": sum(hold_times) / len(hold_times),
            "max_hold_time": max(hold_times),
            "min_hold_time": min(hold_times),
            "trades_under_30min": len([t for t in hold_times if t < 30]),
            "trades_over_2hr": len([t for t in hold_times if t > 120]),
        }

    def _calculate_sharpe_ratio(self, pnls: list[float]) -> float:
        """Calculate Sharpe ratio for P&L series."""
        if len(pnls) < 2:
            return 0

        avg_pnl = sum(pnls) / len(pnls)
        variance = sum([(pnl - avg_pnl) ** 2 for pnl in pnls]) / (len(pnls) - 1)
        std_dev = variance**0.5

        return avg_pnl / std_dev if std_dev > 0 else 0
