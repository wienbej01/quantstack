"""
AAA scoring system for pattern ranking.
Favors moderate metrics over extreme ones.
"""


class AAAScorer:
    """Score patterns using composite AAA criteria."""
    
    def __init__(
        self,
        optimal_win_rate: float = 0.54,
        optimal_sharpe: float = 2.0,
        optimal_t_stat: float = 40.0,
        optimal_samples: int = 50000,
    ):
        self.optimal_win_rate = optimal_win_rate
        self.optimal_sharpe = optimal_sharpe
        self.optimal_t_stat = optimal_t_stat
        self.optimal_samples = optimal_samples
    
    def calculate_aaa_score(
        self,
        pattern: dict,
        current_regime: str = None,
    ) -> float:
        """
        Calculate composite AAA score.
        Higher score = better pattern.
        
        Score components:
        - T-stat (normalized to 0-1)
        - Win rate penalty for extremes
        - Sharpe (capped at optimal)
        - Sample size bonus
        - Regime match bonus
        """
        # T-stat component (25-40 optimal)
        t_score = min(pattern['t_stat'] / self.optimal_t_stat, 1.0)
        
        # Win rate penalty for extremes (54% optimal)
        wr_deviation = abs(pattern['win_rate'] - self.optimal_win_rate)
        wr_penalty = 1 - (wr_deviation / self.optimal_win_rate)
        wr_penalty = max(0, wr_penalty)
        
        # Sharpe cap at optimal
        sharpe_score = min(pattern['sharpe'] / self.optimal_sharpe, 1.0)
        
        # Sample size bonus
        sample_score = min(pattern['n_samples'] / self.optimal_samples, 1.0)
        
        # Regime match bonus
        regime_bonus = 1.0
        if current_regime is not None:
            regime_bonus = 1.5 if pattern.get('regime') == current_regime else 0.5
        
        # Composite score
        score = t_score * wr_penalty * sharpe_score * sample_score * regime_bonus
        
        return score
    
    def rank_patterns(
        self,
        patterns: list,
        current_regime: str = None,
    ) -> list:
        """
        Rank patterns by AAA score.
        
        Returns:
            Sorted list of patterns (highest score first)
        """
        for pattern in patterns:
            pattern['aaa_score'] = self.calculate_aaa_score(pattern, current_regime)
        
        return sorted(patterns, key=lambda p: p['aaa_score'], reverse=True)
