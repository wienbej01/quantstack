#!/usr/bin/env python3
"""
Quick AAA test - minimal functionality check
"""

import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from src.overfitting_filter import OverfittingFilter
from src.regime_filter import RegimeFilter
from src.event_filter import EventFilter
from src.aaa_scorer import AAAScorer

def test_aaa_filters():
    """Test AAA filters with mock data."""
    
    print("=" * 60)
    print("AAA FILTER FUNCTIONALITY TEST")
    print("=" * 60)
    
    # Mock patterns (like from old system)
    mock_patterns = [
        {
            'rule': 'ret_60m_bin == 4.0 AND is_first_hour_bin == True',
            'direction': 'LONG',
            'horizon': 'fwd_ret_180m',
            't_stat': 34.3,
            'expectancy': 0.0542,
            'win_rate': 0.526,
            'sharpe': 1.42,
            'n_samples': 147738,
            'regime': 'bull_high_vol'
        },
        {
            'rule': 'atr_14_bin == 0',  # State pattern - should be rejected
            'direction': 'LONG', 
            'horizon': 'fwd_ret_180m',
            't_stat': 49.0,
            'expectancy': 0.018,
            'win_rate': 0.502,
            'sharpe': 1.10,
            'n_samples': 494261,
            'regime': 'bull_low_vol'
        },
        {
            'rule': 'rel_outperform_extreme_bin == True AND session_range_pct_bin == 0',  # Overfit
            'direction': 'LONG',
            'horizon': 'fwd_ret_180m', 
            't_stat': 35.6,
            'expectancy': 0.3159,  # Too high
            'win_rate': 0.8093,    # Too high
            'sharpe': 8.97,        # Too high
            'n_samples': 3964,     # Too low
            'regime': 'bear_high_vol'
        }
    ]
    
    # Initialize filters
    overfit_filter = OverfittingFilter()
    event_filter = EventFilter()
    regime_filter = RegimeFilter()
    scorer = AAAScorer()
    
    current_regime = "bull_high_vol"
    
    print(f"Testing {len(mock_patterns)} patterns...")
    print(f"Current regime: {current_regime}")
    print()
    
    for i, pattern in enumerate(mock_patterns, 1):
        print(f"Pattern {i}: {pattern['rule'][:50]}...")
        
        # Test overfitting filter
        is_overfit, reason = overfit_filter.is_overfit(pattern)
        print(f"  Overfit check: {'❌ REJECT' if is_overfit else '✅ PASS'} - {reason}")
        
        # Test event filter
        is_event = event_filter.is_event_based(pattern['rule'])
        print(f"  Event check: {'✅ PASS' if is_event else '❌ REJECT'} - {'Event-based' if is_event else 'State-based'}")
        
        # Test regime filter
        regime_match = regime_filter.matches_regime(pattern, current_regime)
        print(f"  Regime check: {'✅ PASS' if regime_match else '❌ REJECT'} - {pattern['regime']} vs {current_regime}")
        
        # Test AAA scoring
        aaa_score = scorer.calculate_aaa_score(pattern, current_regime)
        print(f"  AAA Score: {aaa_score:.3f}")
        
        # Overall result
        passes_all = not is_overfit and is_event and regime_match
        print(f"  OVERALL: {'✅ AAA QUALIFIED' if passes_all else '❌ REJECTED'}")
        print()
    
    print("=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)

if __name__ == "__main__":
    test_aaa_filters()
