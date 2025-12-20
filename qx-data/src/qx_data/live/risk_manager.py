"""Risk management system with kill switch and position limits."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple


@dataclass
class RiskLimits:
    """Risk management limits."""

    daily_loss_limit: float = 500.0
    max_concurrent_positions: int = 4
    max_position_pct: float = 0.25
    max_trades_per_day: int = 50
    min_confidence_threshold: float = 0.65
    max_correlation_exposure: float = 0.5


class RiskManager:
    """Risk management with kill switch and position limits."""

    def __init__(self, limits: RiskLimits, account_value: float = 10000):
        self.limits = limits
        self.account_value = account_value
        self._daily_trades = 0
        self._daily_pnl = 0.0
        self._kill_switch_active = False
        self._kill_switch_reason = ""
        self._active_positions: Dict[str, dict] = {}
        self.logger = logging.getLogger(__name__)

    def can_trade(
        self, symbol: str, confidence: float, position_value: float
    ) -> Tuple[bool, str]:
        """Check if trading is allowed."""

        # Kill switch check
        if self._kill_switch_active:
            return False, f"KILL_SWITCH: {self._kill_switch_reason}"

        # Confidence threshold
        if confidence < self.limits.min_confidence_threshold:
            return (
                False,
                f"LOW_CONFIDENCE: {confidence:.3f} < {self.limits.min_confidence_threshold}",
            )

        # Daily trade limit
        if self._daily_trades >= self.limits.max_trades_per_day:
            return False, f"MAX_DAILY_TRADES: {self._daily_trades}"

        # Concurrent position limit
        active_count = len(
            [p for p in self._active_positions.values() if p["status"] == "OPEN"]
        )
        if active_count >= self.limits.max_concurrent_positions:
            return False, f"MAX_CONCURRENT: {active_count}"

        # Position size limit
        position_pct = position_value / self.account_value
        if position_pct > self.limits.max_position_pct:
            return (
                False,
                f"POSITION_TOO_LARGE: {position_pct:.1%} > {self.limits.max_position_pct:.1%}",
            )

        # Sector correlation check (simplified)
        sector_exposure = self._calculate_sector_exposure(symbol)
        if sector_exposure > self.limits.max_correlation_exposure:
            return False, f"SECTOR_OVEREXPOSED: {sector_exposure:.1%}"

        return True, "OK"

    def record_trade_start(
        self,
        symbol: str,
        direction: str,
        quantity: int,
        entry_price: float,
        confidence: float,
    ):
        """Record trade start."""
        self._daily_trades += 1
        self._active_positions[symbol] = {
            "direction": direction,
            "quantity": quantity,
            "entry_price": entry_price,
            "confidence": confidence,
            "start_time": datetime.now(),
            "status": "OPEN",
        }

        self.logger.info(
            f"Trade started: {symbol} {direction} {quantity}@{entry_price:.2f} "
            f"(confidence={confidence:.3f}, daily_trades={self._daily_trades})"
        )

    def record_trade_end(self, symbol: str, exit_price: float, pnl: float):
        """Record trade end and update P&L."""
        if symbol in self._active_positions:
            self._active_positions[symbol]["status"] = "CLOSED"
            self._active_positions[symbol]["exit_price"] = exit_price
            self._active_positions[symbol]["pnl"] = pnl

        self._daily_pnl += pnl

        self.logger.info(
            f"Trade ended: {symbol} @ {exit_price:.2f} "
            f"(pnl=${pnl:.2f}, daily_pnl=${self._daily_pnl:.2f})"
        )

        # Check kill switch trigger
        if self._daily_pnl <= -self.limits.daily_loss_limit:
            self.trigger_kill_switch(f"Daily loss limit: ${self._daily_pnl:.2f}")

    def trigger_kill_switch(self, reason: str):
        """Activate kill switch."""
        self._kill_switch_active = True
        self._kill_switch_reason = reason
        self.logger.critical(f"🚨 KILL SWITCH ACTIVATED: {reason}")

    def reset_daily_counters(self):
        """Reset daily counters (call at market open)."""
        self._daily_trades = 0
        self._daily_pnl = 0.0
        self._kill_switch_active = False
        self._kill_switch_reason = ""

        # Clear closed positions
        self._active_positions = {
            k: v for k, v in self._active_positions.items() if v["status"] == "OPEN"
        }

        self.logger.info("Daily risk counters reset")

    def get_risk_status(self) -> Dict:
        """Get current risk status."""
        active_positions = [
            p for p in self._active_positions.values() if p["status"] == "OPEN"
        ]

        return {
            "kill_switch_active": self._kill_switch_active,
            "kill_switch_reason": self._kill_switch_reason,
            "daily_trades": self._daily_trades,
            "daily_pnl": self._daily_pnl,
            "active_positions": len(active_positions),
            "daily_loss_remaining": self.limits.daily_loss_limit + self._daily_pnl,
            "trades_remaining": self.limits.max_trades_per_day - self._daily_trades,
            "positions_remaining": self.limits.max_concurrent_positions
            - len(active_positions),
        }

    def _calculate_sector_exposure(self, symbol: str) -> float:
        """Calculate sector exposure (simplified by symbol prefix)."""
        # Simplified: assume symbols starting with same letter are correlated
        prefix = symbol[0] if symbol else ""

        same_sector_value = 0
        for pos in self._active_positions.values():
            if pos["status"] == "OPEN" and pos.get("symbol", "")[0] == prefix:
                same_sector_value += pos["quantity"] * pos["entry_price"]

        return same_sector_value / self.account_value

    def update_account_value(self, new_value: float):
        """Update account value for position sizing."""
        self.account_value = new_value
        self.logger.debug(f"Account value updated: ${new_value:,.2f}")

    def should_reduce_position_size(self) -> bool:
        """Check if position sizes should be reduced due to recent losses."""
        # Reduce size if daily P&L is negative and > 25% of limit
        loss_threshold = -self.limits.daily_loss_limit * 0.25
        return self._daily_pnl < loss_threshold

    def get_adjusted_position_size(self, base_quantity: int) -> int:
        """Get position size adjusted for current risk level."""
        if self.should_reduce_position_size():
            # Reduce by 50% if losses mounting
            return max(1, base_quantity // 2)
        return base_quantity
