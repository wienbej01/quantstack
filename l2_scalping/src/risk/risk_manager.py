"""Risk Management Module for L2 Scalping System

Implements per-trade risk limits, position sizing, and circuit breakers.
"""

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class RiskStatus(Enum):
    NORMAL = "normal"
    WARNING = "warning"
    BREACH = "breach"
    EMERGENCY_STOP = "emergency_stop"


@dataclass
class Position:
    """Current position information"""

    symbol: str
    quantity: int
    avg_price: float
    unrealized_pnl: float
    timestamp: float


@dataclass
class RiskMetrics:
    """Current risk metrics"""

    daily_pnl: float
    daily_trades: int
    max_position_size: int
    current_positions: Dict[str, Position]
    risk_status: RiskStatus
    last_update: float


class RiskManager:
    """Comprehensive risk management system"""

    def __init__(self, config: Dict):
        self.config = config
        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.positions: Dict[str, Position] = {}
        self.trade_history: List[Dict] = []
        self.risk_status = RiskStatus.NORMAL
        self.last_reset = time.time()

        # Risk limits from config
        self.max_daily_loss = (
            config.get("max_daily_loss_bps", 100) / 10000
        )  # Convert bps to decimal
        self.max_trade_loss = config.get("max_trade_loss_bps", 10) / 10000
        self.max_position_pct = config.get("max_position_pct", 0.01)  # 1% of account
        self.max_daily_trades = config.get("max_daily_trades", 100)

        logger.info(
            f"Risk Manager initialized with limits: "
            f"daily_loss={self.max_daily_loss:.1%}, "
            f"trade_loss={self.max_trade_loss:.1%}, "
            f"position_pct={self.max_position_pct:.1%}"
        )

    def check_pre_trade_risk(
        self, symbol: str, quantity: int, price: float, account_value: float
    ) -> tuple[bool, str]:
        """Check if trade is allowed before execution"""

        # Check daily loss limit
        if self.daily_pnl <= -self.max_daily_loss * account_value:
            return False, f"Daily loss limit breached: {self.daily_pnl:.2f}"

        # Check daily trade limit
        if self.daily_trades >= self.max_daily_trades:
            return False, f"Daily trade limit reached: {self.daily_trades}"

        # Check position size limit
        position_value = abs(quantity) * price
        max_position_value = account_value * self.max_position_pct

        if position_value > max_position_value:
            return (
                False,
                f"Position size too large: {position_value:.2f} > {max_position_value:.2f}",
            )

        # Check if we already have a position in this symbol
        if symbol in self.positions:
            return False, f"Already have position in {symbol}"

        # Check emergency stop
        if self.risk_status == RiskStatus.EMERGENCY_STOP:
            return False, "Emergency stop activated"

        return True, "Risk check passed"

    def calculate_position_size(
        self,
        symbol: str,
        signal_strength: float,
        confidence: float,
        account_value: float,
        price: float,
    ) -> int:
        """Calculate optimal position size"""

        # Base position size (1% of account)
        base_value = account_value * self.max_position_pct
        base_shares = int(base_value / price)

        # Scale by signal strength (0.3-1.0 → 0.5-1.5x)
        strength_multiplier = 0.5 + signal_strength

        # Scale by confidence (0.0-1.0 → 0.5-1.0x)
        confidence_multiplier = 0.5 + 0.5 * confidence

        # Apply risk scaling if we're in drawdown
        drawdown_multiplier = 1.0
        if self.daily_pnl < 0:
            # Reduce size by 50% if in significant drawdown
            drawdown_pct = abs(self.daily_pnl) / (account_value * self.max_daily_loss)
            if drawdown_pct > 0.5:
                drawdown_multiplier = 0.5

        final_shares = int(
            base_shares
            * strength_multiplier
            * confidence_multiplier
            * drawdown_multiplier
        )

        # Ensure minimum viable size
        min_shares = max(1, int(100 / price))  # At least $100 position
        final_shares = max(min_shares, final_shares)

        logger.debug(
            f"Position sizing for {symbol}: base={base_shares}, "
            f"strength={strength_multiplier:.2f}, confidence={confidence_multiplier:.2f}, "
            f"drawdown={drawdown_multiplier:.2f}, final={final_shares}"
        )

        return final_shares

    def add_position(self, symbol: str, quantity: int, price: float) -> None:
        """Add new position to tracking"""
        self.positions[symbol] = Position(
            symbol=symbol,
            quantity=quantity,
            avg_price=price,
            unrealized_pnl=0.0,
            timestamp=time.time(),
        )
        self.daily_trades += 1

        logger.info(f"Added position: {symbol} {quantity}@{price:.4f}")

    def update_position_pnl(self, symbol: str, current_price: float) -> None:
        """Update unrealized P&L for position"""
        if symbol not in self.positions:
            return

        position = self.positions[symbol]
        position.unrealized_pnl = (
            current_price - position.avg_price
        ) * position.quantity

    def close_position(self, symbol: str, exit_price: float) -> float:
        """Close position and return realized P&L"""
        if symbol not in self.positions:
            logger.warning(f"Attempted to close non-existent position: {symbol}")
            return 0.0

        position = self.positions[symbol]
        realized_pnl = (exit_price - position.avg_price) * position.quantity

        # Update daily P&L
        self.daily_pnl += realized_pnl

        # Record trade
        self.trade_history.append(
            {
                "symbol": symbol,
                "quantity": position.quantity,
                "entry_price": position.avg_price,
                "exit_price": exit_price,
                "pnl": realized_pnl,
                "hold_time": time.time() - position.timestamp,
                "timestamp": time.time(),
            }
        )

        # Remove position
        del self.positions[symbol]

        logger.info(
            f"Closed position: {symbol} P&L={realized_pnl:.2f}, Daily P&L={self.daily_pnl:.2f}"
        )

        # Check risk status after trade
        self._update_risk_status()

        return realized_pnl

    def _update_risk_status(self) -> None:
        """Update overall risk status"""
        old_status = self.risk_status

        # Check for emergency stop conditions
        if self.daily_pnl <= -self.max_daily_loss * 0.9:  # 90% of daily limit
            self.risk_status = RiskStatus.EMERGENCY_STOP
        elif self.daily_pnl <= -self.max_daily_loss * 0.7:  # 70% of daily limit
            self.risk_status = RiskStatus.BREACH
        elif self.daily_pnl <= -self.max_daily_loss * 0.5:  # 50% of daily limit
            self.risk_status = RiskStatus.WARNING
        else:
            self.risk_status = RiskStatus.NORMAL

        if old_status != self.risk_status:
            logger.warning(
                f"Risk status changed: {old_status.value} → {self.risk_status.value}"
            )

    def should_stop_trading(self) -> tuple[bool, str]:
        """Check if trading should be stopped"""
        if self.risk_status == RiskStatus.EMERGENCY_STOP:
            return True, "Emergency stop - daily loss limit approached"

        if self.daily_trades >= self.max_daily_trades:
            return True, "Daily trade limit reached"

        return False, "Trading allowed"

    def get_risk_metrics(self, account_value: float) -> RiskMetrics:
        """Get current risk metrics"""
        return RiskMetrics(
            daily_pnl=self.daily_pnl,
            daily_trades=self.daily_trades,
            max_position_size=int(account_value * self.max_position_pct),
            current_positions=self.positions.copy(),
            risk_status=self.risk_status,
            last_update=time.time(),
        )

    def reset_daily_metrics(self) -> None:
        """Reset daily metrics (call at market open)"""
        logger.info(
            f"Resetting daily metrics. Previous: P&L={self.daily_pnl:.2f}, trades={self.daily_trades}"
        )

        self.daily_pnl = 0.0
        self.daily_trades = 0
        self.trade_history.clear()
        self.risk_status = RiskStatus.NORMAL
        self.last_reset = time.time()

        # Close any remaining positions (shouldn't happen in scalping)
        if self.positions:
            logger.warning(f"Found {len(self.positions)} open positions at reset")
            self.positions.clear()


class CircuitBreaker:
    """Emergency circuit breaker for system protection"""

    def __init__(self, config: Dict):
        self.config = config
        self.is_triggered = False
        self.trigger_time: Optional[float] = None
        self.trigger_reason = ""

        # Circuit breaker thresholds
        self.max_loss_rate = (
            config.get("max_loss_rate_per_minute", 50) / 10000
        )  # 50 bps per minute
        self.max_consecutive_losses = config.get("max_consecutive_losses", 5)
        self.min_time_between_trades = (
            config.get("min_time_between_trades_ms", 1000) / 1000
        )

        # State tracking
        self.recent_trades: List[Dict] = []
        self.consecutive_losses = 0
        self.last_trade_time = 0.0

    def check_circuit_breaker(self, trade_pnl: float) -> tuple[bool, str]:
        """Check if circuit breaker should trigger"""
        current_time = time.time()

        # Add trade to recent history
        self.recent_trades.append({"pnl": trade_pnl, "timestamp": current_time})

        # Keep only last minute of trades
        cutoff_time = current_time - 60
        self.recent_trades = [
            t for t in self.recent_trades if t["timestamp"] > cutoff_time
        ]

        # Check loss rate
        recent_pnl = sum(t["pnl"] for t in self.recent_trades)
        if recent_pnl <= -self.max_loss_rate:
            self._trigger_breaker(f"Loss rate exceeded: {recent_pnl:.4f} in 1 minute")
            return True, self.trigger_reason

        # Check consecutive losses
        if trade_pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        if self.consecutive_losses >= self.max_consecutive_losses:
            self._trigger_breaker(f"Consecutive losses: {self.consecutive_losses}")
            return True, self.trigger_reason

        # Check trade frequency
        if current_time - self.last_trade_time < self.min_time_between_trades:
            self._trigger_breaker("Trading too frequently")
            return True, self.trigger_reason

        self.last_trade_time = current_time
        return False, "Circuit breaker OK"

    def _trigger_breaker(self, reason: str) -> None:
        """Trigger the circuit breaker"""
        self.is_triggered = True
        self.trigger_time = time.time()
        self.trigger_reason = reason
        logger.critical(f"CIRCUIT BREAKER TRIGGERED: {reason}")

    def reset_breaker(self) -> None:
        """Reset circuit breaker (manual intervention required)"""
        logger.info("Circuit breaker reset")
        self.is_triggered = False
        self.trigger_time = None
        self.trigger_reason = ""
        self.consecutive_losses = 0
        self.recent_trades.clear()
