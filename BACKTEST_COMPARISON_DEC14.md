# Backtest Comparison - December 14, 2024

## Key Finding: Cross-Sectional Features Outperform Full Feature Set

### Results Summary

| Metric | All 57 Features | Cross-Sectional Only (11) | 502 Features |
|--------|-----------------|---------------------------|--------------|
| **Return** | -21.3% | **+8.3%** | TBD |
| **Win Rate** | 48.5% | **50.3%** | 50.4% |
| **Max Drawdown** | -52.9% | **-12.5%** | -53.2% |
| **Trades** | 7,598 | 2,684 | 15,550 |

### Cross-Sectional Features Used (11)
1. cross_rank_ret - Percentile rank of returns vs peers
2. cross_rank_vol - Percentile rank of volume vs peers
3. sector_momentum - Average return of sector peers
4. cross_dispersion - Cross-sectional return dispersion
5. market_breadth - Number of active symbols
6. up_down_ratio - Fraction of stocks with positive returns
7. rel_strength_5 - 5-bar relative strength vs market
8. rel_strength_10 - 10-bar relative strength vs market
9. rel_strength_20 - 20-bar relative strength vs market
10. market_ret_5 - 5-bar market return
11. market_ret_10 - 10-bar market return

### Key Insight

**Single-stock technical features add noise and hurt performance.**

The full 57-feature set (including RSI, MACD, Bollinger Bands, etc.) produced:
- Negative returns (-21.3%)
- Lower win rate (48.5%)
- Higher drawdown (-52.9%)

The cross-sectional features alone produced:
- Positive returns (+8.3%)
- Higher win rate (50.3%)
- Lower drawdown (-12.5%)

### Implication

For this dataset, the optimal strategy is to:
1. Use ONLY cross-sectional/market-relative features
2. Avoid single-stock technical indicators
3. Focus on peer comparison and market breadth signals

This aligns with academic research (Gu et al. 2020) showing cross-sectional features dominate single-stock features.
