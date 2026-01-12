"""
Overfitting filter for pattern discovery.
Rejects patterns with extreme metrics that are likely to degrade OOS.
"""

from typing import Tuple


class OverfittingFilter:
    """Filter to detect and reject overfit patterns."""
    
    def __init__(
        self,
        max_win_rate: float = 0.65,
        max_sharpe: float = 3.0,
        max_expectancy: float = 0.10,
        min_samples: int = 10000,
    ):
        self.max_win_rate = max_win_rate
        self.max_sharpe = max_sharpe
        self.max_expectancy = max_expectancy
        self.min_samples = min_samples
    
    def is_overfit(self, pattern: dict) -> Tuple[bool, str]:
        """
        Check if pattern shows overfitting signals.
        
        Returns:
            (is_overfit, reason)
        """
        if pattern['win_rate'] > self.max_win_rate:
            return True, f"Win rate too high ({pattern['win_rate']:.1%} > {self.max_win_rate:.1%})"
        
        if pattern['sharpe'] > self.max_sharpe:
            return True, f"Sharpe too high ({pattern['sharpe']:.2f} > {self.max_sharpe:.2f})"
        
        if pattern['expectancy'] > self.max_expectancy:
            return True, f"Expectancy too high ({pattern['expectancy']:.3%} > {self.max_expectancy:.3%})"
        
        if pattern['n_samples'] < self.min_samples:
            return True, f"Insufficient samples ({pattern['n_samples']:,} < {self.min_samples:,})"
        
        return False, "PASS"
    
    def calculate_overfit_risk(self, pattern: dict) -> float:
        """
        Calculate overfitting risk score.
        Higher score = higher risk.
        
        Risk = (win_rate - 0.50) * 2 + (sharpe - 1.5) * 0.5 + (expectancy - 0.03) * 10
        """
        wr_risk = max(0, pattern['win_rate'] - 0.50) * 2
        sharpe_risk = max(0, pattern['sharpe'] - 1.5) * 0.5
        exp_risk = max(0, pattern['expectancy'] - 0.03) * 10
        
        return wr_risk + sharpe_risk + exp_risk
