"""Dynamic position sizing and risk management."""

from dataclasses import dataclass

import pandas as pd


@dataclass
class RiskLimits:
    """Risk management limits."""
    
    equity: float
    max_risk_per_trade_pct: float = 0.02  # 2% of equity per trade
    max_daily_loss_pct: float = 0.05  # 5% of equity max daily loss
    min_position_size: int = 1
    max_position_size: int = 1000


class DynamicPositionSizer:
    """Calculate position size based on stop distance and risk limits."""
    
    def __init__(self, risk_limits: RiskLimits):
        self.risk_limits = risk_limits
        self.daily_pnl = 0.0
        self.current_date = None
    
    def reset_daily_pnl(self, date: pd.Timestamp) -> None:
        """Reset daily P&L tracking."""
        if self.current_date is None or date.date() != self.current_date:
            self.daily_pnl = 0.0
            self.current_date = date.date()
    
    def update_daily_pnl(self, pnl: float) -> None:
        """Update daily P&L."""
        self.daily_pnl += pnl
    
    def can_trade(self) -> bool:
        """Check if we can take new trades (daily loss limit)."""
        max_daily_loss = self.risk_limits.equity * self.risk_limits.max_daily_loss_pct
        return self.daily_pnl > -max_daily_loss
    
    def calculate_position_size(
        self,
        entry_price: float,
        stop_price: float,
    ) -> int:
        """
        Calculate position size based on 2% equity risk per trade.
        
        Position size = (Equity * Risk%) / (Entry - Stop)
        """
        if not self.can_trade():
            return 0
        
        stop_distance = abs(entry_price - stop_price)
        if stop_distance < 0.001:  # Minimum stop distance
            return self.risk_limits.min_position_size
        
        # Risk amount in dollars
        risk_amount = self.risk_limits.equity * self.risk_limits.max_risk_per_trade_pct
        
        # Position size = risk amount / stop distance
        position_size = int(risk_amount / stop_distance)
        
        # Clamp to limits
        position_size = max(self.risk_limits.min_position_size, position_size)
        position_size = min(self.risk_limits.max_position_size, position_size)
        
        return position_size
    
    def get_risk_metrics(self) -> dict:
        """Get current risk metrics."""
        max_daily_loss = self.risk_limits.equity * self.risk_limits.max_daily_loss_pct
        remaining_daily_risk = max_daily_loss + self.daily_pnl
        
        return {
            "equity": self.risk_limits.equity,
            "daily_pnl": self.daily_pnl,
            "max_daily_loss": max_daily_loss,
            "remaining_daily_risk": remaining_daily_risk,
            "can_trade": self.can_trade(),
            "daily_loss_pct": self.daily_pnl / self.risk_limits.equity * 100,
        }


def calculate_dynamic_position_size(
    equity: float,
    entry_price: float,
    stop_price: float,
    risk_per_trade_pct: float = 0.02,
    min_size: int = 1,
    max_size: int = 1000,
) -> int:
    """
    Simple function to calculate position size.
    
    Args:
        equity: Current account equity
        entry_price: Entry price
        stop_price: Stop loss price
        risk_per_trade_pct: Risk per trade as % of equity (default 2%)
        min_size: Minimum position size
        max_size: Maximum position size
    
    Returns:
        Position size in shares
    """
    stop_distance = abs(entry_price - stop_price)
    if stop_distance < 0.001:
        return min_size
    
    risk_amount = equity * risk_per_trade_pct
    position_size = int(risk_amount / stop_distance)
    
    return max(min_size, min(max_size, position_size))
