"""
Regime filter for pattern discovery.
Detects current market regime and filters patterns by regime match.
"""

import pandas as pd


class RegimeFilter:
    """Filter patterns by market regime."""
    
    REGIMES = [
        "bull_high_vol",
        "bull_low_vol",
        "bear_high_vol",
        "bear_low_vol",
    ]
    
    def __init__(self, sma_period: int = 50, vol_threshold: float = 20.0):
        self.sma_period = sma_period
        self.vol_threshold = vol_threshold
    
    def detect_regime(self, spy_data: pd.DataFrame) -> str:
        """
        Detect current SPY regime.
        
        Args:
            spy_data: DataFrame with 'close' column
        
        Returns:
            regime string (e.g., "bull_high_vol")
        """
        # Bull/Bear: Price vs SMA
        spy_data = spy_data.copy()
        spy_data['sma'] = spy_data['close'].rolling(self.sma_period).mean()
        current_price = spy_data['close'].iloc[-1]
        current_sma = spy_data['sma'].iloc[-1]
        
        is_bull = current_price > current_sma
        
        # High/Low Vol: Realized volatility
        spy_data['returns'] = spy_data['close'].pct_change()
        realized_vol = spy_data['returns'].rolling(20).std() * (252 ** 0.5) * 100
        current_vol = realized_vol.iloc[-1]
        
        is_high_vol = current_vol > self.vol_threshold
        
        # Combine
        if is_bull and is_high_vol:
            return "bull_high_vol"
        elif is_bull and not is_high_vol:
            return "bull_low_vol"
        elif not is_bull and is_high_vol:
            return "bear_high_vol"
        else:
            return "bear_low_vol"
    
    def matches_regime(self, pattern: dict, current_regime: str) -> bool:
        """Check if pattern regime matches current regime."""
        return pattern.get('regime') == current_regime
    
    def filter_by_regime(self, patterns: list, current_regime: str) -> list:
        """Filter patterns to only those matching current regime."""
        return [p for p in patterns if self.matches_regime(p, current_regime)]
