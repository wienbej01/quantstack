"""
Validation gate to check pattern degradation between scan and validation periods.
"""


class ValidationGate:
    """Check if patterns pass validation criteria."""
    
    def __init__(
        self,
        max_win_rate_drop: float = 0.10,
        max_expectancy_drop_pct: float = 0.50,
        max_sharpe_drop_pct: float = 0.40,
        min_validation_trades: int = 20,
    ):
        self.max_win_rate_drop = max_win_rate_drop
        self.max_expectancy_drop_pct = max_expectancy_drop_pct
        self.max_sharpe_drop_pct = max_sharpe_drop_pct
        self.min_validation_trades = min_validation_trades
    
    def passes_validation(
        self,
        scan_metrics: dict,
        val_metrics: dict,
    ) -> tuple[bool, str]:
        """
        Check if pattern passes validation gate.
        
        Args:
            scan_metrics: Metrics from scan period
            val_metrics: Metrics from validation period
        
        Returns:
            (passes, reason)
        """
        # Check trade count
        if val_metrics['n_trades'] < self.min_validation_trades:
            return False, f"Insufficient validation trades ({val_metrics['n_trades']} < {self.min_validation_trades})"
        
        # Check win rate degradation
        wr_drop = abs(scan_metrics['win_rate'] - val_metrics['win_rate'])
        if wr_drop > self.max_win_rate_drop:
            return False, f"Win rate dropped {wr_drop:.1%} (limit: {self.max_win_rate_drop:.1%})"
        
        # Check expectancy degradation
        if scan_metrics['expectancy'] > 0:
            exp_drop_pct = 1 - (val_metrics['expectancy'] / scan_metrics['expectancy'])
            if exp_drop_pct > self.max_expectancy_drop_pct:
                return False, f"Expectancy dropped {exp_drop_pct:.1%} (limit: {self.max_expectancy_drop_pct:.1%})"
        
        # Check Sharpe degradation
        if scan_metrics['sharpe'] > 0:
            sharpe_drop_pct = 1 - (val_metrics['sharpe'] / scan_metrics['sharpe'])
            if sharpe_drop_pct > self.max_sharpe_drop_pct:
                return False, f"Sharpe dropped {sharpe_drop_pct:.1%} (limit: {self.max_sharpe_drop_pct:.1%})"
        
        return True, "PASS"
    
    def calculate_degradation_score(
        self,
        scan_metrics: dict,
        val_metrics: dict,
    ) -> float:
        """
        Calculate degradation score (0-1, lower is better).
        """
        wr_deg = abs(scan_metrics['win_rate'] - val_metrics['win_rate']) / self.max_win_rate_drop
        
        exp_deg = 0
        if scan_metrics['expectancy'] > 0:
            exp_deg = abs(1 - val_metrics['expectancy'] / scan_metrics['expectancy']) / self.max_expectancy_drop_pct
        
        sharpe_deg = 0
        if scan_metrics['sharpe'] > 0:
            sharpe_deg = abs(1 - val_metrics['sharpe'] / scan_metrics['sharpe']) / self.max_sharpe_drop_pct
        
        return (wr_deg + exp_deg + sharpe_deg) / 3
