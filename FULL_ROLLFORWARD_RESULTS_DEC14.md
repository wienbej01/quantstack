# Full Roll-Forward Backtest Results - December 14, 2024

## Data Overview

| Period | Rows | Symbols | Days |
|--------|------|---------|------|
| 2023-01-30 to 2024-12-31 | 68,520 | 442 | 442 |
| 2025-01-02 to 2025-09-05 | 33,457 | 315 | 143 |
| **Total** | **101,977** | **493** | **585** |

## Performance Summary

| Period | Return | Win Rate | Max DD | Trades |
|--------|--------|----------|--------|--------|
| **2023-2024 (clean)** | **+29.3%** | 50.1% | -18.2% | 5,689 |
| 2023-2025 (full) | +367.5%* | 52.3% | -18.2% | 12,563 |

*⚠️ 2025 data contains anomalous period (Mar-Apr 2025) with unrealistic returns

## Year-by-Year Performance

| Year | Return | Win Rate | Trades | Notes |
|------|--------|----------|--------|-------|
| 2023 | +6.0% | 49.0% | 2,304 | ✅ Clean |
| 2024 | +21.5% | 50.8% | 3,385 | ✅ Clean |
| 2025 | +340.1% | 54.2% | 6,874 | ⚠️ Anomalous |

## Performance by Regime

| Regime | Win Rate | Avg Return | Trades |
|--------|----------|------------|--------|
| Bull | 54.3% | +0.086% | 6,601 |
| Bear | 50.3% | +0.009% | 3,454 |
| Sideways | 49.8% | +0.073% | 2,508 |

## Key Observations

### 1. Clean Data Performance (2023-2024)
- **+29.3% total return** over ~2 years
- **~14% annualized return**
- Consistent positive performance across both years
- Max drawdown -18.2%

### 2. 2025 Data Anomaly
The period 2025-03-31 to 2025-05-01 shows:
- 5,129 trades in one period (vs ~200-500 normally)
- Unrealistic equity growth ($12K → $48K)
- Likely future/synthetic test data

### 3. Regime Performance
- **Bull regime performs best** (54.3% win rate)
- Bear and sideways regimes near 50%
- Regime-aware approach adds value

## Recommended Use

```bash
# For realistic performance estimates, use 2023-2024 data only
python scripts/regime_aware_strategy.py  # Already filters to 2024

# Expected performance:
# - Annual return: ~14%
# - Win rate: ~50%
# - Max drawdown: ~18%
```

## Configuration

```python
# 11 cross-sectional features
FEATURES = [
    "cross_rank_ret", "cross_rank_vol", "sector_momentum", 
    "cross_dispersion", "market_breadth", "up_down_ratio",
    "rel_strength_5", "rel_strength_10", "rel_strength_20",
    "market_ret_5", "market_ret_10"
]

# Regime-aware GradientBoosting
# Train window: 60 days
# Test window: 20 days
# Signal threshold: 0.55 (high vol) / 0.58 (normal)
# Position sizing: 1% risk, 0.7x in high vol
```
